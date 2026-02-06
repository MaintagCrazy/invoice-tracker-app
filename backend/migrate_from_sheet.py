#!/usr/bin/env python3
"""
Migration script to import existing invoices from Google Sheet

Run once after first deployment to import the 38 existing invoices.

Usage:
    python migrate_from_sheet.py

Requires:
    - GOOGLE_SERVICE_ACCOUNT_FILE environment variable
    - gspread and google-auth packages
"""

import os
import sys
from datetime import datetime

# Add parent path for credentials
sys.path.insert(0, '/Users/datnguyen/Marbily claude code/ecommerce-ceo-system')

try:
    import gspread
    from google.oauth2.service_account import Credentials
    from UNIVERSAL_CREDENTIALS import UniversalCredentials
except ImportError:
    print("Error: Required packages not installed.")
    print("Install with: pip install gspread google-auth")
    sys.exit(1)

from models.database import init_db, SessionLocal, Client, Invoice

# Sheet ID from the plan
SHEET_ID = "1xETHFJZO29qJj_UlyTqB29CRyOp7UFi49oEOvmfd084"
DATABASE_TAB = "Database"

# Client name mapping
CLIENT_MAPPING = {
    'Bauceram GmbH': 'Bauceram GmbH',
    'bauceram': 'Bauceram GmbH',
    'Clinker Bau Schweiz GmbH': 'Clinker Bau Schweiz GmbH',
    'clinker': 'Clinker Bau Schweiz GmbH',
    'Stuckgeschäft Laufenberg': 'Stuckgeschäft Laufenberg',
    'laufenberg': 'Stuckgeschäft Laufenberg',
}


def connect_to_sheet():
    """Connect to Google Sheets"""
    creds = UniversalCredentials()
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets.readonly',
        'https://www.googleapis.com/auth/drive.readonly'
    ]
    credentials = Credentials.from_service_account_file(
        creds.GOOGLE_SERVICE_ACCOUNT_FILE,
        scopes=scopes
    )
    gc = gspread.authorize(credentials)
    return gc.open_by_key(SHEET_ID)


def parse_date(date_str):
    """Parse date from DD.MM.YYYY format"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%d.%m.%Y").date()
    except ValueError:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None


def migrate():
    """Run the migration"""
    print("Starting migration from Google Sheet...")
    print(f"Sheet ID: {SHEET_ID}")

    # Initialize database
    init_db()
    db = SessionLocal()

    # Connect to sheet
    try:
        sheet = connect_to_sheet()
        worksheet = sheet.worksheet(DATABASE_TAB)
    except Exception as e:
        print(f"Error connecting to sheet: {e}")
        return

    # Get all data
    all_data = worksheet.get_all_records()
    print(f"Found {len(all_data)} rows in sheet")

    # Get existing clients
    clients = {c.name: c for c in db.query(Client).all()}
    print(f"Existing clients: {list(clients.keys())}")

    # Check for existing invoices
    existing_invoices = {i.file_number for i in db.query(Invoice).all()}
    print(f"Existing invoices: {len(existing_invoices)}")

    imported = 0
    skipped = 0
    errors = []

    for row in all_data:
        try:
            file_num = int(row.get('File #', 0))
            if file_num == 0:
                continue

            # Skip if already exists
            if file_num in existing_invoices:
                skipped += 1
                continue

            # Get client
            client_name = row.get('Client', '')
            normalized_name = CLIENT_MAPPING.get(client_name, client_name)
            client = clients.get(normalized_name)

            if not client:
                errors.append(f"Row {file_num}: Unknown client '{client_name}'")
                continue

            # Parse data
            invoice_number = row.get('Invoice Number', f'{file_num:02d}/01/2025')
            issue_date = parse_date(row.get('Issue Date', ''))
            due_date = parse_date(row.get('Due Date', ''))
            description = row.get('Description', '')
            amount = float(row.get('Amount', 0)) if row.get('Amount') else 0
            currency = row.get('Currency', 'EUR')

            # Default dates if not provided
            if not issue_date:
                issue_date = datetime.now().date()
            if not due_date:
                from datetime import timedelta
                due_date = issue_date + timedelta(days=30)

            # Create invoice
            invoice = Invoice(
                invoice_number=invoice_number,
                file_number=file_num,
                client_id=client.id,
                description=description,
                amount=amount,
                currency=currency,
                issue_date=issue_date,
                due_date=due_date,
                status='sent'  # Assume existing invoices were sent
            )
            db.add(invoice)
            imported += 1
            print(f"  Imported: Faktura {file_num} - {client_name} - {currency} {amount}")

        except Exception as e:
            errors.append(f"Row {row.get('File #', '?')}: {str(e)}")

    # Commit
    db.commit()
    db.close()

    print(f"\nMigration complete!")
    print(f"  Imported: {imported}")
    print(f"  Skipped (already exists): {skipped}")
    print(f"  Errors: {len(errors)}")

    if errors:
        print("\nErrors:")
        for error in errors:
            print(f"  - {error}")


if __name__ == "__main__":
    migrate()
