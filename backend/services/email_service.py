"""
Email service using Gmail API
"""
import os
import base64
import json
import logging
from typing import Optional, List
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from config import config

# Gmail API may not be available locally
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    GMAIL_API_AVAILABLE = True
except ImportError:
    GMAIL_API_AVAILABLE = False
    Request = None
    Credentials = None
    build = None

logger = logging.getLogger(__name__)


class EmailService:
    """Send emails via Gmail API"""

    # Email templates by language
    TEMPLATES = {
        "de": {
            "subject": "Rechnung {invoice_number} - {currency} {amount}",
            "body": """Sehr geehrte Damen und Herren,

anbei erhalten Sie die Rechnung für:
{description}

Bei Fragen stehen wir Ihnen gerne zur Verfügung.

Mit freundlichen Grüßen,
C.D. Grupa Budowlana Hung Dat Nguyen
Tel: 0048 792678888
Email: c.d.consulting.warsaw@gmail.com
"""
        },
        "pl": {
            "subject": "Faktura {invoice_number} - {currency} {amount}",
            "body": """Szanowni Państwo,

w załączeniu przesyłam fakturę za:
{description}

W razie pytań pozostaję do dyspozycji.

Z poważaniem,
C.D. Grupa Budowlana Hung Dat Nguyen
Tel: 0048 792678888
Email: c.d.consulting.warsaw@gmail.com
"""
        },
        "en": {
            "subject": "Invoice {invoice_number} - {currency} {amount}",
            "body": """Dear Sir or Madam,

Please find attached the invoice for:
{description}

If you have any questions, please don't hesitate to contact us.

Best regards,
C.D. Grupa Budowlana Hung Dat Nguyen
Tel: 0048 792678888
Email: c.d.consulting.warsaw@gmail.com
"""
        }
    }

    def __init__(self):
        self.service = None
        self.creds = None

    def _load_credentials(self):
        """Load Gmail credentials from environment (base64 encoded)"""
        token_b64 = config.GMAIL_TOKEN_B64
        if not token_b64:
            raise ValueError("GMAIL_TOKEN_B64 environment variable not set")

        try:
            token_json = base64.b64decode(token_b64).decode('utf-8')
            token_data = json.loads(token_json)
            self.creds = Credentials.from_authorized_user_info(
                token_data,
                scopes=['https://www.googleapis.com/auth/gmail.modify']
            )
        except Exception as e:
            logger.error(f"Failed to load Gmail credentials: {e}")
            raise

    def authenticate(self):
        """Authenticate with Gmail API"""
        if not GMAIL_API_AVAILABLE:
            raise RuntimeError("Gmail API not available - install google-api-python-client")

        if self.service:
            return

        self._load_credentials()

        if self.creds and self.creds.expired and self.creds.refresh_token:
            logger.info("Refreshing expired Gmail token...")
            self.creds.refresh(Request())

        self.service = build('gmail', 'v1', credentials=self.creds)
        logger.info("Gmail API authenticated successfully")

    def detect_language(self, email: str) -> str:
        """Detect language based on email domain"""
        email_lower = email.lower()
        if email_lower.endswith('.de'):
            return 'de'
        elif email_lower.endswith('.ch'):
            return 'de'  # Swiss German
        elif email_lower.endswith('.pl'):
            return 'pl'
        else:
            return 'en'

    def create_message(
        self,
        to: str,
        subject: str,
        body: str,
        attachment_bytes: Optional[bytes] = None,
        attachment_filename: Optional[str] = None
    ) -> dict:
        """Create email message with optional PDF attachment"""
        message = MIMEMultipart()
        message['to'] = to
        message['from'] = 'c.d.consulting.warsaw@gmail.com'
        message['subject'] = subject

        message.attach(MIMEText(body, 'plain'))

        if attachment_bytes and attachment_filename:
            part = MIMEBase('application', 'pdf')
            part.set_payload(attachment_bytes)
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename="{attachment_filename}"'
            )
            message.attach(part)
            logger.info(f"Attached: {attachment_filename}")

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return {'raw': raw}

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        attachment_bytes: Optional[bytes] = None,
        attachment_filename: Optional[str] = None
    ) -> dict:
        """Send an email"""
        if not self.service:
            self.authenticate()

        message = self.create_message(to, subject, body, attachment_bytes, attachment_filename)

        try:
            sent = self.service.users().messages().send(userId='me', body=message).execute()
            logger.info(f"Email sent to {to}! Message ID: {sent['id']}")
            return {"success": True, "message_id": sent['id']}
        except Exception as e:
            logger.error(f"Failed to send email to {to}: {e}")
            return {"success": False, "error": str(e)}

    def send_invoice(
        self,
        invoice_data: dict,
        pdf_bytes: bytes,
        recipients: List[str],
        custom_subject: Optional[str] = None,
        custom_body: Optional[str] = None
    ) -> List[dict]:
        """
        Send invoice to multiple recipients with appropriate language

        Always sends to tax accountants (Polish) + client (their language)
        """
        results = []
        invoice_number = invoice_data.get('invoice_number', '')
        amount = float(invoice_data.get('amount', 0))
        currency = invoice_data.get('currency', 'EUR')
        description = invoice_data.get('description', '')
        file_number = invoice_data.get('file_number', 0)

        filename = f"Faktura_{invoice_number.replace('/', '_')}.pdf"

        # Always send to tax accountants first (Polish)
        for tax_email in config.TAX_ACCOUNTANT_EMAILS:
            template = self.TEMPLATES['pl']
            subject = custom_subject or template['subject'].format(
                invoice_number=invoice_number,
                currency=currency,
                amount=f"{amount:,.2f}"
            )
            body = custom_body or template['body'].format(description=description)

            result = self.send_email(
                to=tax_email,
                subject=subject,
                body=body,
                attachment_bytes=pdf_bytes,
                attachment_filename=filename
            )
            result['recipient'] = tax_email
            result['type'] = 'tax_accountant'
            results.append(result)

        # Send to other recipients (detect language)
        for recipient in recipients:
            if recipient in config.TAX_ACCOUNTANT_EMAILS:
                continue  # Skip if already sent as tax accountant

            lang = self.detect_language(recipient)
            template = self.TEMPLATES[lang]

            subject = custom_subject or template['subject'].format(
                invoice_number=invoice_number,
                currency=currency,
                amount=f"{amount:,.2f}"
            )
            body = custom_body or template['body'].format(description=description)

            result = self.send_email(
                to=recipient,
                subject=subject,
                body=body,
                attachment_bytes=pdf_bytes,
                attachment_filename=filename
            )
            result['recipient'] = recipient
            result['type'] = 'client'
            results.append(result)

        return results


# Singleton instance
_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """Get email service singleton"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
