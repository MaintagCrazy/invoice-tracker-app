"""
KSeF endpoints — submit invoices to Poland's National e-Invoice System.
"""
import logging
from fastapi import APIRouter, HTTPException

from services.sheets_database import get_sheets_db
from services.ksef_service import submit_invoice_to_ksef, check_ksef_health

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ksef", tags=["ksef"])


@router.post("/submit/{invoice_id}")
def submit_to_ksef(invoice_id: int):
    """
    Submit an invoice to KSeF.
    Builds FA(3) XML from invoice data and sends to production KSeF.
    """
    db = get_sheets_db()
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    client = invoice.get("client", {})
    if not client:
        raise HTTPException(status_code=400, detail="Invoice has no client data")

    try:
        result = submit_invoice_to_ksef(invoice, client)

        # Store KSeF reference in invoice metadata
        try:
            updates = {}
            if result.get("ksef_number"):
                updates["ksef_reference"] = result["ksef_number"]
                updates["ksef_status"] = result.get("ksef_status", "submitted")
            if updates:
                db.update_invoice(invoice_id, updates)
        except Exception as e:
            logger.warning(f"Could not save KSeF reference to sheet: {e}")

        return {
            "success": True,
            "invoice_id": invoice_id,
            **result
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception(f"KSeF submission failed for invoice {invoice_id}")
        raise HTTPException(status_code=500, detail=f"KSeF submission failed: {e}")


@router.get("/status/{invoice_id}")
def get_ksef_status(invoice_id: int):
    """
    Get KSeF submission status for an invoice.
    """
    db = get_sheets_db()
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return {
        "invoice_id": invoice_id,
        "invoice_number": invoice.get("invoice_number"),
        "ksef_reference": invoice.get("ksef_reference"),
        "ksef_status": invoice.get("ksef_status", "not_submitted"),
    }


@router.get("/health")
def ksef_health():
    """
    Check KSeF API connectivity and token validity.
    """
    return check_ksef_health()
