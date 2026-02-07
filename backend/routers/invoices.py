"""
Invoice endpoints - using Google Sheets as database
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Response

from services.sheets_database import get_sheets_db
from services.pdf_service import get_pdf_service, WEASYPRINT_AVAILABLE

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


@router.get("/")
def list_invoices(status: Optional[str] = None):
    """List all invoices from Google Sheet"""
    db = get_sheets_db()
    return db.get_invoices(status=status)


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

    return db.create_invoice(
        client_id=client_id,
        description=description,
        amount=amount,
        currency=currency,
        issue_date=issue_date,
        due_date=due_date,
        work_dates=work_dates
    )


@router.get("/{invoice_id}")
def get_invoice(invoice_id: int):
    """Get a single invoice by ID"""
    db = get_sheets_db()
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.get("/{invoice_id}/preview")
def preview_invoice_pdf(invoice_id: int):
    """Generate and return PDF preview"""
    db = get_sheets_db()
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    pdf_service = get_pdf_service()

    # Prepare invoice data
    invoice_data = {
        "invoice_number": invoice['invoice_number'],
        "description": invoice['description'],
        "amount": invoice['amount'],
        "currency": invoice['currency'],
        "issue_date": invoice['issue_date'],
        "due_date": invoice['due_date']
    }

    # Prepare client data
    client = invoice.get('client', {})
    client_data = {
        "name": client.get('name', ''),
        "address": client.get('address', ''),
        "company_id": client.get('company_id', '')
    }

    content = pdf_service.generate_pdf_bytes(invoice_data, client_data)

    if WEASYPRINT_AVAILABLE:
        return Response(
            content=content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename=Faktura_{invoice['invoice_number'].replace('/', '_')}.pdf"
            }
        )
    else:
        return Response(
            content=content,
            media_type="text/html",
            headers={"Content-Disposition": "inline"}
        )


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
