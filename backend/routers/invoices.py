"""
Invoice endpoints - using Google Sheets as database
"""
import logging
from decimal import Decimal
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from services import correction_service
from services.sheets_database import get_sheets_db
from services.ksef_service import file_invoice_in_ksef, KsefFilingError, require_filed_to_send
from services.sheets_database import InvoiceLocked, DuplicateFileNumber
from services.pdf_service import get_pdf_service, WEASYPRINT_AVAILABLE
from services.drive_storage import get_drive_service, drive_filename

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


@router.get("/")
def list_invoices(status: Optional[str] = None, client_id: Optional[int] = None):
    """List all invoices from Google Sheet"""
    db = get_sheets_db()
    return db.get_invoices(status=status, client_id=client_id)


@router.get("/stats")
def get_dashboard_stats():
    """Get dashboard statistics"""
    db = get_sheets_db()
    return db.get_stats()


@router.get("/max-sequence")
def get_max_invoice_sequence(month: int = None, year: int = None):
    """Get max invoice sequence for cross-system numbering.
    Used by Allegro invoice system to avoid number overlaps."""
    from datetime import datetime
    now = datetime.now()
    if month is None:
        month = now.month
    if year is None:
        year = now.year

    db = get_sheets_db()
    month_suffix = f"/{month:02d}/{year}"

    invoices = db.get_invoices()
    seq_numbers = []
    for inv in invoices:
        inv_num = inv.get('invoice_number', '')
        if inv_num.endswith(month_suffix):
            try:
                seq = int(inv_num.split('/')[0])
                seq_numbers.append(seq)
            except (ValueError, IndexError):
                pass

    return {
        "month": month,
        "year": year,
        "max_sequence": max(seq_numbers, default=0),
        "count": len(seq_numbers)
    }


@router.post("/")
def create_invoice(
    client_id: int,
    description: str,
    amount: float,
    currency: str = "EUR",
    issue_date: Optional[str] = None,
    due_date: Optional[str] = None,
    work_dates: Optional[str] = None
):
    """Create a new invoice"""
    db = get_sheets_db()

    # Verify client exists
    client = db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    try:
        invoice = db.create_invoice(
            client_id=client_id,
            description=description,
            amount=amount,
            currency=currency,
            issue_date=issue_date,
            due_date=due_date,
            work_dates=work_dates
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Every invoice is filed in KSeF right after it is saved (legal duty). A failure
    # keeps the invoice, shows on it as KSeF Status "BLAD: ..." and in ksef_error.
    try:
        invoice = file_invoice_in_ksef(db, invoice, client)
    except KsefFilingError as e:
        invoice["ksef_error"] = str(e)
        invoice["ksef_status"] = f"BLAD: {e}"[:200]

    # Auto-upload PDF to Google Drive (non-blocking -- don't fail creation)
    try:
        if WEASYPRINT_AVAILABLE:
            pdf_service = get_pdf_service()
            invoice_data = {
                "invoice_number": invoice['invoice_number'],
                "description": invoice['description'],
                "amount": invoice['amount'],
                "currency": invoice['currency'],
                "issue_date": invoice['issue_date'],
                "due_date": invoice['due_date'],
                "ksef_reference": invoice.get('ksef_reference', ''),
                "ksef_hash": invoice.get('ksef_hash', ''),
                "correction": invoice.get('correction')
            }
            client_data = {
                "name": client.get('name', ''),
                "address": client.get('address', ''),
                "company_id": client.get('company_id', '')
            }
            pdf_bytes = pdf_service.generate_pdf_bytes(invoice_data, client_data)
            filename = drive_filename(invoice['file_number'])
            drive = get_drive_service()
            file_id = drive.upload_pdf(pdf_bytes, filename)
            db.update_invoice_drive_file_id(invoice['file_number'], file_id)
            invoice['drive_file_id'] = file_id
            logger.info(f"Saved invoice {invoice['invoice_number']} to Drive as {filename}: {file_id}")
    except Exception as e:
        logger.warning(f"Drive upload failed for new invoice (non-critical): {e}")

    return invoice


@router.get("/deleted/list")
def list_deleted_invoices():
    """List all soft-deleted invoices (trash view)"""
    db = get_sheets_db()
    return db.get_deleted_invoices()


@router.post("/deleted/purge")
def purge_deleted_invoices(days: int = 30):
    """Permanently delete invoices that have been in trash for more than X days"""
    db = get_sheets_db()
    count = db.purge_old_deleted_invoices(days=days)
    return {"success": True, "purged_count": count}


@router.get("/{invoice_id}")
def get_invoice(invoice_id: int):
    """Get a single invoice by ID"""
    db = get_sheets_db()
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.get("/{invoice_id}/preview")
def preview_invoice_html(invoice_id: int):
    """Generate and return HTML preview (always works)"""
    db = get_sheets_db()
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    pdf_service = get_pdf_service()

    invoice_data = {
        "invoice_number": invoice['invoice_number'],
        "description": invoice['description'],
        "amount": invoice['amount'],
        "currency": invoice['currency'],
        "issue_date": invoice['issue_date'],
        "due_date": invoice['due_date'],
        "ksef_reference": invoice.get('ksef_reference', ''),
        "ksef_hash": invoice.get('ksef_hash', ''),
        "correction": invoice.get('correction')
    }

    client = invoice.get('client', {})
    client_data = {
        "name": client.get('name', ''),
        "address": client.get('address', ''),
        "company_id": client.get('company_id', '')
    }

    html = pdf_service.generate_html(invoice_data, client_data)
    return Response(content=html.encode('utf-8'), media_type="text/html")


@router.get("/{invoice_id}/download")
def download_invoice_pdf(invoice_id: int):
    """Download invoice as PDF (falls back to HTML if WeasyPrint unavailable)"""
    db = get_sheets_db()
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    pdf_service = get_pdf_service()

    invoice_data = {
        "invoice_number": invoice['invoice_number'],
        "description": invoice['description'],
        "amount": invoice['amount'],
        "currency": invoice['currency'],
        "issue_date": invoice['issue_date'],
        "due_date": invoice['due_date'],
        "ksef_reference": invoice.get('ksef_reference', ''),
        "ksef_hash": invoice.get('ksef_hash', ''),
        "correction": invoice.get('correction')
    }

    client = invoice.get('client', {})
    client_data = {
        "name": client.get('name', ''),
        "address": client.get('address', ''),
        "company_id": client.get('company_id', '')
    }

    filename = drive_filename(invoice['file_number'])

    if WEASYPRINT_AVAILABLE:
        try:
            content = pdf_service.generate_pdf_bytes(invoice_data, client_data)

            # Lazy backfill: upload to Drive on first download if not already stored
            if not invoice.get('drive_file_id'):
                try:
                    drive = get_drive_service()
                    file_id = drive.upload_pdf(content, filename)
                    db.update_invoice_drive_file_id(invoice['file_number'], file_id)
                    logger.info(f"Lazy backfill: saved {filename} to Drive: {file_id}")
                except Exception as e:
                    logger.warning(f"Lazy Drive upload failed (non-critical): {e}")

            return Response(
                content=content,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename={filename}"
                }
            )
        except Exception:
            logger.exception(f"PDF generation failed for invoice {invoice_id}")
            # Fall through to HTML fallback

    # Fallback: return HTML as downloadable file
    html_filename = f"Faktura {invoice['file_number']}.html"
    html = pdf_service.generate_html(invoice_data, client_data)
    return Response(
        content=html.encode('utf-8'),
        media_type="text/html",
        headers={
            "Content-Disposition": f"attachment; filename={html_filename}"
        }
    )


