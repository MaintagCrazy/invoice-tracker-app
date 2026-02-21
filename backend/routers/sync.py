"""Sync endpoints - regenerate PDFs and upload to Google Drive"""
import logging
import traceback
from fastapi import APIRouter, HTTPException

from services.sheets_database import get_sheets_db
from services.pdf_service import get_pdf_service, WEASYPRINT_AVAILABLE
from services.drive_storage import get_drive_service, drive_filename

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/drive-status")
def drive_status():
    """Show Drive connection status, folder info, and invoice coverage"""
    db = get_sheets_db()
    invoices = db.get_invoices()

    with_drive = [i for i in invoices if i.get('drive_file_id')]
    without_drive = [i for i in invoices if not i.get('drive_file_id')]

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


@router.get("/drive-files")
def list_drive_files():
    """List all files in the Drive folder with their IDs and names"""
    drive = get_drive_service()
    if not drive.is_connected:
        raise HTTPException(status_code=503, detail="Drive not connected")

    db = get_sheets_db()
    invoices = db.get_invoices()
    linked_file_ids = {i.get('drive_file_id') for i in invoices if i.get('drive_file_id')}

    files = drive.list_files()
    result = []
    for f in files:
        result.append({
            "id": f["id"],
            "name": f["name"],
            "linked_to_invoice": f["id"] in linked_file_ids
        })

    linked = [f for f in result if f["linked_to_invoice"]]
    orphans = [f for f in result if not f["linked_to_invoice"]]

    return {
        "total_files": len(result),
        "linked_to_invoices": len(linked),
        "orphans": len(orphans),
        "orphan_files": orphans,
        "linked_files": linked
    }


@router.delete("/drive-orphans")
def delete_drive_orphans():
    """Delete files in Drive folder that are NOT linked to any invoice"""
    drive = get_drive_service()
    if not drive.is_connected:
        raise HTTPException(status_code=503, detail="Drive not connected")

    db = get_sheets_db()
    invoices = db.get_invoices()
    linked_file_ids = {i.get('drive_file_id') for i in invoices if i.get('drive_file_id')}

    files = drive.list_files()
    deleted = []
    errors = []

    for f in files:
        if f["id"] not in linked_file_ids:
            try:
                drive.delete_file(f["id"])
                deleted.append({"id": f["id"], "name": f["name"]})
                logger.info(f"Deleted orphan Drive file: {f['name']} ({f['id']})")
            except Exception as e:
                errors.append({"id": f["id"], "name": f["name"], "error": str(e)})

    return {
        "deleted_count": len(deleted),
        "error_count": len(errors),
        "deleted": deleted,
        "errors": errors
    }


@router.post("/drive-reset")
def drive_reset():
    """Delete ALL Drive files, clear all drive_file_ids, then re-upload everything with correct naming."""
    if not WEASYPRINT_AVAILABLE:
        raise HTTPException(status_code=503, detail="WeasyPrint not available")

    drive = get_drive_service()
    if not drive.is_connected:
        raise HTTPException(status_code=503, detail="Drive not connected")

    db = get_sheets_db()
    pdf_service = get_pdf_service()

    # Step 1: Delete ALL files in the Drive folder
    files = drive.list_files()
    deleted_count = 0
    for f in files:
        try:
            drive.delete_file(f["id"])
            deleted_count += 1
        except Exception as e:
            logger.error(f"Failed to delete {f['name']}: {e}")

    # Step 2: Clear all drive_file_ids and re-upload
    invoices = db.get_invoices()
    uploaded = []
    errors = []

    for invoice in invoices:
        try:
            # Clear existing drive_file_id
            if invoice.get('drive_file_id'):
                db.update_invoice_drive_file_id(invoice['file_number'], '')

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
            filename = drive_filename(invoice['file_number'])
            file_id = drive.upload_pdf(pdf_bytes, filename)
            db.update_invoice_drive_file_id(invoice['file_number'], file_id)

            uploaded.append({
                "file_number": invoice['file_number'],
                "filename": filename,
                "drive_file_id": file_id
            })
        except Exception as e:
            errors.append({
                "file_number": invoice['file_number'],
                "error": str(e)
            })
            logger.error(f"Failed to re-upload invoice {invoice['file_number']}: {e}")

    return {
        "old_files_deleted": deleted_count,
        "invoices_uploaded": len(uploaded),
        "errors": len(errors),
        "uploaded": uploaded,
        "error_details": errors
    }


@router.get("/pdf-test")
def pdf_test():
    """Test PDF generation and return diagnostic info"""
    result = {"weasyprint_available": WEASYPRINT_AVAILABLE}

    if not WEASYPRINT_AVAILABLE:
        result["error"] = "WeasyPrint not importable"
        return result

    try:
        pdf_service = get_pdf_service()
        test_invoice = {
            "invoice_number": "TEST/01/2026",
            "description": "Test invoice",
            "amount": 100.0,
            "currency": "EUR",
            "issue_date": "01.01.2026",
            "due_date": "31.01.2026"
        }
        test_client = {
            "name": "Test Client",
            "address": "Test Address",
            "company_id": "TEST123"
        }
        pdf_bytes = pdf_service.generate_pdf_bytes(test_invoice, test_client)
        result["pdf_generated"] = True
        result["pdf_size"] = len(pdf_bytes)
        result["starts_with_pdf"] = pdf_bytes[:5] == b"%PDF-"
    except Exception as e:
        result["pdf_generated"] = False
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()

    return result


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
            detail="Google Drive not connected -- check DRIVE_TOKEN_B64 env var"
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
            filename = drive_filename(invoice['file_number'])

            file_id = drive.upload_pdf(pdf_bytes, filename)
            db.update_invoice_drive_file_id(invoice['file_number'], file_id)

            results["regenerated"].append({
                "file_number": invoice['file_number'],
                "drive_filename": filename,
                "drive_file_id": file_id,
                "drive_link": drive.get_file_link(file_id)
            })
            logger.info(f"Regenerated and uploaded {filename}")

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
