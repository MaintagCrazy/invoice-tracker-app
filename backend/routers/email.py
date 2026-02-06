"""
Email sending endpoints
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models.database import get_db
from models.schemas import SendEmailRequest
from services.invoice_service import InvoiceService
from services.pdf_service import get_pdf_service
from services.email_service import get_email_service

router = APIRouter(prefix="/api/invoices", tags=["email"])


@router.post("/{invoice_id}/send")
async def send_invoice(
    invoice_id: int,
    request: SendEmailRequest = SendEmailRequest(),
    db: Session = Depends(get_db)
):
    """
    Send invoice via email

    Always sends to:
    1. Tax accountants (Polish) - ALWAYS
    2. Client email (if exists) - in their language
    3. Additional recipients - in detected language
    """
    invoice_service = InvoiceService(db)
    pdf_service = get_pdf_service()
    email_service = get_email_service()

    # Get invoice
    invoice = invoice_service.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Generate PDF
    invoice_data = {
        "invoice_number": invoice.invoice_number,
        "file_number": invoice.file_number,
        "description": invoice.description,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "issue_date": invoice.issue_date,
        "due_date": invoice.due_date
    }

    client_data = {
        "name": invoice.client.name,
        "address": invoice.client.address,
        "company_id": invoice.client.company_id
    }

    pdf_bytes = pdf_service.generate_pdf_bytes(invoice_data, client_data)

    # Build recipient list
    recipients = []

    # Add client email if exists
    if invoice.client.email:
        recipients.append(invoice.client.email)

    # Add additional recipients
    if request.additional_recipients:
        recipients.extend(request.additional_recipients)

    # Send emails (tax accountants are automatically included)
    results = email_service.send_invoice(
        invoice_data=invoice_data,
        pdf_bytes=pdf_bytes,
        recipients=recipients,
        custom_subject=request.custom_subject,
        custom_body=request.custom_message
    )

    # Log all email attempts
    for result in results:
        invoice_service.log_email(
            invoice_id=invoice_id,
            recipient=result['recipient'],
            subject=request.custom_subject or f"Invoice {invoice.invoice_number}",
            status="SUCCESS" if result['success'] else "FAILED",
            error_message=result.get('error')
        )

    # Mark invoice as sent if at least one email succeeded
    if any(r['success'] for r in results):
        invoice_service.mark_as_sent(invoice_id)

    # Summarize results
    success_count = sum(1 for r in results if r['success'])
    fail_count = sum(1 for r in results if not r['success'])

    return {
        "success": success_count > 0,
        "message": f"Sent to {success_count} recipient(s), {fail_count} failed",
        "results": results,
        "invoice_status": "sent" if success_count > 0 else "draft"
    }


@router.get("/{invoice_id}/email-logs")
def get_email_logs(invoice_id: int, db: Session = Depends(get_db)):
    """Get email send history for an invoice"""
    invoice_service = InvoiceService(db)
    invoice = invoice_service.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    logs = [
        {
            "id": log.id,
            "recipient": log.recipient,
            "subject": log.subject,
            "status": log.status,
            "sent_at": log.sent_at.isoformat(),
            "error_message": log.error_message
        }
        for log in invoice.email_logs
    ]

    return {"logs": logs}
