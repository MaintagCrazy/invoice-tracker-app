"""
Google Sheets as Database Service
Direct read/write to Google Sheets - single source of truth.
Includes in-memory caching to avoid Google API rate limits (60 reads/min).
"""
import os
import re
import json
import base64
import logging
import time
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
ZUS_TAB = "ZUS"

# "YYYY-MM" — the key format used for a ZUS month everywhere (sheet, API, UI)
MONTH_KEY_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


def month_key(year: int, month: int) -> str:
    """Build the canonical 'YYYY-MM' month key"""
    return f"{year:04d}-{month:02d}"


def month_label(key: str) -> str:
    """Human label for a 'YYYY-MM' key, e.g. '2026-08' -> 'August 2026'"""
    try:
        year, month = key.split("-")
        return f"{MONTH_NAMES[int(month) - 1]} {year}"
    except (ValueError, IndexError):
        return key


def issue_date_month(date_str: Any) -> Optional[str]:
    """Extract the 'YYYY-MM' month from an invoice issue date.

    Handles the two formats present in the sheet ('DD.MM.YYYY' as written by
    this app, 'YYYY-MM-DD' as a defensive fallback). Returns None when the
    value cannot be parsed — some migrated rows literally contain 'NOT FOUND',
    and a row we cannot date is simply not counted anywhere.
    """
    value = str(date_str or "").strip()
    if not value:
        return None
    match = re.match(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})$", value)
    if match:
        day, month, year = (int(g) for g in match.groups())
    else:
        match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", value)
        if not match:
            return None
        year, month, day = (int(g) for g in match.groups())
    if not 1 <= month <= 12:
        return None
    return month_key(year, month)

# Seed clients — written to Clients sheet on first run, then sheet is source of truth
SEED_CLIENTS = [
    {"name": "Bauceram GmbH", "address": "Am Tonscuppen.2, 53347 Alfter", "company_id": "DE306313681", "email": "info@bauceram.de", "contact_person": "", "phone": ""},
    {"name": "Clinker Bau Schweiz GmbH", "address": "Hinterbergstrasse 26, 6312 Steinhausen", "company_id": "CHE-271.aborak.764", "email": "info@clinkerbau.ch", "contact_person": "", "phone": ""},
    {"name": "Stuckgeschäft Laufenberg", "address": "Servatiusweg 33, 53332 Bornheim", "company_id": "", "email": "", "contact_person": "", "phone": ""},
    {"name": "Schneider & Bitzer GmbH", "address": "", "company_id": "", "email": "", "contact_person": "", "phone": ""},
    {"name": "Hillenbrand Bauunternehmen GmbH", "address": "", "company_id": "", "email": "", "contact_person": "", "phone": ""},
    {"name": "BUDMAT", "address": "", "company_id": "", "email": "", "contact_person": "", "phone": ""},
]


CACHE_TTL = 30  # seconds — how long cached sheet data is considered fresh


class SheetsDatabaseService:
    """Google Sheets as database with in-memory caching"""

    def __init__(self):
        self.gc = None
        self.sheet = None
        self.db_worksheet = None
        self._cache: Dict[str, Any] = {}       # key -> data
        self._cache_ts: Dict[str, float] = {}   # key -> timestamp
        self._connect()

    def _cache_get(self, key: str):
        """Return cached value if fresh, else None"""
        ts = self._cache_ts.get(key, 0)
        if time.time() - ts < CACHE_TTL and key in self._cache:
            return self._cache[key]
        return None

    def _cache_set(self, key: str, value):
        """Store value in cache"""
        self._cache[key] = value
        self._cache_ts[key] = time.time()

    def _cache_invalidate(self, *keys):
        """Invalidate specific cache keys (or all if no keys given)"""
        if not keys:
            self._cache.clear()
            self._cache_ts.clear()
        else:
            for k in keys:
                self._cache.pop(k, None)
                self._cache_ts.pop(k, None)

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
            self._init_clients_worksheet()
            self._init_zus_worksheet()
            self._ensure_deleted_at_column()
            logger.info(f"Connected to Google Sheet: {SHEET_ID}")

        except Exception as e:
            logger.error(f"Failed to connect to Google Sheets: {e}")
            raise

    def _ensure_deleted_at_column(self):
        """Ensure the Database sheet has a 'Deleted At' header in column L (12)"""
        try:
            headers = self.db_worksheet.row_values(1)
            if len(headers) < 12 or headers[11] != "Deleted At":
                self.db_worksheet.update_cell(1, 12, "Deleted At")
                logger.info("Added 'Deleted At' column header to Database sheet")
        except Exception as e:
            logger.warning(f"Could not ensure 'Deleted At' column: {e}")

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

    def _init_zus_worksheet(self):
        """Initialize ZUS worksheet (create if not exists).

        Purely additive: it only ever adds a new tab, and never reads from or
        writes to the Database / Clients / Payments tabs.
        """
        try:
            self.zus_worksheet = self.sheet.worksheet(ZUS_TAB)
        except gspread.exceptions.WorksheetNotFound:
            self.zus_worksheet = self.sheet.add_worksheet(
                title=ZUS_TAB, rows=200, cols=6
            )
            headers = ["Month", "Paid", "Paid At", "Base Rate PLN", "Updated At"]
            self.zus_worksheet.append_row(headers)
            logger.info("Created ZUS worksheet")

    def _init_clients_worksheet(self):
        """Initialize Clients worksheet (create if not exists, seed if empty)"""
        try:
            self.clients_worksheet = self.sheet.worksheet(CLIENTS_TAB)
        except gspread.exceptions.WorksheetNotFound:
            self.clients_worksheet = self.sheet.add_worksheet(
                title=CLIENTS_TAB, rows=200, cols=8
            )
            headers = ["ID", "Name", "Address", "Company ID", "Email", "Contact Person", "Phone", "Created At"]
            self.clients_worksheet.append_row(headers)
            logger.info("Created Clients worksheet")

        # Seed if empty (only header row)
        all_data = self.clients_worksheet.get_all_records()
        if not all_data:
            now = datetime.now().isoformat()
            for idx, c in enumerate(SEED_CLIENTS, start=1):
                row = [idx, c["name"], c["address"], c["company_id"], c["email"], c["contact_person"], c["phone"], now]
                self.clients_worksheet.append_row(row)
            logger.info(f"Seeded {len(SEED_CLIENTS)} default clients")

    # ============ CLIENTS (Sheet-based) ============

    def get_clients(self) -> List[Dict]:
        """Get all clients from Clients sheet (cached)"""
        cached = self._cache_get("clients")
        if cached is not None:
            return cached
        try:
            all_data = self.clients_worksheet.get_all_records()
            clients = []
            for row in all_data:
                if not row.get("ID"):
                    continue
                clients.append({
                    "id": int(row["ID"]),
                    "name": row.get("Name", ""),
                    "address": row.get("Address", ""),
                    "company_id": row.get("Company ID", ""),
                    "email": row.get("Email", "") or None,
                    "contact_person": row.get("Contact Person", ""),
                    "phone": row.get("Phone", ""),
                })
            self._cache_set("clients", clients)
            return clients
        except Exception as e:
            logger.error(f"Error fetching clients: {e}")
            return []

    def get_client(self, client_id: int) -> Optional[Dict]:
        """Get client by ID"""
        clients = self.get_clients()
        for c in clients:
            if c["id"] == client_id:
                return c
        return None

    def get_client_by_name(self, name: str) -> Optional[Dict]:
        """Get client by name (fuzzy match)"""
        name_lower = name.lower().strip()
        if not name_lower:
            return None
        clients = self.get_clients()

        # Exact match first
        for client in clients:
            if client["name"].lower() == name_lower:
                return client

        # Partial match
        for client in clients:
            if name_lower in client["name"].lower() or client["name"].lower() in name_lower:
                return client

        # Single-word shorthand match (e.g., "bauceram" -> "Bauceram GmbH")
        for client in clients:
            first_word = client["name"].split()[0].lower() if client["name"] else ""
            if name_lower == first_word:
                return client

        return None

    def create_client(
        self,
        name: str,
        address: str = "",
        company_id: str = "",
        email: str = "",
        contact_person: str = "",
        phone: str = ""
    ) -> Dict:
        """Add a new client to the Clients sheet"""
        # Check for duplicates
        existing = self.get_client_by_name(name)
        if existing:
            raise ValueError(f"Client '{existing['name']}' already exists (ID: {existing['id']})")

        # Get next ID
        clients = self.get_clients()
        next_id = max((c["id"] for c in clients), default=0) + 1

        now = datetime.now().isoformat()
        row_data = [next_id, name, address, company_id, email, contact_person, phone, now]
        self.clients_worksheet.append_row(row_data)
        self._cache_invalidate("clients")

        logger.info(f"Created client '{name}' (ID: {next_id})")

        return {
            "id": next_id,
            "name": name,
            "address": address,
            "company_id": company_id,
            "email": email or None,
            "contact_person": contact_person,
            "phone": phone,
        }

    # ============ INVOICES ============

    def _load_all_invoices(self) -> List[Dict]:
        """Load all invoices from sheet (cached). Returns unfiltered, sorted list."""
        cached = self._cache_get("invoices")
        if cached is not None:
            return cached
        try:
            all_data = self.db_worksheet.get_all_records()
            payments_by_invoice = self._get_payments_by_invoice()
            invoices = []

            for row in all_data:
                if not row.get('File #'):
                    continue

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

                invoice_payments = payments_by_invoice.get(file_number, [])
                amount_paid = sum(p['amount'] for p in invoice_payments)
                amount_due = max(0, amount - amount_paid)

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
                    "status": row.get('Status', 'sent'),
                    "work_dates": row.get('Work Dates', ''),
                    "created_at": row.get('Created At', ''),
                    "sent_at": None,
                    "paid_at": None,
                    "pdf_path": None,
                    "drive_file_id": row.get('Drive File ID', ''),
                    "deleted_at": row.get('Deleted At', ''),
                    # KSeF filing is irreversible, so its reference is the only
                    # proof the invoice was filed — and what stops it being filed twice.
                    "ksef_reference": row.get('KSeF Reference', ''),
                    "ksef_status": row.get('KSeF Status', '')
                }
                invoices.append(invoice)

            invoices.sort(key=lambda x: x['file_number'], reverse=True)
            self._cache_set("invoices", invoices)
            return invoices

        except Exception as e:
            logger.error(f"Error fetching invoices: {e}")
            return []

    def get_invoices(self, status: Optional[str] = None, client_id: Optional[int] = None, include_deleted: bool = False) -> List[Dict]:
        """Get invoices with optional filters (uses cached data). Excludes deleted invoices by default."""
        invoices = self._load_all_invoices()
        if not include_deleted:
            invoices = [i for i in invoices if i['status'] != 'deleted']
        if status:
            invoices = [i for i in invoices if i['status'] == status]
        if client_id:
            invoices = [i for i in invoices if i['client_id'] == client_id]
        return invoices

    def get_deleted_invoices(self) -> List[Dict]:
        """Get all soft-deleted invoices (for the trash/deleted view)"""
        all_invoices = self._load_all_invoices()
        return [i for i in all_invoices if i['status'] == 'deleted']

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
        """Generate invoice number: XX/MM/YYYY
        Cross-checks with Allegro invoice system to avoid number overlaps
        (both systems share NIP 7011092699).
        """
        now = datetime.now()
        month_suffix = f"/{now.month:02d}/{now.year}"

        # Read Invoice Number column directly (column C = index 3)
        # This avoids get_invoices() which can skip rows with missing File #
        try:
            all_values = self.db_worksheet.col_values(3)  # Column C = Invoice Number
        except Exception as e:
            logger.error(f"Error reading invoice numbers: {e}")
            all_values = []

        seq_numbers = []
        for val in all_values[1:]:  # Skip header row
            val = str(val).strip()
            if val.endswith(month_suffix):
                try:
                    seq = int(val.split('/')[0])
                    seq_numbers.append(seq)
                except (ValueError, IndexError):
                    pass

        next_seq = max(seq_numbers, default=0) + 1

        # Cross-system check: Allegro Glamova invoices share NIP 7011092699
        try:
            import httpx
            resp = httpx.get(
                'https://marbily-backend-production.up.railway.app/allegro/invoices/max-sequence',
                params={'month': now.month, 'year': now.year, 'nip': '7011092699'},
                timeout=5
            )
            if resp.status_code == 200:
                allegro_max = resp.json().get('max_sequence', 0)
                if allegro_max >= next_seq:
                    next_seq = allegro_max + 1
                    logger.info(f"Cross-system sequence: Allegro max={allegro_max}, using seq={next_seq}")
        except Exception as e:
            logger.warning(f"Cross-system invoice sequence check failed (proceeding with local): {e}")

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

            # Get client — refuse to create invoice without a valid client
            client = self.get_client(client_id)
            if not client:
                raise ValueError(f"Client with ID {client_id} not found. Cannot create invoice without a client.")
            client_name = client['name']

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
            self._cache_invalidate("invoices")
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

    # Only these fields have a column behind them. Anything else passed to
    # update_invoice used to be accepted and silently dropped — that is how a
    # KSeF reference could be lost right after an irreversible filing.
    _UPDATABLE_COLUMNS = {
        "description": 7,       # G
        "amount": 8,            # H
        "status": 10,           # J
        "ksef_reference": 13,   # M
        "ksef_status": 14,      # N
    }

    def update_invoice(self, file_number: int, updates: Dict[str, Any]) -> bool:
        """Update invoice fields. Accepts: description, amount, status,
        ksef_reference, ksef_status.

        Raises ValueError for any field with no column, rather than reporting
        success for a write that never happened.
        """
        unknown = set(updates) - set(self._UPDATABLE_COLUMNS)
        if unknown:
            raise ValueError(
                f"update_invoice cannot persist {sorted(unknown)} — no column for it. "
                f"Persistable fields: {sorted(self._UPDATABLE_COLUMNS)}."
            )
        try:
            all_data = self.db_worksheet.get_all_records()
            for idx, row in enumerate(all_data):
                if int(row.get('File #', 0)) == file_number:
                    row_num = idx + 2  # 1 for header, 1 for 0-index
                    for field, col in self._UPDATABLE_COLUMNS.items():
                        if field not in updates:
                            continue
                        value = updates[field]
                        if field == "amount":
                            value = float(value)
                        self.db_worksheet.update_cell(row_num, col, value)
                    logger.info(f"Updated invoice {file_number}: {list(updates.keys())}")
                    self._cache_invalidate("invoices")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error updating invoice {file_number}: {e}")
            return False

    def delete_invoice(self, file_number: int) -> bool:
        """Soft-delete an invoice: set status to 'deleted' and record deletion date.
        Invoice remains in the sheet for 30 days and can be restored."""
        try:
            all_data = self.db_worksheet.get_all_records()
            for idx, row in enumerate(all_data):
                if int(row.get('File #', 0)) == file_number:
                    row_num = idx + 2
                    # Set status to "deleted" (column J = 10)
                    self.db_worksheet.update_cell(row_num, 10, "deleted")
                    # Set Deleted At date (column L = 12)
                    self.db_worksheet.update_cell(row_num, 12, datetime.now().isoformat())
                    self._cache_invalidate("invoices")
                    logger.info(f"Soft-deleted invoice {file_number}")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error soft-deleting invoice {file_number}: {e}")
            return False

    def restore_invoice(self, file_number: int) -> str:
        """Restore a soft-deleted invoice. Returns 'restored', 'not_deleted', or 'not_found'."""
        try:
            all_data = self.db_worksheet.get_all_records()
            for idx, row in enumerate(all_data):
                if int(row.get('File #', 0)) == file_number:
                    if row.get('Status') != 'deleted':
                        logger.warning(f"Invoice {file_number} is not deleted, cannot restore")
                        return "not_deleted"
                    row_num = idx + 2
                    # Set status back to "draft" (column J = 10)
                    self.db_worksheet.update_cell(row_num, 10, "draft")
                    # Clear Deleted At (column L = 12)
                    self.db_worksheet.update_cell(row_num, 12, "")
                    self._cache_invalidate("invoices")
                    logger.info(f"Restored invoice {file_number}")
                    return "restored"
            return "not_found"
        except Exception as e:
            logger.error(f"Error restoring invoice {file_number}: {e}")
            return "not_found"

    def purge_old_deleted_invoices(self, days: int = 30) -> int:
        """Permanently delete invoices that have been soft-deleted for more than `days` days"""
        try:
            all_data = self.db_worksheet.get_all_records()
            cutoff = datetime.now() - timedelta(days=days)
            rows_to_delete = []

            for idx, row in enumerate(all_data):
                if row.get('Status') == 'deleted' and row.get('Deleted At'):
                    try:
                        deleted_at = datetime.fromisoformat(row['Deleted At'])
                        if deleted_at < cutoff:
                            rows_to_delete.append(idx + 2)
                    except (ValueError, TypeError):
                        pass

            # Delete in reverse order to maintain row indices
            for row_num in sorted(rows_to_delete, reverse=True):
                self.db_worksheet.delete_rows(row_num)

            if rows_to_delete:
                self._cache_invalidate("invoices")
                logger.info(f"Purged {len(rows_to_delete)} deleted invoices older than {days} days")

            return len(rows_to_delete)
        except Exception as e:
            logger.error(f"Error purging deleted invoices: {e}")
            return 0

    def delete_client(self, client_id: int) -> bool:
        """Delete a client row from the Clients sheet"""
        try:
            all_data = self.clients_worksheet.get_all_records()
            for idx, row in enumerate(all_data):
                if int(row.get('ID', 0)) == client_id:
                    row_num = idx + 2
                    self.clients_worksheet.delete_rows(row_num)
                    self._cache_invalidate("clients")
                    logger.info(f"Deleted client {client_id}")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error deleting client {client_id}: {e}")
            return False

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
                    self._cache_invalidate("invoices")
                    logger.info(f"Updated invoice {file_number} status to {status}")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error updating invoice status: {e}")
            return False

    def update_invoice_drive_file_id(self, file_number: int, drive_file_id: str) -> bool:
        """Write Drive File ID to column K for a given invoice"""
        try:
            all_data = self.db_worksheet.get_all_records()
            for idx, row in enumerate(all_data):
                if int(row.get('File #', 0)) == file_number:
                    row_num = idx + 2  # 1 for header, 1 for 0-index
                    # Drive File ID is column K (11th column)
                    self.db_worksheet.update_cell(row_num, 11, drive_file_id)
                    self._cache_invalidate("invoices")
                    logger.info(f"Updated invoice {file_number} Drive File ID: {drive_file_id}")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error updating Drive File ID for invoice {file_number}: {e}")
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
        """Get all payments grouped by invoice file number (cached)"""
        cached = self._cache_get("payments_by_invoice")
        if cached is not None:
            return cached
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

            self._cache_set("payments_by_invoice", payments_by_invoice)
            return payments_by_invoice
        except Exception as e:
            logger.error(f"Error fetching payments by invoice: {e}")
            return {}

    def get_payments(
        self,
        client_id: Optional[int] = None,
        invoice_id: Optional[int] = None
    ) -> List[Dict]:
        """Get all payments with optional filters (uses cached data)"""
        try:
            payments_by_inv = self._get_payments_by_invoice()
            payments = []
            for inv_payments in payments_by_inv.values():
                payments.extend(inv_payments)

            # Sort by ID descending
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
            self._cache_invalidate("payments_by_invoice", "invoices")
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
                    self._cache_invalidate("payments_by_invoice", "invoices")
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

    # ============ ZUS (monthly social-security contribution) ============

    def _load_zus_records(self) -> Dict[str, Dict]:
        """Load ticked ZUS months from the ZUS sheet (cached), keyed by 'YYYY-MM'.

        The sheet only stores months the user has touched; the month list itself
        is generated from the calendar, so this is one small read per cache TTL.
        """
        cached = self._cache_get("zus")
        if cached is not None:
            return cached
        try:
            all_data = self.zus_worksheet.get_all_records()
            records: Dict[str, Dict] = {}

            for row in all_data:
                month = str(row.get('Month', '')).strip()
                if not MONTH_KEY_RE.match(month):
                    continue

                base_rate = None
                raw_rate = row.get('Base Rate PLN')
                if raw_rate not in (None, ""):
                    try:
                        base_rate = float(raw_rate)
                    except (TypeError, ValueError):
                        base_rate = None

                records[month] = {
                    "month": month,
                    "paid": str(row.get('Paid', '')).strip().upper() in ("TRUE", "YES", "1"),
                    "paid_at": str(row.get('Paid At', '') or ''),
                    "base_rate": base_rate,
                }

            self._cache_set("zus", records)
            return records
        except Exception as e:
            logger.error(f"Error fetching ZUS records: {e}")
            return {}

    def _invoices_by_month(self) -> Dict[str, List[str]]:
        """Group invoice numbers by the month they were issued in.

        Reads the already-cached invoice list — no extra API calls, no per-row
        lookups. Invoices with an unparseable issue date are left out entirely.
        """
        by_month: Dict[str, List[str]] = {}
        for inv in self.get_invoices():
            key = issue_date_month(inv.get('issue_date'))
            if not key:
                continue
            by_month.setdefault(key, []).append(inv.get('invoice_number', ''))
        return by_month

    def get_zus_payments(self, months: Optional[int] = None) -> Dict[str, Any]:
        """Month-by-month ZUS list, newest first.

        Every month carries the FIXED base rate from config. Months in which
        invoices were issued are flagged `likely_higher` — the real contribution
        is usually above the base rate then, but we have no formula for it, so
        the flag never comes with an estimated amount. The only figures reported
        are the config base rate and the real invoice count read from the sheet.
        """
        window = months or config.ZUS_DEFAULT_MONTHS
        records = self._load_zus_records()
        invoices_by_month = self._invoices_by_month()

        # Last `window` calendar months, ending with the current one
        now = datetime.now()
        wanted = set()
        year, month = now.year, now.month
        for _ in range(window):
            wanted.add(month_key(year, month))
            month -= 1
            if month == 0:
                month = 12
                year -= 1

        # Anything already ticked stays visible even if it falls outside the window
        wanted.update(records.keys())

        rows = []
        for key in sorted(wanted, reverse=True):
            record = records.get(key, {})
            paid = bool(record.get("paid"))
            # A paid month keeps the rate that was in force when it was ticked;
            # everything else shows the current configured base rate.
            base_amount = record.get("base_rate") if (paid and record.get("base_rate")) else config.ZUS_BASE_AMOUNT_PLN
            invoice_numbers = invoices_by_month.get(key, [])

            rows.append({
                "month": key,
                "label": month_label(key),
                "base_amount": base_amount,
                "currency": config.ZUS_CURRENCY,
                "paid": paid,
                "paid_at": record.get("paid_at") or None,
                "invoice_count": len(invoice_numbers),
                "invoice_numbers": invoice_numbers,
                "likely_higher": len(invoice_numbers) > 0,
            })

        return {
            "base_amount": config.ZUS_BASE_AMOUNT_PLN,
            "currency": config.ZUS_CURRENCY,
            "months_requested": window,
            "paid_count": sum(1 for r in rows if r["paid"]),
            "unpaid_count": sum(1 for r in rows if not r["paid"]),
            "months": rows,
        }

    def set_zus_paid(self, month: str, paid: bool) -> Optional[Dict]:
        """Tick / un-tick a ZUS month. Upserts one row in the ZUS sheet.

        Writes with RAW input so Sheets stores '2026-08' as text instead of
        coercing it into a date.
        """
        try:
            now = datetime.now()
            paid_at = now.isoformat() if paid else ""
            # Records the rate that was in force at the moment of ticking, so a
            # future change to the base rate doesn't rewrite past months.
            base_rate = config.ZUS_BASE_AMOUNT_PLN if paid else ""
            row_values = [
                month,
                "TRUE" if paid else "FALSE",
                paid_at,
                base_rate,
                now.isoformat(),
            ]

            all_data = self.zus_worksheet.get_all_records()
            row_num = None
            for idx, row in enumerate(all_data):
                if str(row.get('Month', '')).strip() == month:
                    row_num = idx + 2  # 1 for header, 1 for 0-index
                    break

            if row_num:
                self.zus_worksheet.update([row_values], f"A{row_num}:E{row_num}")
            else:
                self.zus_worksheet.append_row(row_values)

            self._cache_invalidate("zus")
            logger.info(f"ZUS {month} marked {'paid' if paid else 'unpaid'}")

            return {
                "month": month,
                "label": month_label(month),
                "paid": paid,
                "paid_at": paid_at or None,
                "base_amount": config.ZUS_BASE_AMOUNT_PLN,
                "currency": config.ZUS_CURRENCY,
            }
        except Exception as e:
            logger.error(f"Error updating ZUS month {month}: {e}")
            return None


# Singleton
_sheets_db: Optional[SheetsDatabaseService] = None


def get_sheets_db() -> SheetsDatabaseService:
    """Get sheets database singleton"""
    global _sheets_db
    if _sheets_db is None:
        _sheets_db = SheetsDatabaseService()
    return _sheets_db
