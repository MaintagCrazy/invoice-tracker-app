"""
KSeF endpoints — submit invoices to Poland's National e-Invoice System.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import config
from services.sheets_database import get_sheets_db
from services.ksef_service import submit_invoice_to_ksef, check_ksef_health

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ksef", tags=["ksef"])


class KsefSubmitRequest(BaseModel):
    """Filing to KSeF is a legally binding submission to the tax authority and
    cannot be withdrawn, so it requires an explicit confirmation — the same gate
    the customer-facing email send uses."""
    confirmed: bool = False


@router.get("/submit-preview/{invoice_id}")
def preview_ksef_submission(invoice_id: int):
    """What WOULD be filed — read-only, sends nothing to KSeF.

    Lets the confirmation dialog state exactly which invoice, whose NIP, and
    which environment before anything irreversible happens.
    """
    db = get_sheets_db()
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    client = invoice.get("client", {})
    if not client:
        raise HTTPException(status_code=400, detail="Invoice has no client data")

    already = invoice.get("ksef_reference") or ""
    return {
        "invoice_id": invoice_id,
        "invoice_number": invoice.get("invoice_number"),
        "client_name": client.get("name"),
        "client_nip": client.get("company_id"),
        "amount": invoice.get("amount"),
        "currency": invoice.get("currency", "EUR"),
        "issue_date": invoice.get("issue_date"),
        "seller_nip": config.COMPANY.get("nip"),
        "environment": config.KSEF_ENVIRONMENT,
        "already_submitted": bool(already),
        "existing_ksef_reference": already or None,
        "irreversible": True,
        "warning": (
            "Filing to KSeF is a legally binding submission to the Polish tax "
            "authority and cannot be withdrawn or deleted afterwards."
        ),
    }


@router.post("/submit/{invoice_id}")
def submit_to_ksef(invoice_id: int, body: Optional[KsefSubmitRequest] = None):
    """
    Submit an invoice to KSeF.
    Builds FA(3) XML from invoice data and sends to production KSeF.

    Requires {"confirmed": true} — this files with the tax authority and
    cannot be undone.
    """
    if body is None or not body.confirmed:
        raise HTTPException(
            status_code=400,
            detail=(
                "KSeF submission must be confirmed. This files the invoice with the "
                "Polish tax authority and cannot be withdrawn. Re-send with "
                '{"confirmed": true} once the details have been checked.'
            ),
        )

    db = get_sheets_db()
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    client = invoice.get("client", {})
    if not client:
        raise HTTPException(status_code=400, detail="Invoice has no client data")

    # Filing the same invoice twice creates a duplicate at the tax authority
    # that cannot be withdrawn — refuse rather than silently re-file.
    existing = invoice.get("ksef_reference")
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Invoice {invoice.get('invoice_number')} was already filed with KSeF "
                f"(reference {existing}). Filing again would create a duplicate."
            ),
        )

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
