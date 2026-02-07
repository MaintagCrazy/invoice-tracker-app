"""
Email sending endpoints - using Google Sheets as database
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException

from models.schemas import SendEmailRequest
from services.sheets_database import get_sheets_db
from services.pdf_service import get_pdf_service
from services.email_service import get_email_service

router = APIRouter(prefix="/api/invoices", tags=["email"])


@router.post("/{invoice_id}/send")
async def send_invoice(
    invoice_id: int,
    request: SendEmailRequest = SendEmailRequest()
):
    """
    Send invoice via email

    Always sends to:
    1. Tax accountants (Polish) - ALWAYS
    2. Client email (if exists) - in their language
    3. Additional recipients - in detected language
    """
    db = get_sheets_db()
    pdf_service = get_pdf_service()
    email_service = get_email_service()

    # Get invoice
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Generate PDF
    invoice_data = {
        "invoice_number": invoice['invoice_number'],
        "file_number": invoice['file_number'],
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

    pdf_bytes = pdf_service.generate_pdf_bytes(invoice_data, client_data)

    # Build recipient list
    recipients = []

    # Add client email if exists
    client_email = client.get('email')
    if client_email:
        recipients.append(client_email)

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

    # Mark invoice as sent if at least one email succeeded
    if any(r['success'] for r in results):
        db.update_invoice_status(invoice_id, "sent")

    # Summarize results
    success_count = sum(1 for r in results if r['success'])
    fail_count = sum(1 for r in results if not r['success'])

    return {
        "success": success_count > 0,
        "message": f"Sent to {success_count} recipient(s), {fail_count} failed",
        "results": results,
        "invoice_status": "sent" if success_count > 0 else "draft"
    }
