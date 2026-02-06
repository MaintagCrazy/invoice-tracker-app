"""
Invoice CRUD endpoints
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from models.database import get_db, Invoice, Client
from models.schemas import (
    InvoiceCreate, InvoiceUpdate, Invoice as InvoiceSchema, InvoiceWithClient,
    DashboardStats
)
from services.invoice_service import InvoiceService
from services.pdf_service import get_pdf_service, WEASYPRINT_AVAILABLE

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


@router.get("/", response_model=List[InvoiceWithClient])
def list_invoices(
    status: Optional[str] = None,
    client_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """List all invoices with optional filters"""
    service = InvoiceService(db)
    invoices = service.list_invoices(
        status=status,
        client_id=client_id,
        limit=limit,
        offset=offset
    )
    return invoices


@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(db: Session = Depends(get_db)):
    """Get dashboard statistics"""
    service = InvoiceService(db)
    return service.get_dashboard_stats()


@router.post("/", response_model=InvoiceSchema)
def create_invoice(
    invoice: InvoiceCreate,
    db: Session = Depends(get_db)
):
    """Create a new invoice"""
    # Verify client exists
    client = db.query(Client).filter(Client.id == invoice.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    service = InvoiceService(db)
    created = service.create_invoice(
        client_id=invoice.client_id,
        description=invoice.description,
        amount=invoice.amount,
        currency=invoice.currency,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        work_dates=invoice.work_dates
    )
    return created


@router.get("/{invoice_id}", response_model=InvoiceWithClient)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Get a single invoice by ID"""
    service = InvoiceService(db)
    invoice = service.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.patch("/{invoice_id}", response_model=InvoiceSchema)
def update_invoice(
    invoice_id: int,
    update: InvoiceUpdate,
    db: Session = Depends(get_db)
):
    """Update an invoice"""
    service = InvoiceService(db)

    # Convert status enum to string if present
    update_data = update.model_dump(exclude_unset=True)
    if 'status' in update_data and update_data['status']:
        update_data['status'] = update_data['status'].value

    invoice = service.update_invoice(invoice_id, **update_data)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.get("/{invoice_id}/preview")
def preview_invoice_pdf(invoice_id: int, db: Session = Depends(get_db)):
    """Generate and return PDF preview"""
    service = InvoiceService(db)
    invoice = service.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    pdf_service = get_pdf_service()

    # Prepare invoice data
    invoice_data = {
        "invoice_number": invoice.invoice_number,
        "description": invoice.description,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "issue_date": invoice.issue_date,
        "due_date": invoice.due_date
    }

    # Prepare client data
    client_data = {
        "name": invoice.client.name,
        "address": invoice.client.address,
        "company_id": invoice.client.company_id
    }

    content = pdf_service.generate_pdf_bytes(invoice_data, client_data)

    # Return appropriate content type
    if WEASYPRINT_AVAILABLE:
        return Response(
            content=content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename=Faktura_{invoice.invoice_number.replace('/', '_')}.pdf"
            }
        )
    else:
        # Return HTML preview when PDF generation not available
        return Response(
            content=content,
            media_type="text/html",
            headers={
                "Content-Disposition": "inline"
            }
        )


@router.post("/{invoice_id}/mark-paid", response_model=InvoiceSchema)
def mark_invoice_paid(invoice_id: int, db: Session = Depends(get_db)):
    """Mark an invoice as paid"""
    service = InvoiceService(db)
    invoice = service.mark_as_paid(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice
