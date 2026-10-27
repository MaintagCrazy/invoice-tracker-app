"""
KSeF 2.0 Service — Submit invoices to Poland's National e-Invoice System.

Maps invoice-tracker-app data to FA(3) schema and submits via ksef2 SDK.
Token and company details come from config.py.
"""
import base64
import hashlib
import logging
import threading
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from config import config

logger = logging.getLogger(__name__)

# Lazy imports — ksef2 is optional, don't crash the app if missing
_ksef2_available = False
try:
    from ksef2 import Client as KsefClient, Environment, FormSchema
    from ksef2.infra.schema.fa3.models.schemat import (
        Faktura, FakturaFa, FakturaFaAdnotacje, FakturaFaAdnotacjeZwolnienie,
        FakturaFaAdnotacjeNoweSrodkiTransportu, FakturaFaAdnotacjePmarzy,
        FakturaFaFaWiersz, FakturaFaPlatnosc, FakturaFaPlatnoscTerminPlatnosci,
        FakturaPodmiot1, FakturaPodmiot2,
        Tnaglowek, TnaglowekKodFormularza, TnaglowekWariantFormularza,
        Tpodmiot1, Tpodmiot2, Tadres,
        TkodWaluty, TrodzajFaktury, TstawkaPodatku, TformaPlatnosci, TkodyKrajowUe,
        TrachunekBankowy, FakturaPodmiot2Jst, FakturaPodmiot2Gv,
    )
    from ksef2.infra.schema.fa3.models.elementarne_typy_danych_v10_0_e import Twybor12, Twybor1
    from ksef2.infra.schema.fa3.models.kody_krajow_v10_0_e import TkodKraju
    from xsdata.models.datatype import XmlDate, XmlDateTime
    from xsdata_pydantic.bindings import XmlSerializer
    _ksef2_available = True
except ImportError:
    logger.warning("ksef2 SDK not installed — KSeF integration disabled")


# ── Currency mapping ─────────────────────────────────────────
CURRENCY_MAP = {
    "PLN": "PLN", "EUR": "EUR", "USD": "USD", "GBP": "GBP",
    "CHF": "CHF", "CZK": "CZK", "VND": "VND",
}

# ── Country detection from VAT ID prefix ─────────────────────
COUNTRY_FROM_VAT = {
    "DE": "DE", "AT": "AT", "FR": "FR", "NL": "NL", "BE": "BE",
    "IT": "IT", "ES": "ES", "CZ": "CZ", "SK": "SK", "HU": "HU",
    "RO": "RO", "BG": "BG", "HR": "HR", "SI": "SI", "LT": "LT",
    "LV": "LV", "EE": "EE", "FI": "FI", "SE": "SE", "DK": "DK",
    "IE": "IE", "PT": "PT", "EL": "GR", "GR": "GR", "LU": "LU",
    "MT": "MT", "CY": "CY", "PL": "PL", "CHE": "CH",
}

EU_COUNTRIES = {
    "DE", "AT", "FR", "NL", "BE", "IT", "ES", "CZ", "SK", "HU",
    "RO", "BG", "HR", "SI", "LT", "LV", "EE", "FI", "SE", "DK",
    "IE", "PT", "GR", "LU", "MT", "CY", "PL",
}