class InvoicePreviewRequest(BaseModel):
    client_name: str
    amount: float
    currency: str = "EUR"
    description: str = ""
    work_dates: Optional[str] = None


class InvoicePatchRequest(BaseModel):
    description: Optional[str] = None
    amount: Optional[float] = None
    status: Optional[str] = None


@router.post("/preview")
def preview_invoice_draft(data: InvoicePreviewRequest):
    """Generate HTML preview from draft data (no creation)"""
    from datetime import datetime, timedelta
    db = get_sheets_db()
    pdf_service = get_pdf_service()

    client = db.get_client_by_name(data.client_name)
    client_data = {
        "name": client.get("name", data.client_name) if client else data.client_name,
        "address": client.get("address", "") if client else "",
        "company_id": client.get("company_id", "") if client else ""
    }

    now = datetime.now()
    invoice_data = {
        "invoice_number": "PREVIEW",
        "description": data.description,
        "amount": data.amount,
        "currency": data.currency,
        "issue_date": now.strftime("%d.%m.%Y"),
        "due_date": (now + timedelta(days=30)).strftime("%d.%m.%Y")
    }

    html = pdf_service.generate_html(invoice_data, client_data)
    return Response(content=html.encode('utf-8'), media_type="text/html")


class CorrectionRequest(BaseModel):
    """A correction invoice (faktura korygująca) for a filed invoice: its value becomes new_amount.
    correction_type 2 = effect at the correction's date (change agreed after the invoice),
    1 = effect at the original's date (the original carried an error)."""
    new_amount: Decimal
    reason: Optional[str] = None
    correction_type: int = 2
    confirmed: bool = False
    # from the preview: when given, saving refuses if the correction changed since (number,
    # value before or issue date, e.g. another correction meanwhile or past midnight)
    expected_number: Optional[str] = None
    expected_amount_before: Optional[float] = None
    expected_issue_date: Optional[str] = None


@router.post("/{invoice_id}/correction/preview")
def preview_correction(invoice_id: int, data: CorrectionRequest):
    """Read-only: the correction that WOULD be made (number, before, after, difference), its
    FA(3) XML, the XSD result and the PDF (base64) plus HTML. No sheet write, no KSeF call."""
    db = get_sheets_db()
    try:
        return correction_service.preview_correction(db, invoice_id, data.new_amount, data.reason, data.correction_type)
    except correction_service.CorrectionRefused as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.post("/{invoice_id}/correction")
