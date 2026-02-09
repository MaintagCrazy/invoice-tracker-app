"""
Google Sheets as Database Service
Direct read/write to Google Sheets - single source of truth
"""
import os
import json
import base64
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from google.oauth2.service_account import Credentials
import gspread

from config import config

logger = logging.getLogger(__name__)

# Sheet configuration
SHEET_ID = "1xETHFJZO29qJj_UlyTqB29CRyOp7UFi49oEOvmfd084"
DATABASE_TAB = "Database"
CLIENTS_TAB = "Clients"
PAYMENTS_TAB = "Payments"

# Client data (hardcoded for now, can move to sheet later)
DEFAULT_CLIENTS = {
    1: {
        "id": 1,
        "name": "Bauceram GmbH",
        "address": "Am Tonscuppen.2\n53347 Alfter",
        "company_id": "DE306313681",
        "email": "info@bauceram.de"
    },
    2: {
        "id": 2,
        "name": "Clinker Bau Schweiz GmbH",
        "address": "Hinterbergstrasse 26\n6312 Steinhausen",
        "company_id": "CHE-271.aborak.764",
        "email": "info@clinkerbau.ch"
    },
    3: {
        "id": 3,
        "name": "Stuckgeschäft Laufenberg",
        "address": "Servatiusweg 33\n53332 Bornheim",
        "company_id": "",
        "email": None
    },
    4: {
        "id": 4,
        "name": "Schneider & Bitzer GmbH",
        "address": "",
        "company_id": "",
        "email": None
    },
    5: {
        "id": 5,
        "name": "Hillenbrand Bauunternehmen GmbH",
        "address": "",
        "company_id": "",
        "email": None
    },
    6: {
        "id": 6,
        "name": "BUDMAT",
        "address": "",
        "company_id": "",
        "email": None
    }
}

# Map client names to IDs
CLIENT_NAME_TO_ID = {
    "Bauceram GmbH": 1,
    "BauCeram GmbH": 1,
    "bauceram": 1,
    "Clinker Bau Schweiz GmbH": 2,
    "clinker": 2,
    "Stuckgeschäft Laufenberg": 3,
    "laufenberg": 3,
    "Schneider & Bitzer GmbH": 4,
    "schneider": 4,
    "Hillenbrand Bauunternehmen GmbH": 5,
    "hillenbrand": 5,
    "BUDMAT": 6,
    "budmat": 6,
}


class SheetsDatabaseService:
    """Google Sheets as database"""

    def __init__(self):
        self.gc = None
        self.sheet = None
        self.db_worksheet = None
        self._connect()

    def _connect(self):
        """Connect to Google Sheets"""
        try:
            # Try to get credentials from environment (base64 encoded service account)
            sa_b64 = os.environ.get("GOOGLE_SERVICE_ACCOUNT_B64")

            if sa_b64:
                sa_json = base64.b64decode(sa_b64).decode('utf-8')
                sa_info = json.loads(sa_json)
                credentials = Credentials.from_service_account_info(
                    sa_info,
                    scopes=[
                        'https://www.googleapis.com/auth/spreadsheets',
                        'https://www.googleapis.com/auth/drive'
                    ]
                )
            else:
                # Local development - use file
                from UNIVERSAL_CREDENTIALS import UniversalCredentials
                creds = UniversalCredentials()
                credentials = Credentials.from_service_account_file(
                    creds.GOOGLE_SERVICE_ACCOUNT_FILE,
                    scopes=[
                        'https://www.googleapis.com/auth/spreadsheets',
                        'https://www.googleapis.com/auth/drive'
                    ]
                )

            self.gc = gspread.authorize(credentials)
            self.sheet = self.gc.open_by_key(SHEET_ID)
            self.db_worksheet = self.sheet.worksheet(DATABASE_TAB)
            self._init_payments_worksheet()
            logger.info(f"Connected to Google Sheet: {SHEET_ID}")

        except Exception as e:
            logger.error(f"Failed to connect to Google Sheets: {e}")
            raise

    def _init_payments_worksheet(self):
        """Initialize Payments worksheet (create if not exists)"""
        try:
            self.payments_worksheet = self.sheet.worksheet(PAYMENTS_TAB)
        except gspread.exceptions.WorksheetNotFound:
            # Create Payments tab with headers
            self.payments_worksheet = self.sheet.add_worksheet(
                title=PAYMENTS_TAB, rows=1000, cols=10
            )
            headers = [
                "Payment ID", "Invoice #", "Client", "Amount", "Currency",
                "Date", "Method", "Notes", "Created At"
            ]
            self.payments_worksheet.append_row(headers)
            logger.info("Created Payments worksheet")

    # ============ CLIENTS ============

    def get_clients(self) -> List[Dict]:
        """Get all clients"""
        return list(DEFAULT_CLIENTS.values())

    def get_client(self, client_id: int) -> Optional[Dict]:
        """Get client by ID"""
        return DEFAULT_CLIENTS.get(client_id)

    def get_client_by_name(self, name: str) -> Optional[Dict]:
        """Get client by name (partial match)"""
        name_lower = name.lower()
        for client in DEFAULT_CLIENTS.values():
            if name_lower in client["name"].lower():
                return client
        # Try mapping
        client_id = CLIENT_NAME_TO_ID.get(name.lower())
        if client_id:
            return DEFAULT_CLIENTS.get(client_id)
        return None

    # ============ INVOICES ============

    def get_invoices(self, status: Optional[str] = None, client_id: Optional[int] = None) -> List[Dict]:
        """Get all invoices from sheet with payment status"""
        try:
            all_data = self.db_worksheet.get_all_records()

            # Get all payments for calculating amounts
            payments_by_invoice = self._get_payments_by_invoice()

            invoices = []

            for row in all_data:
                if not row.get('File #'):
                    continue

                # Map client name to client object
                client_name = row.get('Client', '')
                client = self.get_client_by_name(client_name) or {
                    "id": 0,
                    "name": client_name,
                    "address": "",
                    "company_id": "",
                    "email": None
                }

                file_number = int(row.get('File #', 0))
                amount = float(row.get('Amount', 0)) if row.get('Amount') else 0

                # Calculate payment status
                invoice_payments = payments_by_invoice.get(file_number, [])
                amount_paid = sum(p['amount'] for p in invoice_payments)
                amount_due = max(0, amount - amount_paid)

                # Determine payment status
                if amount_paid >= amount:
                    payment_status = "paid"
                elif amount_paid > 0:
                    payment_status = "partial"
                else:
                    payment_status = "unpaid"

                invoice = {
                    "id": file_number,
                    "file_number": file_number,
                    "invoice_number": row.get('Invoice Number', ''),
                    "client_id": client["id"],
                    "client": client,
                    "description": row.get('Description', ''),
                    "amount": amount,
                    "amount_paid": amount_paid,
                    "amount_due": amount_due,
                    "payment_status": payment_status,
                    "currency": row.get('Currency', 'EUR'),
                    "issue_date": row.get('Issue Date', ''),
                    "due_date": row.get('Due Date', ''),
                    "status": row.get('Status', 'sent'),  # Assume existing are sent
                    "work_dates": row.get('Work Dates', ''),
                    "created_at": row.get('Created At', ''),
                    "sent_at": None,
                    "paid_at": None,
                    "pdf_path": None
                }
                invoices.append(invoice)

            # Sort by file number descending
            invoices.sort(key=lambda x: x['file_number'], reverse=True)

            # Filter by status if provided
            if status:
                invoices = [i for i in invoices if i['status'] == status]

            # Filter by client_id if provided
            if client_id:
                invoices = [i for i in invoices if i['client_id'] == client_id]

            return invoices

        except Exception as e:
            logger.error(f"Error fetching invoices: {e}")
            return []

    def get_invoice(self, invoice_id: int) -> Optional[Dict]:
        """Get single invoice by ID (file number)"""
        invoices = self.get_invoices()
        for inv in invoices:
            if inv['id'] == invoice_id or inv['file_number'] == invoice_id:
                return inv
        return None

    def get_next_file_number(self) -> int:
        """Get next available file number"""
        invoices = self.get_invoices()
        if not invoices:
            return 1
        return max(inv['file_number'] for inv in invoices) + 1

    def get_next_invoice_number(self) -> str:
        """Generate invoice number: XX/MM/YYYY"""
        now = datetime.now()
        month_suffix = f"/{now.month:02d}/{now.year}"

        invoices = self.get_invoices()
        month_invoices = [
            inv for inv in invoices
            if inv['invoice_number'].endswith(month_suffix)
        ]

        seq_numbers = []
        for inv in month_invoices:
            try:
                seq = int(inv['invoice_number'].split('/')[0])
                seq_numbers.append(seq)
            except (ValueError, IndexError):
                pass

        next_seq = max(seq_numbers, default=0) + 1
        return f"{next_seq:02d}/{now.month:02d}/{now.year}"

    def create_invoice(
        self,
        client_id: int,
        description: str,
        amount: float,
        currency: str = "EUR",
        issue_date: Optional[str] = None,
        due_date: Optional[str] = None,
        work_dates: Optional[str] = None
    ) -> Dict:
        """Create new invoice in sheet"""
        try:
            file_number = self.get_next_file_number()
            invoice_number = self.get_next_invoice_number()

            # Default dates
            now = datetime.now()
            if not issue_date:
                issue_date = now.strftime("%d.%m.%Y")
            if not due_date:
                due_date = (now + timedelta(days=30)).strftime("%d.%m.%Y")

            # Get client
            client = self.get_client(client_id)
            client_name = client['name'] if client else ''

            # Prepare row data matching sheet columns:
            # File Name | File # | Invoice Number | Issue Date | Due Date | Client | Description | Amount | Currency | Status
            row_data = [
                f"Faktura {file_number}.pdf",  # File Name
                file_number,                    # File #
                invoice_number,                 # Invoice Number
                issue_date,                     # Issue Date
                due_date,                       # Due Date
                client_name,                    # Client
                description,                    # Description
                amount,                         # Amount
                currency,                       # Currency
                "draft"                         # Status
            ]

            # Append to sheet
            self.db_worksheet.append_row(row_data)
            logger.info(f"Created invoice {invoice_number} (File #{file_number})")

            return {
                "id": file_number,
                "file_number": file_number,
                "invoice_number": invoice_number,
                "client_id": client_id,
                "client": client,
                "description": description,
                "amount": amount,
                "currency": currency,
                "issue_date": issue_date,
                "due_date": due_date,
                "status": "draft",
                "work_dates": work_dates,
                "created_at": now.isoformat(),
                "sent_at": None,
                "paid_at": None,
                "pdf_path": None
            }

        except Exception as e:
            logger.error(f"Error creating invoice: {e}")
            raise

    def update_invoice_status(self, file_number: int, status: str) -> bool:
        """Update invoice status in sheet"""
        try:
            # Find the row
            all_data = self.db_worksheet.get_all_records()
            for idx, row in enumerate(all_data):
                if int(row.get('File #', 0)) == file_number:
                    # Row index is idx + 2 (1 for header, 1 for 0-index)
                    row_num = idx + 2
                    # Status is column J (10th column)
                    self.db_worksheet.update_cell(row_num, 10, status)
                    logger.info(f"Updated invoice {file_number} status to {status}")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error updating invoice status: {e}")
            return False

    def get_stats(self) -> Dict:
        """Get dashboard statistics"""
        invoices = self.get_invoices()

        total = len(invoices)
        draft = sum(1 for i in invoices if i['status'] == 'draft')
        sent = sum(1 for i in invoices if i['status'] == 'sent')
        paid = sum(1 for i in invoices if i['status'] == 'paid')
        total_amount = sum(i['amount'] for i in invoices)
        total_paid = sum(i['amount_paid'] for i in invoices)
        total_due = sum(i['amount_due'] for i in invoices)

        # By client - total invoiced
        by_client = {}
        # By client - outstanding due
        due_by_client = {}
        for inv in invoices:
            client_name = inv['client']['name'] if inv['client'] else 'Unknown'
            by_client[client_name] = by_client.get(client_name, 0) + inv['amount']
            due_by_client[client_name] = due_by_client.get(client_name, 0) + inv['amount_due']

        return {
            "total_invoices": total,
            "draft_count": draft,
            "sent_count": sent,
            "paid_count": paid,
            "total_amount": total_amount,
            "total_paid": total_paid,
            "total_due": total_due,
            "total_by_client": by_client,
            "due_by_client": due_by_client
        }

    # ============ PAYMENTS ============

    def _get_payments_by_invoice(self) -> Dict[int, List[Dict]]:
        """Get all payments grouped by invoice file number"""
        try:
            all_data = self.payments_worksheet.get_all_records()
            payments_by_invoice = {}

            for row in all_data:
                if not row.get('Payment ID'):
                    continue

                invoice_num = int(row.get('Invoice #', 0))
                if invoice_num not in payments_by_invoice:
                    payments_by_invoice[invoice_num] = []

                payment = {
                    "id": int(row.get('Payment ID', 0)),
                    "invoice_id": invoice_num,
                    "client": row.get('Client', ''),
                    "amount": float(row.get('Amount', 0)) if row.get('Amount') else 0,
                    "currency": row.get('Currency', 'EUR'),
                    "date": row.get('Date', ''),
                    "method": row.get('Method', ''),
                    "notes": row.get('Notes', ''),
                    "created_at": row.get('Created At', '')
                }
                payments_by_invoice[invoice_num].append(payment)

            return payments_by_invoice
        except Exception as e:
            logger.error(f"Error fetching payments by invoice: {e}")
            return {}

    def get_payments(
        self,
        client_id: Optional[int] = None,
        invoice_id: Optional[int] = None
    ) -> List[Dict]:
        """Get all payments with optional filters"""
        try:
            all_data = self.payments_worksheet.get_all_records()
            payments = []

            for row in all_data:
                if not row.get('Payment ID'):
                    continue

                payment = {
                    "id": int(row.get('Payment ID', 0)),
                    "invoice_id": int(row.get('Invoice #', 0)),
                    "client": row.get('Client', ''),
                    "amount": float(row.get('Amount', 0)) if row.get('Amount') else 0,
                    "currency": row.get('Currency', 'EUR'),
                    "date": row.get('Date', ''),
                    "method": row.get('Method', ''),
                    "notes": row.get('Notes', ''),
                    "created_at": row.get('Created At', '')
                }
                payments.append(payment)

            # Sort by date descending
            payments.sort(key=lambda x: x['id'], reverse=True)

            # Filter by invoice_id if provided
            if invoice_id:
                payments = [p for p in payments if p['invoice_id'] == invoice_id]

            # Filter by client_id if provided
            if client_id:
                client = self.get_client(client_id)
                if client:
                    client_name = client['name']
                    payments = [p for p in payments if p['client'] == client_name]

            return payments

        except Exception as e:
            logger.error(f"Error fetching payments: {e}")
            return []

    def get_payment(self, payment_id: int) -> Optional[Dict]:
        """Get single payment by ID"""
        payments = self.get_payments()
        for p in payments:
            if p['id'] == payment_id:
                return p
        return None

    def get_next_payment_id(self) -> int:
        """Get next available payment ID"""
        payments = self.get_payments()
        if not payments:
            return 1
        return max(p['id'] for p in payments) + 1

    def create_payment(
        self,
        invoice_id: int,
        amount: float,
        currency: str = "EUR",
        date: Optional[str] = None,
        method: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict:
        """Create new payment in sheet"""
        try:
            # Get invoice to get client name
            invoice = self.get_invoice(invoice_id)
            if not invoice:
                raise ValueError(f"Invoice {invoice_id} not found")

            # Validate payment amount
            if amount > invoice['amount_due']:
                raise ValueError(
                    f"Payment amount ({amount}) exceeds remaining due ({invoice['amount_due']})"
                )

            payment_id = self.get_next_payment_id()
            client_name = invoice['client']['name'] if invoice['client'] else ''

            # Default date to today
            now = datetime.now()
            if not date:
                date = now.strftime("%d.%m.%Y")

            # Prepare row data matching sheet columns:
            # Payment ID | Invoice # | Client | Amount | Currency | Date | Method | Notes | Created At
            row_data = [
                payment_id,
                invoice_id,
                client_name,
                amount,
                currency,
                date,
                method or "",
                notes or "",
                now.isoformat()
            ]

            # Append to sheet
            self.payments_worksheet.append_row(row_data)
            logger.info(f"Created payment {payment_id} for invoice {invoice_id}")

            return {
                "id": payment_id,
                "invoice_id": invoice_id,
                "client": client_name,
                "amount": amount,
                "currency": currency,
                "date": date,
                "method": method or "",
                "notes": notes or "",
                "created_at": now.isoformat()
            }

        except Exception as e:
            logger.error(f"Error creating payment: {e}")
            raise

    def delete_payment(self, payment_id: int) -> bool:
        """Delete payment from sheet"""
        try:
            all_data = self.payments_worksheet.get_all_records()
            for idx, row in enumerate(all_data):
                if int(row.get('Payment ID', 0)) == payment_id:
                    # Row index is idx + 2 (1 for header, 1 for 0-index)
                    row_num = idx + 2
                    self.payments_worksheet.delete_rows(row_num)
                    logger.info(f"Deleted payment {payment_id}")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error deleting payment: {e}")
            return False

    def get_client_summary(self, client_id: int) -> Optional[Dict]:
        """Get client summary with invoice and payment totals"""
        client = self.get_client(client_id)
        if not client:
            return None

        # Get all invoices for this client
        invoices = self.get_invoices(client_id=client_id)

        # Get all payments for this client
        payments = self.get_payments(client_id=client_id)

        total_invoiced = sum(i['amount'] for i in invoices)
        total_paid = sum(p['amount'] for p in payments)
        total_due = total_invoiced - total_paid

        return {
            "client": client,
            "total_invoiced": total_invoiced,
            "total_paid": total_paid,
            "total_due": total_due,
            "invoice_count": len(invoices),
            "payment_count": len(payments),
            "invoices": invoices,
            "payments": payments
        }

    def get_unpaid_invoices_for_client(self, client_id: int) -> List[Dict]:
        """Get unpaid or partially paid invoices for a client"""
        invoices = self.get_invoices(client_id=client_id)
        return [i for i in invoices if i['amount_due'] > 0]


# Singleton
_sheets_db: Optional[SheetsDatabaseService] = None


def get_sheets_db() -> SheetsDatabaseService:
    """Get sheets database singleton"""
    global _sheets_db
    if _sheets_db is None:
        _sheets_db = SheetsDatabaseService()
    return _sheets_db
