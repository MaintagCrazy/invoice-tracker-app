"""
Correction invoices (faktura korygująca, FA(3) RodzajFaktury KOR) for invoices already filed in KSeF.

A filed invoice is locked (amount and description cannot change); a change of its value is made
by a correction invoice: a new row in the Database tab, numbered KOR/<original number>, whose
Amount is the signed difference and which is linked to the original (sheets_database columns
"Corrects File #", "Correction Reason", "Correction Type"). It is filed through the same path as
every invoice (ksef_service.file_invoice_in_ksef), whose build_faktura renders it as KOR.

plan_correction() checks and describes a correction without writing anything; the preview route
renders it (XML, XSD result, PDF). create_correction() re-plans on fresh sheet data inside the
create lock, refuses an XML the official FA(3) XSD rejects, and only then writes the row.
"""
import base64
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from services import sheets_database as sdb
from services.ksef_service import (CORRECTION_TYPES, parse_issue_date, render_faktura_xml,
                                   validate_fa3_xml)

logger = logging.getLogger(__name__)

DEFAULT_REASON = "Zmiana wartości usługi"
# 2 = the correction takes effect at its own issue date (a value change agreed after the invoice);
# 1 = at the date the original was recorded (the original carried an error).
DEFAULT_TYPE = 2
TYPE_LABELS = {
    1: "Korekta skutkująca w dacie ujęcia faktury pierwotnej (błąd na fakturze pierwotnej)",
    2: "Korekta skutkująca w dacie wystawienia faktury korygującej (zmiana po wystawieniu faktury)",
}
MAX_NUMBER_SUFFIX = 1000


