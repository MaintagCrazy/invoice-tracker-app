"""
Sync endpoints - regenerate PDFs and upload to Google Drive
"""
import logging
from fastapi import APIRouter, HTTPException

from services.sheets_database import get_sheets_db
from services.pdf_service import get_pdf_service, WEASYPRINT_AVAILABLE
from services.drive_storage import get_drive_service, sanitize_filename

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/drive-status")
def drive_status():
    """Show Drive connection status, folder info, and invoice coverage"""
    db = get_sheets_db()
    invoices = db.get_invoices()

    with_drive = [i for i in invoices if i.get('drive_file_id')]
    without_drive = [i for i in invoices if not i.get('drive_file_id')]

    # Try to connect to Drive
    drive_connected = False
    folder_id = None
    folder_link = None
    drive_file_count = 0
    try:
        drive = get_drive_service()
        drive_connected = drive.is_connected
        folder_id = drive.folder_id
        folder_link = drive.get_folder_link()
        if drive_connected:
            drive_file_count = drive.get_file_count()
    except Exception as e:
        logger.error(f"Drive connection check failed: {e}")

    return {
        "drive_connected": drive_connected,
        "folder_id": folder_id,
        "folder_link": folder_link,
        "drive_file_count": drive_file_count,
        "total_invoices": len(invoices),
        "invoices_with_drive_id": len(with_drive),
        "invoices_without_drive_id": len(without_drive),
        "missing_file_numbers": [i['file_number'] for i in without_drive],
        "weasyprint_available": WEASYPRINT_AVAILABLE
    }


@router.post("/regenerate-all-pdfs")
def regenerate_all_pdfs():
    """Regenerate PDFs from Sheet data and upload to Drive (for invoices missing Drive ID)"""
    if not WEASYPRINT_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="WeasyPrint not available -- cannot generate PDFs on this server"
        )

    db = get_sheets_db()
    drive = get_drive_service()

    if not drive.is_connected:
        raise HTTPException(
            status_code=503,
            detail="Google Drive not connected -- check GMAIL_TOKEN_B64 env var"
        )

    pdf_service = get_pdf_service()
    invoices = db.get_invoices()

    results = {
        "regenerated": [],
        "skipped_already_has_drive_id": [],
        "errors": []
    }

    for invoice in invoices:
        if invoice.get('drive_file_id'):
            results["skipped_already_has_drive_id"].append(invoice['file_number'])
            continue

        try:
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

            pdf_bytes = pdf_service.generate_pdf_bytes(invoice_data, client_data)
            filename = sanitize_filename(invoice['invoice_number'], client.get('name', ''))

            file_id = drive.upload_pdf(pdf_bytes, filename)
            db.update_invoice_drive_file_id(invoice['file_number'], file_id)

            results["regenerated"].append({
                "file_number": invoice['file_number'],
                "invoice_number": invoice['invoice_number'],
                "drive_filename": filename,
                "drive_file_id": file_id,
                "drive_link": drive.get_file_link(file_id)
            })
            logger.info(f"Regenerated and uploaded invoice {invoice['invoice_number']}")

        except Exception as e:
            results["errors"].append({
                "file_number": invoice['file_number'],
                "error": str(e)
            })
            logger.error(f"Failed to regenerate invoice {invoice['file_number']}: {e}")

    return {
        "summary": {
            "total_invoices": len(invoices),
            "regenerated": len(results["regenerated"]),
            "skipped_already_stored": len(results["skipped_already_has_drive_id"]),
            "errors": len(results["errors"])
        },
        "details": results
    }
