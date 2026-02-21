"""
Invoice endpoints - using Google Sheets as database
"""
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from services.sheets_database import get_sheets_db
from services.pdf_service import get_pdf_service, WEASYPRINT_AVAILABLE
from services.drive_storage import get_drive_service, sanitize_filename

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

    invoice = db.create_invoice(
        client_id=client_id,
        description=description,
        amount=amount,
        currency=currency,
        issue_date=issue_date,
        due_date=due_date,
        work_dates=work_dates
    )

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
                "due_date": invoice['due_date']
            }
            client_data = {
                "name": client.get('name', ''),
                "address": client.get('address', ''),
                "company_id": client.get('company_id', '')
            }
            pdf_bytes = pdf_service.generate_pdf_bytes(invoice_data, client_data)
            filename = sanitize_filename(invoice['invoice_number'], client.get('name', ''))
            drive = get_drive_service()
            file_id = drive.upload_pdf(pdf_bytes, filename)
            db.update_invoice_drive_file_id(invoice['file_number'], file_id)
            invoice['drive_file_id'] = file_id
            logger.info(f"Saved invoice {invoice['invoice_number']} to Drive: {file_id}")
    except Exception as e:
        logger.warning(f"Drive upload failed for new invoice (non-critical): {e}")

    return invoice


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
        "due_date": invoice['due_date']
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
        "due_date": invoice['due_date']
    }

    client = invoice.get('client', {})
    client_data = {
        "name": client.get('name', ''),
        "address": client.get('address', ''),
        "company_id": client.get('company_id', '')
    }

    filename = f"Faktura_{invoice['invoice_number'].replace('/', '_')}"

    if WEASYPRINT_AVAILABLE:
        try:
            content = pdf_service.generate_pdf_bytes(invoice_data, client_data)

            # Lazy backfill: upload to Drive on first download if not already stored
            if not invoice.get('drive_file_id'):
                try:
                    drive_filename = sanitize_filename(
                        invoice['invoice_number'],
                        client_data.get('name', '')
                    )
                    drive = get_drive_service()
                    file_id = drive.upload_pdf(content, drive_filename)
                    db.update_invoice_drive_file_id(invoice['file_number'], file_id)
                    logger.info(f"Lazy backfill: saved invoice {invoice['invoice_number']} to Drive: {file_id}")
                except Exception as e:
                    logger.warning(f"Lazy Drive upload failed (non-critical): {e}")

            return Response(
                content=content,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename={filename}.pdf"
                }
            )
        except Exception:
            logger.exception(f"PDF generation failed for invoice {invoice_id}")
            # Fall through to HTML fallback

    # Fallback: return HTML as downloadable file
    html = pdf_service.generate_html(invoice_data, client_data)
    return Response(
        content=html.encode('utf-8'),
        media_type="text/html",
        headers={
            "Content-Disposition": f"attachment; filename={filename}.html"
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

    success = db.update_invoice(invoice_id, updates)
    if not success:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return {"success": True, "invoice_id": invoice_id, "updated": list(updates.keys())}


@router.delete("/{invoice_id}")
def delete_invoice(invoice_id: int):
    """Delete an invoice"""
    db = get_sheets_db()
    success = db.delete_invoice(invoice_id)
    if not success:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {"success": True, "invoice_id": invoice_id}


@router.post("/{invoice_id}/mark-paid")
def mark_invoice_paid(invoice_id: int):
    """Mark an invoice as paid"""
    db = get_sheets_db()
    success = db.update_invoice_status(invoice_id, "paid")
    if not success:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {"success": True, "status": "paid"}


@router.post("/{invoice_id}/mark-sent")
def mark_invoice_sent(invoice_id: int):
    """Mark an invoice as sent"""
    db = get_sheets_db()
    success = db.update_invoice_status(invoice_id, "sent")
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