class CorrectionRefused(ValueError):
    """The correction cannot be made; status is the HTTP status the route answers with."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def _today_pl() -> str:
    """Issue date of a correction: today in Poland (DD.MM.YYYY, the app's date format)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Warsaw")).strftime("%d.%m.%Y")
    except Exception:
        return datetime.now().strftime("%d.%m.%Y")


def correction_number(original_number: str, taken: set) -> str:
    """KOR/<original number>; a further correction of the same invoice gets /2, /3, ...
    A number is never reused, deleted rows included."""
    base = f"KOR/{original_number}"
    if base not in taken:
        return base
    for n in range(2, MAX_NUMBER_SUFFIX):
        candidate = f"{base}/{n}"
        if candidate not in taken:
            return candidate
    raise CorrectionRefused(f"No free correction number left for {original_number}.")


def _taken_numbers(db) -> set:
    """Every invoice number in the Database tab, deleted rows and rows without File # included."""
    return {str(r.get("Invoice Number", "")).strip() for r in db.db_worksheet.get_all_records()}


def _money(value, field: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise CorrectionRefused(f"{field} {value!r} is not a number.", 400)
    if not d.is_finite():
        raise CorrectionRefused(f"{field} {value!r} is not a number.", 400)
    q = d.quantize(Decimal("0.01"))
    if q != d:
        raise CorrectionRefused(f"{field} {value} has more than 2 decimals.", 400)
    return q


def plan_correction(db, original_id: int, new_amount, reason: Optional[str] = None,
                    correction_type: int = DEFAULT_TYPE, issue_date: Optional[str] = None) -> dict:
    """The correction invoice that WOULD be made for invoice `original_id` so that its value
    becomes `new_amount`, as a row dict shaped like sheets_database's (with "correction").
    Writes nothing, files nothing. Raises CorrectionRefused with the reason."""
    invoices = db._load_all_invoices()  # deleted rows included; corrections already linked
    orig = next((i for i in invoices if i["file_number"] == original_id), None)
    if not orig or orig.get("status") == "deleted":
        raise CorrectionRefused(f"Invoice #{original_id} not found.", 404)
    if orig.get("correction") is not None:
        of = orig["correction"].get("original_invoice_number") or f"File # {orig['correction'].get('original_file_number')}"
        raise CorrectionRefused(
            f"Invoice {orig['invoice_number']} is itself a correction (of {of}); "
            "make the new correction to the original invoice instead.")
    if not orig.get("ksef_reference"):
        raise CorrectionRefused(
            f"Invoice {orig['invoice_number']} has no KSeF number, so it cannot be corrected here: "
            "an invoice that is not filed is edited directly; a correction needs the original's KSeF number.")
    if not parse_issue_date(orig.get("issue_date")):
        raise CorrectionRefused(f"Invoice {orig['invoice_number']} has no readable issue date ({orig.get('issue_date')!r}).")
    pending = [c for c in orig.get("corrections", []) if not c.get("ksef_reference")]
    if pending:
        raise CorrectionRefused(
            f"Correction {pending[0]['invoice_number']} of this invoice is not filed in KSeF yet; "
            "file it or delete it before making another.")

    new = _money(new_amount, "New amount")
    if new < 0:
        raise CorrectionRefused(f"The new total cannot be negative ({new}).", 400)
    before = _money(round(float(orig.get("corrected_amount", orig["amount"])), 2), "Current amount")
    diff = new - before
    if diff == 0:
        raise CorrectionRefused(
            f"The new amount equals the current value {orig.get('currency', 'EUR')} {before:,.2f}; nothing to correct.", 400)

    reason = (reason or "").strip() or DEFAULT_REASON
    if len(reason) > 256:
        raise CorrectionRefused("The reason is longer than 256 characters (FA(3) PrzyczynaKorekty limit).", 400)
    try:
        correction_type = int(correction_type)
    except (TypeError, ValueError):
        correction_type = 0
    if correction_type not in CORRECTION_TYPES:
        raise CorrectionRefused("Correction type must be 1 (error on the original) or 2 (change after the invoice).", 400)

    issue = issue_date or _today_pl()
    issue_d, orig_d = parse_issue_date(issue), parse_issue_date(orig["issue_date"])
    if not issue_d or issue_d < orig_d:
        raise CorrectionRefused(f"Correction issue date {issue} is before the original's ({orig['issue_date']}).", 400)

    return {
        "id": None,
        "file_number": None,
        "invoice_number": correction_number(orig["invoice_number"], _taken_numbers(db)),
        "client_id": orig.get("client_id"),
        "client": orig.get("client") or {},
        "description": orig.get("description", ""),
        "amount": float(diff),
        "currency": orig.get("currency", "EUR"),
        "issue_date": issue,
        "due_date": orig.get("due_date", ""),
        "status": "draft",
        "ksef_reference": "",
        "ksef_status": "",
        "ksef_hash": "",
        "correction": {
            "original_file_number": orig["file_number"],
            "original_invoice_number": orig["invoice_number"],
            "original_issue_date": orig["issue_date"],
            "original_ksef_reference": orig["ksef_reference"],
            "original_description": orig.get("description", ""),
            "amount_before": float(before),
            "amount_after": float(new),
            "reason": reason,
            "type": correction_type,
        },
    }


def render_correction(plan: dict, with_pdf: bool = True) -> dict:
    """XML (as the app would file it), its FA(3) XSD result, the PDF/HTML. Raises ValueError
    when the XML cannot be built (for example a buyer without a usable VAT id)."""
    from services.pdf_service import get_pdf_service, WEASYPRINT_AVAILABLE
    client = plan.get("client") or {}
    xml = render_faktura_xml(plan, client)
    errors = validate_fa3_xml(xml)
    client_data = {k: client.get(k, "") for k in ("name", "address", "company_id")}
    pdf = get_pdf_service()
    data = pdf_data(plan)
    html = pdf.generate_html(data, client_data)
    pdf_bytes = pdf.generate_pdf_bytes(data, client_data) if (with_pdf and WEASYPRINT_AVAILABLE) else None
    return {"xml": xml.decode("utf-8"), "xsd_errors": errors, "html": html, "pdf_bytes": pdf_bytes}


def pdf_data(invoice: dict) -> dict:
    """The invoice fields the PDF uses (the same keys every PDF call site passes)."""
    keys = ("invoice_number", "file_number", "description", "amount", "currency", "issue_date",
            "due_date", "ksef_reference", "ksef_hash", "correction")
    return {k: invoice.get(k, "") if k != "correction" else invoice.get(k) for k in keys}


def summary(plan: dict) -> dict:
    c = plan["correction"]
    return {
        "correction_number": plan["invoice_number"],
        "issue_date": plan["issue_date"],
        "due_date": plan["due_date"],
        "client": (plan.get("client") or {}).get("name", ""),
        "description": plan["description"],
        "currency": plan["currency"],
        "original": {
            "id": c["original_file_number"],
            "invoice_number": c["original_invoice_number"],
            "issue_date": c["original_issue_date"],
            "ksef_reference": c["original_ksef_reference"],
        },
        "amount_before": c["amount_before"],
        "amount_after": c["amount_after"],
        "difference": plan["amount"],
        "reason": c["reason"],
        "correction_type": c["type"],
        "correction_type_label": TYPE_LABELS.get(c["type"], ""),
    }


def preview_correction(db, original_id: int, new_amount, reason=None, correction_type=DEFAULT_TYPE) -> dict:
    """Read-only: what the correction would be, its XML, the XSD result and the PDF. No sheet write, no KSeF call."""
    plan = plan_correction(db, original_id, new_amount, reason, correction_type)
    try:
        out = render_correction(plan)
    except ValueError as e:
        raise CorrectionRefused(str(e), 400)
    return {
        **summary(plan),
        "xml": out["xml"],
        "xsd_valid": not out["xsd_errors"],
        "xsd_errors": out["xsd_errors"],
        "html": out["html"],
        "pdf_base64": base64.b64encode(out["pdf_bytes"]).decode() if out["pdf_bytes"] else None,
        "files_in_ksef_on_confirm": True,
        "warning": ("Confirming saves this correction and files it in KSeF with the Polish tax "
                    "authority; a filing is legally binding and cannot be withdrawn."),
    }


def create_correction(db, original_id: int, new_amount, reason=None, correction_type=DEFAULT_TYPE) -> dict:
    """Write the correction row (never files: the caller files it). Re-plans on fresh sheet data
    inside the create lock, so two corrections never get the same number or File #, and refuses
    an XML that fails the official FA(3) XSD before anything is written. Returns the stored row."""
    with sdb._CREATE_LOCK:
        db._cache_invalidate("invoices")
        plan = plan_correction(db, original_id, new_amount, reason, correction_type)
        try:
            xml = render_faktura_xml(plan, plan.get("client") or {})
        except ValueError as e:
            raise CorrectionRefused(str(e), 400)
        errors = validate_fa3_xml(xml)
        if errors:
            raise CorrectionRefused(f"The correction XML fails the FA(3) XSD, nothing saved: {'; '.join(errors[:3])}", 422)
        file_number = db.get_next_file_number()
        c = plan["correction"]
        db.append_correction_row(
            file_number=file_number,
            invoice_number=plan["invoice_number"],
            issue_date=plan["issue_date"],
            due_date=plan["due_date"],
            client_name=(plan.get("client") or {}).get("name", ""),
            description=plan["description"],
            amount=plan["amount"],
            currency=plan["currency"],
            corrects_file_number=c["original_file_number"],
            reason=c["reason"],
            correction_type=c["type"],
        )
    stored = db.get_invoice(file_number)
    sc = (stored or {}).get("correction") or {}
    if not stored or sc.get("error") or stored.get("invoice_number") != plan["invoice_number"] \
            or abs(float(sc.get("amount_after", -1)) - c["amount_after"]) > 0.005:
        raise RuntimeError(
            f"Correction {plan['invoice_number']} was written as File # {file_number} but reading it back "
            f"did not match ({sc.get('error') or 'values differ'}); it is NOT filed. Check the sheet.")
    return stored