def _dec(value) -> Decimal:
    """Convert to Decimal rounded to 2 places."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _detect_country(company_id: str) -> Optional[str]:
    """Country from the VAT/tax id, or None when it cannot be told (empty id, unknown
    prefix). Never guesses Poland: a German buyer without an id used to be filed with
    23% Polish VAT."""
    cid = (company_id or "").strip().upper().replace(" ", "").replace("-", "")
    if not cid:
        return None
    if cid.startswith("CHE"):
        return "CH"
    for prefix, country in COUNTRY_FROM_VAT.items():
        if cid.startswith(prefix) and len(prefix) == 2:
            return country
    if cid.isdigit() and len(cid) == 10:
        return "PL"  # bare Polish NIP
    return None


# KSeF is mandatory for invoices issued from this date; older ones are never auto-filed.
KSEF_START = date(2026, 4, 1)


def parse_issue_date(date_str) -> Optional[date]:
    """Strict date parse (DD.MM.YYYY, YYYY-MM-DD, DD/MM/YYYY); None when unreadable.
    Never falls back to today."""
    if isinstance(date_str, datetime):
        return date_str.date()
    if isinstance(date_str, date):
        return date_str
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime((date_str or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def ksef_required(invoice: dict) -> bool:
    """True when the invoice has a valid issue date on or after 01.04.2026."""
    d = parse_issue_date(invoice.get("issue_date"))
    return bool(d and d >= KSEF_START)


def _parse_date(date_str: str) -> tuple:
    """Parse DD.MM.YYYY or YYYY-MM-DD to (year, month, day)."""
    if not date_str:
        now = datetime.now()
        return (now.year, now.month, now.day)
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return (dt.year, dt.month, dt.day)
        except ValueError:
            continue
    now = datetime.now()
    return (now.year, now.month, now.day)


def _get_ksef_currency(currency: str) -> "TkodWaluty":
    """Map currency string to KSeF enum."""
    code = CURRENCY_MAP.get(currency.upper(), "EUR")
    return TkodWaluty(code)


def _get_tax_rate(country: str):
    """
    Determine VAT treatment based on buyer country.
    - PL domestic: 23%
    - EU (non-PL): reverse charge (np I)
    - Non-EU: export (0 EX)
    """
    if country == "PL":
        return TstawkaPodatku.VALUE_23, Decimal("0.23")
    elif country in EU_COUNTRIES:
        return TstawkaPodatku.NP_I, Decimal("0")
    else:
        return TstawkaPodatku.VALUE_0_EX, Decimal("0")


def _get_country_enum(country_code: str) -> "TkodKraju":
    """Get TkodKraju enum from 2-letter code."""
    try:
        return TkodKraju(country_code)
    except (ValueError, KeyError):
        return TkodKraju.PL


def build_faktura(invoice: dict, client: dict) -> "Faktura":
    """
    Build a KSeF FA(3) Faktura object from invoice-tracker-app data.

    Args:
        invoice: dict with keys from sheets_database (invoice_number, amount,
                 currency, issue_date, due_date, description, work_dates)
        client:  dict with keys (name, address, company_id, email)

    Returns:
        Faktura object ready for XML serialization and KSeF submission.
    """
    if not _ksef2_available:
        raise RuntimeError("ksef2 SDK not installed")

    company = config.COMPANY
    buyer_country = _detect_country(client.get("company_id", ""))
    if not buyer_country:
        raise ValueError(
            f"Buyer '{client.get('name', '')}' has no usable VAT id / country "
            f"(Company ID '{client.get('company_id', '')}'): cannot choose the VAT treatment. "
            "Add the buyer's VAT id to the client first."
        )
    if not parse_issue_date(invoice.get("issue_date")):
        raise ValueError(f"Invoice issue date '{invoice.get('issue_date')}' is not a valid date.")
    tax_rate_enum, tax_multiplier = _get_tax_rate(buyer_country)

    amount = _dec(invoice["amount"])
    currency = invoice.get("currency", "EUR")

    # For PL domestic: amount is gross, derive net + VAT
    # For EU/export: amount is net (no VAT)
    if buyer_country == "PL":
        gross = amount
        net = (gross / Decimal("1.23")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        vat = gross - net
    else:
        net = amount
        vat = Decimal("0.00")
        gross = net

    issue_y, issue_m, issue_d = _parse_date(invoice.get("issue_date", ""))
    due_y, due_m, due_d = _parse_date(invoice.get("due_date", ""))

    now = datetime.now()

    # ── Build buyer identifier ────────────────────────────────
    buyer_vat = (client.get("company_id") or "").strip()
    buyer_id_kwargs = {}
    if buyer_country == "PL" and buyer_vat:
        # Polish NIP — strip "PL" prefix if present
        nip = buyer_vat.replace("PL", "").replace(" ", "").replace("-", "")
        buyer_id_kwargs["nip"] = nip
    elif buyer_country in EU_COUNTRIES and buyer_vat:
        # FA(3) requires the country code and the number SEPARATELY: KodUE + NrVatUE.
        # Sending "DE306313681" as NrVatUE (prefix embedded, no KodUE) is
        # schema-invalid and KSeF rejects it.
        vat_digits = buyer_vat.replace(" ", "").replace("-", "").upper()
        if vat_digits.startswith(buyer_country):
            vat_digits = vat_digits[len(buyer_country):]
        buyer_id_kwargs["kod_ue"] = TkodyKrajowUe(buyer_country)
        buyer_id_kwargs["nr_vat_ue"] = vat_digits
    elif buyer_vat:
        buyer_id_kwargs["nr_id"] = buyer_vat

    buyer_id_kwargs["nazwa"] = client.get("name", "")

    # ── Build buyer address ───────────────────────────────────
    buyer_addr_kwargs = {
        "kod_kraju": _get_country_enum(buyer_country),
        "adres_l1": client.get("address", "").replace("\n", ", "),
    }

    # ── Tax summary fields ────────────────────────────────────
    # The summary bucket must match the line's rate code, or the invoice reports
    # the turnover under the wrong heading and feeds the wrong box of JPK_V7.
    #   P_13_1   — net taxed at 23%
    #   P_13_8   — supplies/services OUTSIDE the territory of the country ("np")
    #   P_13_6_3 — 0% rate, export
    # (P_13_6_1 is 0%-rated DOMESTIC sales and P_13_6_2 is 0% intra-community
    #  supply of goods — neither describes services to a foreign business.)
    tax_summary = {}
    if buyer_country == "PL":
        tax_summary["p_13_1"] = net   # net at 23%
        tax_summary["p_14_1"] = vat   # VAT at 23%
    elif buyer_country in EU_COUNTRIES:
        tax_summary["p_13_8"] = net    # services outside PL, matches the np I line rate
    else:
        tax_summary["p_13_6_3"] = net  # export, matches the 0 EX line rate

    # ── Adnotacje (annotations) ───────────────────────────────
    # Each flag is 1 = yes, 2 = no, and they are NOT interchangeable:
    #   P_16  metoda kasowa (cash accounting)
    #   P_17  samofakturowanie — the BUYER issued this invoice for us (art. 106d
    #         ust. 1). Only ever 1 with a signed self-billing agreement.
    #   P_18  odwrotne obciążenie — the buyer settles the VAT (reverse charge)
    #   P_18A mechanizm podzielonej płatności (split payment)
    # These were previously mislabelled and shifted by one, which declared
    # self-invoicing on every EU sale while omitting the reverse-charge wording.
    is_reverse_charge = buyer_country in EU_COUNTRIES and buyer_country != "PL"
    adnotacje = FakturaFaAdnotacje(
        p_16=Twybor12.VALUE_2,   # not cash accounting
        p_17=Twybor12.VALUE_2,   # NOT self-invoicing — we issue our own invoices
        p_18=Twybor12.VALUE_1 if is_reverse_charge else Twybor12.VALUE_2,
        p_18_a=Twybor12.VALUE_2,  # no split payment
        # These sub-elements require their negative marker; emitting them empty
        # is schema-invalid.
        zwolnienie=FakturaFaAdnotacjeZwolnienie(p_19_n=Twybor1.VALUE_1),
        nowe_srodki_transportu=FakturaFaAdnotacjeNoweSrodkiTransportu(p_22_n=Twybor1.VALUE_1),
        p_23=Twybor12.VALUE_2,   # no margin scheme
        pmarzy=FakturaFaAdnotacjePmarzy(p_pmarzy_n=Twybor1.VALUE_1),
    )

    # ── Build the Faktura ─────────────────────────────────────
    faktura = Faktura(
        naglowek=Tnaglowek(
            kod_formularza=TnaglowekKodFormularza(value="FA"),
            wariant_formularza=TnaglowekWariantFormularza.VALUE_3,
            data_wytworzenia_fa=XmlDateTime(
                now.year, now.month, now.day,
                now.hour, now.minute, now.second
            ),
            system_info="InvoiceTrackerApp/2.0-KSeF",
        ),
        podmiot1=FakturaPodmiot1(
            dane_identyfikacyjne=Tpodmiot1(
                nip=company["nip"],
                nazwa=company["name"],
            ),
            adres=Tadres(
                kod_kraju=TkodKraju.PL,
                adres_l1=f"{company['address']}, {company['city']}",
            ),
        ),
        podmiot2=FakturaPodmiot2(
            dane_identyfikacyjne=Tpodmiot2(**buyer_id_kwargs),
            adres=Tadres(**buyer_addr_kwargs),
            jst=FakturaPodmiot2Jst.VALUE_2,
            gv=FakturaPodmiot2Gv.VALUE_2,
        ),
        fa=FakturaFa(
            kod_waluty=_get_ksef_currency(currency),
            p_1=XmlDate(issue_y, issue_m, issue_d),
            p_2=invoice["invoice_number"],
            p_6=XmlDate(issue_y, issue_m, issue_d),
            p_15=gross,
            rodzaj_faktury=TrodzajFaktury.VAT,
            adnotacje=adnotacje,
            fa_wiersz=[
                FakturaFaFaWiersz(
                    nr_wiersza_fa=1,
                    p_7=invoice.get("description", "Services"),
                    p_8_a="us\u0142.",
                    p_8_b=Decimal("1"),
                    p_9_a=net,
                    p_11=net,
                    p_11_vat=vat,
                    p_12=tax_rate_enum,
                ),
            ],
            platnosc=FakturaFaPlatnosc(
                # 6 = Przelew (bank transfer). Was 2 = Karta (card), which
                # contradicted the IBAN/SWIFT block on the same invoice.
                forma_platnosci=TformaPlatnosci.VALUE_6,
                termin_platnosci=[
                    FakturaFaPlatnoscTerminPlatnosci(
                        termin=XmlDate(due_y, due_m, due_d)
                    )
                ],
                rachunek_bankowy=[
                    TrachunekBankowy(
                        nr_rb=company["iban"].replace(" ", ""),
                        swift=company["swift"],
                        nazwa_banku=company["bank"],
                    )
                ],
            ),
            **tax_summary,
        ),
    )

    return faktura


def xml_hash_b64url(xml_bytes: bytes) -> str:
    """SHA-256 of the exact invoice XML, base64url without padding (the QR 'wyroznik')."""
    return base64.urlsafe_b64encode(hashlib.sha256(xml_bytes).digest()).decode().rstrip("=")


def _std_to_url(b64: str) -> str:
    """KSeF reports hashes as standard base64; the QR wants base64url without padding."""
    return (b64 or "").replace("+", "-").replace("/", "_").rstrip("=")


class KsefFilingError(RuntimeError):
    """Filing failed or cannot be done; the reason is shown on the invoice."""


class KsefPendingError(RuntimeError):
    """KSeF has the invoice but did not finish in time (SDK polling timeout)."""

    def __init__(self, reference: str):
        super().__init__(f"KSeF is still processing the invoice (reference {reference})")
        self.reference = reference


def _auth():
    env = Environment.PRODUCTION if config.KSEF_ENVIRONMENT == "production" else Environment.TEST
    return KsefClient(env).authentication.with_token(ksef_token=config.KSEF_TOKEN, nip=config.COMPANY["nip"])


def _metadata(auth, invoice: dict, ksef_number: Optional[str] = None):
    """KSeF's own record (ksef_number + invoiceHash) of this seller invoice, or None.
    Read-only query; never raises (None = could not confirm)."""
    try:
        from ksef2.models import InvoicesFilter
        d = parse_issue_date(invoice.get("issue_date"))
        filters = InvoicesFilter.for_seller(
            date_from=d.isoformat(), date_to=(d + timedelta(days=1)).isoformat(),
            seller_nip=config.COMPANY["nip"], invoice_number=invoice["invoice_number"],
        )
        for m in auth.invoices.all_metadata(filters=filters):
            if (ksef_number and m.ksef_number == ksef_number) or (
                not ksef_number and getattr(m, "invoice_number", None) == invoice["invoice_number"]
            ):
                return m
    except Exception as e:
        logger.warning(f"KSeF metadata query failed for {invoice.get('invoice_number')}: {e}")
    return None


def _duplicate_number(exc) -> Optional[str]:
    """originalKsefNumber when KSeF rejected the invoice as a duplicate (status 440)."""
    if getattr(exc, "invoice_status_code", None) == 440:
        ext = getattr(exc, "extensions", None) or {}
        return ext.get("originalKsefNumber") or ext.get("original_ksef_number")
    return None


def submit_invoice_to_ksef(invoice: dict, client: dict) -> dict:
    """
    Build FA(3) and submit to KSeF production.

    Returns dict with ksef_number, ksef_status, invoice_hash (hash of the bytes WE sent;
    empty when KSeF already held the invoice, then the caller reads KSeF's own hash).
    Raises KsefPendingError on an SDK polling timeout (KSeF may well have accepted it).
    A 440 duplicate rejection is returned as success using originalKsefNumber.
    """
    if not _ksef2_available:
        raise RuntimeError("ksef2 SDK not installed — run: pip install ksef2")
    if not config.KSEF_TOKEN:
        raise RuntimeError("KSEF_TOKEN not configured")

    xml_bytes = _render_xml(build_faktura(invoice, client)).encode("utf-8")
    logger.info(f"Submitting invoice {invoice['invoice_number']} to KSeF (NIP: {config.COMPANY['nip']})")

    auth = _auth()
    try:
        with auth.online_session(form_code=FormSchema.FA3) as session:
            result = session.send_invoice_and_wait(invoice_xml=xml_bytes)
    except Exception as e:
        original = _duplicate_number(e)
        if original:
            return {"ksef_number": original, "ksef_status": "Duplikat (440): numer pierwotnej faktury",
                    "invoice_hash": "", "invoice_number": invoice["invoice_number"]}
        if "Timeout" in type(e).__name__ or isinstance(e, TimeoutError):
            raise KsefPendingError(getattr(e, "invoice_reference_number", "") or "?") from e
        raise

    logger.info(f"KSeF submission complete: ksef_number={result.ksef_number}, status={result.status.description}")
    return {
        "ksef_number": result.ksef_number,
        "reference_number": result.reference_number,
        "invoice_hash": xml_hash_b64url(xml_bytes),
        "ksef_status": result.status.description,
        "ksef_status_code": result.status.code,
        "invoice_number": invoice["invoice_number"],
        "submitted_at": datetime.now().isoformat(),
    }


_locks: dict = {}
_locks_guard = threading.Lock()


def _lock_for(file_number: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(file_number, threading.Lock())


def _store_error(db, file_number: int, text: str):
    """Show the reason on the invoice; the sheet layer refuses to overwrite a stored KSeF number."""
    try:
        db.update_invoice(file_number, {"ksef_status": text[:200]})
    except Exception as e:
        logger.error(f"Could not store KSeF status on invoice {file_number}: {e}")


def file_invoice_in_ksef(db, invoice: dict, client: dict) -> dict:
    """File one invoice in KSeF and store number, status and QR hash on its row.

    - Only invoices with a valid issue date on/after 01.04.2026 are filed; others are returned as is.
    - File # must be unique in the sheet, the buyer must have a usable VAT id.
    - One filing at a time per invoice (lock); the invoice is re-read inside the lock, and one
      that already has a KSeF number is never filed again (duplicate guard).
    - A previous attempt that timed out is recovered from KSeF (metadata) before anything is re-sent;
      a 440 duplicate answer is treated as the original's number.
    - Failure is never swallowed: the reason is stored as KSeF Status ("BLAD: ...") and
      KsefFilingError is raised; a stored KSeF number is never overwritten.
    """
    fn = invoice["file_number"]
    try:
        db._find_row(fn)  # raises when File # is on several rows
    except ValueError as e:
        raise KsefFilingError(f"Invoice {invoice.get('invoice_number')} NOT filed: {e}") from e
    if not ksef_required(invoice):
        return invoice

    with _lock_for(fn):
        fresh = db.get_invoice(fn) or invoice
        if fresh.get("ksef_reference"):
            return {**invoice, **fresh}
        client = client or fresh.get("client") or {}
        if not _detect_country(client.get("company_id", "")):
            msg = (f"Buyer '{client.get('name', '')}' has no usable VAT id / country "
                   f"(Company ID '{client.get('company_id', '')}'); add it, then file again.")
            _store_error(db, fn, f"BLAD: {msg}")
            raise KsefFilingError(f"Invoice {invoice.get('invoice_number')} is NOT filed in KSeF: {msg}")

        try:
            # an earlier attempt left a marker/error: ask KSeF whether it actually took the invoice
            if fresh.get("ksef_status") and _ksef2_available and config.KSEF_TOKEN:
                m = _metadata(_auth(), fresh)
                if m:
                    return _save(db, fresh, m.ksef_number, "Sukces (odzyskano z KSeF)", _std_to_url(m.invoice_hash))
            _store_error(db, fn, "W TOKU: wysylanie do KSeF")
            try:
                result = submit_invoice_to_ksef(fresh, client)
            except KsefPendingError as p:
                _store_error(db, fn, f"W TOKU: KSeF jeszcze przetwarza (ref {p.reference}); wyslij ponownie pozniej")
                m = _metadata(_auth(), fresh)
                if not m:
                    raise KsefFilingError(
                        f"Invoice {invoice.get('invoice_number')} sent to KSeF but not confirmed yet "
                        f"(reference {p.reference}). Do NOT file it again by hand; try sending again later, "
                        "the app will pick up the KSeF number.") from p
                result = {"ksef_number": m.ksef_number, "ksef_status": "Sukces (odzyskano z KSeF)",
                          "invoice_hash": _std_to_url(m.invoice_hash)}
            if not result.get("ksef_number"):
                raise RuntimeError(f"KSeF returned no number (status: {result.get('ksef_status')})")
            h = result.get("invoice_hash") or ""
            if not h:  # duplicate answer: the hash must be KSeF's own, never ours
                m = _metadata(_auth(), fresh, ksef_number=result["ksef_number"])
                h = _std_to_url(m.invoice_hash) if m else ""
            return _save(db, fresh, result["ksef_number"], result.get("ksef_status", "submitted"), h)
        except KsefFilingError:
            raise
        except Exception as e:
            logger.error(f"KSeF filing failed for invoice {invoice.get('invoice_number')}: {e}")
            _store_error(db, fn, f"BLAD: {e}")
            raise KsefFilingError(f"Invoice {invoice.get('invoice_number')} is NOT filed in KSeF: {e}") from e


def _save(db, invoice: dict, number: str, status: str, hash_url: str) -> dict:
    updates = {"ksef_reference": number, "ksef_status": status, "ksef_hash": hash_url}
    if not db.update_invoice(invoice["file_number"], updates):
        # Filed but not saved: shout, the number is the only proof it was filed.
        raise KsefFilingError(
            f"Invoice {invoice.get('invoice_number')} WAS filed in KSeF (number {number}, hash {hash_url}) "
            "but saving it to the sheet failed. Record it manually.")
    return {**invoice, **updates}


def ensure_filed(db, invoice_id: int) -> dict:
    """Return the invoice with a KSeF number, filing it first if needed (raises KsefFilingError).
    Invoices that predate KSeF (or have no valid date) are returned as they are."""
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        raise ValueError(f"Invoice #{invoice_id} not found")
    return file_invoice_in_ksef(db, invoice, invoice.get("client") or {})


def require_filed_to_send(invoice: dict) -> None:
    """Raise KsefFilingError when a KSeF-liable invoice has no KSeF number (gate for 'sent')."""
    if ksef_required(invoice) and not invoice.get("ksef_reference"):
        raise KsefFilingError(f"Invoice {invoice.get('invoice_number')} is not filed in KSeF; it cannot be marked or sent.")


def backfill_ksef_hashes(db) -> list:
    """For invoices already filed (KSeF number, no hash): download the filed XML from KSeF by
    number (read-only), cross-check its hash with KSeF's own invoiceHash, store it only on a
    match. A failure on one never stops the rest."""
    if not _ksef2_available:
        raise RuntimeError("ksef2 SDK not installed")
    todo = [i for i in db.get_invoices() if i.get("ksef_reference") and not i.get("ksef_hash")]
    if not todo:
        return []
    results = []
    try:
        auth = _auth()
    except Exception as e:
        logger.error(f"KSeF login failed for backfill: {e}")
        return [{"invoice_number": i["invoice_number"], "ksef_number": i["ksef_reference"], "error": f"KSeF login failed: {e}"} for i in todo]
    for inv in todo:
        number = inv["ksef_reference"]
        row = {"invoice_number": inv["invoice_number"], "ksef_number": number}
        try:
            h = xml_hash_b64url(auth.invoices.download_invoice(ksef_number=number))
            m = _metadata(auth, inv, ksef_number=number)
            if not m:
                row["error"] = "could not read KSeF's own hash to cross-check; not stored"
            elif _std_to_url(m.invoice_hash) != h:
                row["error"] = f"downloaded XML hash {h} != KSeF invoiceHash {_std_to_url(m.invoice_hash)}; not stored"
            else:
                row.update(hash=h, saved=bool(db.update_invoice(inv["file_number"], {"ksef_hash": h})))
        except Exception as e:
            logger.error(f"Hash backfill failed for {number}: {e}")
            row["error"] = str(e)
        results.append(row)
    return results


def _render_xml(faktura) -> str:
    """Serialize the Faktura to FA(3) XML.

    ksef2 switched its schema models from pydantic to plain dataclasses between
    releases, and each needs a different xsdata serializer — the pydantic one
    raises `XmlContextError: Type 'Faktura' is not a dataclass` on the new
    models. The requirement is a floor (`ksef2>=...`), so production can be on
    either; try the model's own binding and fall back rather than failing at the
    last step before submission.
    """
    try:
        return XmlSerializer().render(faktura)
    except Exception as e:
        logger.info(f"pydantic XML binding unusable ({type(e).__name__}), using plain xsdata")
        from xsdata.formats.dataclass.serializers import XmlSerializer as PlainXmlSerializer
        return PlainXmlSerializer().render(faktura)


def _ksef2_version() -> str:
    """Installed ksef2 version — surfaced in health so an SDK bump that changes
    the API is diagnosable from the response instead of a guess."""
    try:
        from importlib.metadata import version
        return version("ksef2")
    except Exception:
        return "unknown"


def check_ksef_health() -> dict:
    """Check KSeF API connectivity and token validity."""
    if not _ksef2_available:
        return {"available": False, "error": "ksef2 SDK not installed"}

    token = config.KSEF_TOKEN
    if not token:
        return {"available": False, "error": "KSEF_TOKEN not configured"}

    env_name = config.KSEF_ENVIRONMENT
    nip = config.COMPANY["nip"]
    try:
        env = Environment.PRODUCTION if env_name == "production" else Environment.TEST
        ksef_client = KsefClient(env)

        # Connectivity probe against a public endpoint (reads only). The SDK
        # renamed this between releases and the pin is a floor, not an exact
        # version — accept either name so a library bump degrades loudly at
        # worst, instead of reporting KSeF dead when it is reachable.
        enc = ksef_client.encryption
        probe = getattr(enc, "get_certificates", None) or getattr(enc, "get_public_key_certificates", None)
        if probe is None:
            raise RuntimeError(
                "ksef2 SDK exposes no known certificate endpoint "
                f"(installed {_ksef2_version()}); the SDK API changed."
            )
        certs = probe()

        # Whether the token still works is the question that actually matters,
        # and connectivity alone never answered it. Authenticating is read-only —
        # it issues a session token and files nothing.
        token_valid, token_error = None, None
        try:
            ksef_client.authentication.with_token(ksef_token=token, nip=nip)
            token_valid = True
        except Exception as auth_err:
            token_valid = False
            token_error = str(auth_err)
            logger.warning(f"KSeF token failed validation: {auth_err}")

        return {
            "available": True,
            "environment": env_name,
            "nip": nip,
            "certificates": len(certs) if certs else 0,
            "sdk_version": _ksef2_version(),
            "token_configured": True,
            "token_valid": token_valid,
            "token_error": token_error,
        }
    except Exception as e:
        return {
            "available": False,
            "environment": env_name,
            "sdk_version": _ksef2_version(),
            "token_configured": True,
            "error": str(e),
        }
