"""
Email sending endpoints - using Google Sheets as database
Hard rule: every email requires explicit user authorization (confirmed=True)
"""
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks

from models.schemas import SendEmailRequest
from services.sheets_database import get_sheets_db
from services.pdf_service import get_pdf_service
from services.email_service import get_email_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/invoices", tags=["email"])


def _send_invoice_background(
    invoice_data: dict,
    client_data: dict,
    pdf_bytes: bytes,
    recipients: list,
    custom_subject: str | None,
    custom_message: str | None,
    invoice_id: int
):
    """Background task: send invoice emails and update status"""
    email_service = get_email_service()
    db = get_sheets_db()

    try:
        results = email_service.send_invoice(
            invoice_data=invoice_data,
            pdf_bytes=pdf_bytes,
            recipients=recipients,
            custom_subject=custom_subject,
            custom_body=custom_message
        )

        if any(r['success'] for r in results):
            db.update_invoice_status(invoice_id, "sent")

        success_count = sum(1 for r in results if r['success'])
        fail_count = sum(1 for r in results if not r['success'])
        logger.info(f"Invoice {invoice_id} email: {success_count} sent, {fail_count} failed")

        # Log to audit if available
        try:
            from services.audit_service import get_audit_service
            audit = get_audit_service()
            audit.log_action(
                action="email_sent" if success_count > 0 else "email_send_failed",
                entity_type="invoice",
                entity_id=str(invoice_id),
                details={"recipients": recipients, "success": success_count, "failed": fail_count}
            )
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Background email send failed for invoice {invoice_id}: {e}")
        try:
            from services.audit_service import get_audit_service
            audit = get_audit_service()
            audit.log_action(
                action="email_send_failed",
                entity_type="invoice",
                entity_id=str(invoice_id),
                details={"error": str(e)}
            )
        except Exception:
            pass


@router.post("/{invoice_id}/send")
async def send_invoice(
    invoice_id: int,
    background_tasks: BackgroundTasks,
    request: SendEmailRequest = SendEmailRequest()
):
    """
    Send invoice via email. Requires confirmed=True.

    Always sends to:
    1. Tax accountants (Polish) - ALWAYS
    2. Client email (if exists) - in their language
    3. Additional recipients - in detected language
    """
    # Hard rule: require explicit confirmation
    if not request.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Email sending requires explicit confirmation. Set confirmed=true."
        )

    db = get_sheets_db()
    pdf_service = get_pdf_service()

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
    client_email = client.get('email')
    if client_email:
        recipients.append(client_email)
    if request.additional_recipients:
        recipients.extend(request.additional_recipients)

    # Queue background email send
    background_tasks.add_task(
        _send_invoice_background,
        invoice_data=invoice_data,
        client_data=client_data,
        pdf_bytes=pdf_bytes,
        recipients=recipients,
        custom_subject=request.custom_subject,
        custom_message=request.custom_message,
        invoice_id=invoice_id
    )

    return {
        "success": True,
        "message": "Email queued for sending",
        "invoice_status": "sending"
    }