def create_correction(invoice_id: int, data: CorrectionRequest):
    """Save the correction invoice as a new row and file it in KSeF (the same filing path as every
    invoice). Requires {"confirmed": true}: filing is legally binding and cannot be withdrawn.
    A filing failure keeps the row, shows "BLAD: ..." on it and in ksef_error; send it again later."""
    if not data.confirmed:
        raise HTTPException(
            status_code=400,
            detail=("A correction invoice is filed in KSeF when it is saved, which is legally binding and "
                    'cannot be withdrawn. Check the preview, then re-send with {"confirmed": true}.'))
    db = get_sheets_db()
    try:
        correction = correction_service.create_correction(
            db, invoice_id, data.new_amount, data.reason, data.correction_type,
            expected={"correction_number": data.expected_number, "amount_before": data.expected_amount_before,
                      "issue_date": data.expected_issue_date})
    except correction_service.CorrectionRefused as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    except (DuplicateFileNumber, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e))

    client = correction.get("client") or {}
    try:
        correction = file_invoice_in_ksef(db, correction, client)
    except KsefFilingError as e:
        correction["ksef_error"] = str(e)
        correction["ksef_status"] = f"BLAD: {e}"[:200]

    # Drive copy of the PDF, as for a new invoice (non-blocking)
    try:
        if WEASYPRINT_AVAILABLE:
            pdf_bytes = get_pdf_service().generate_pdf_bytes(
                correction_service.pdf_data(correction),
                {k: client.get(k, "") for k in ("name", "address", "company_id")})
            filename = drive_filename(correction['file_number'])
            file_id = get_drive_service().upload_pdf(pdf_bytes, filename)
            db.update_invoice_drive_file_id(correction['file_number'], file_id)
            correction['drive_file_id'] = file_id
    except Exception as e:
        logger.warning(f"Drive upload failed for correction {correction.get('invoice_number')} (non-critical): {e}")

    return {
        **correction,
        "filed": bool(correction.get("ksef_reference")),
        "summary": correction_service.summary(correction),
    }


@router.patch("/{invoice_id}")
def patch_invoice(invoice_id: int, data: InvoicePatchRequest):
    """Update specific fields of an invoice"""
    db = get_sheets_db()

    updates = {}
    if data.description is not None:
        updates["description"] = data.description
    if data.amount is not None:
        updates["amount"] = data.amount
    if data.status is not None:
        updates["status"] = data.status

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        if updates.get("status") == "sent":
            inv = db.get_invoice(invoice_id)
            if inv:
                require_filed_to_send(inv)
        success = db.update_invoice(invoice_id, updates)
    except (InvoiceLocked, DuplicateFileNumber, KsefFilingError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not success:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return {"success": True, "invoice_id": invoice_id, "updated": list(updates.keys())}


@router.delete("/{invoice_id}")
def delete_invoice(invoice_id: int):
    """Soft-delete an invoice (moves to trash, restorable for 30 days)"""
    db = get_sheets_db()
    try:
        success = db.delete_invoice(invoice_id)
    except (InvoiceLocked, DuplicateFileNumber) as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not success:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {"success": True, "invoice_id": invoice_id}


@router.post("/{invoice_id}/restore")
def restore_invoice(invoice_id: int):
    """Restore a soft-deleted invoice from trash"""
    db = get_sheets_db()
    result = db.restore_invoice(invoice_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Invoice not found — it may have been permanently purged")
    if result == "not_deleted":
        raise HTTPException(status_code=409, detail="Invoice is not in trash — it's already active")
    if result == "correction":
        raise HTTPException(status_code=409, detail="A deleted correction invoice is never restored (its values were computed when it was made); make a new correction instead.")
    return {"success": True, "invoice_id": invoice_id, "message": f"Invoice #{invoice_id} restored successfully"}


@router.post("/{invoice_id}/mark-paid")
def mark_invoice_paid(invoice_id: int):
    """Mark an invoice as paid"""
    db = get_sheets_db()
    try:
        success = db.update_invoice_status(invoice_id, "paid")
    except DuplicateFileNumber as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not success:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {"success": True, "status": "paid"}


@router.post("/{invoice_id}/mark-sent")
def mark_invoice_sent(invoice_id: int):
    """Mark an invoice as sent"""
    db = get_sheets_db()
    inv = db.get_invoice(invoice_id)
    try:
        if inv:
            require_filed_to_send(inv)
        success = db.update_invoice_status(invoice_id, "sent")
    except (DuplicateFileNumber, KsefFilingError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not success:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {"success": True, "status": "sent"}


@router.get("/{invoice_id}/payments")
def get_invoice_payments(invoice_id: int):
    """Get all payments for a specific invoice"""
    db = get_sheets_db()

    # Verify invoice exists
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    payments = db.get_payments(invoice_id=invoice_id)
    return {
        "invoice_id": invoice_id,
        "invoice_number": invoice['invoice_number'],
        "amount": invoice['amount'],
        "amount_paid": invoice['amount_paid'],
        "amount_due": invoice['amount_due'],
        "payment_status": invoice['payment_status'],
        "payments": payments
    }
