"""
ZUS endpoints - monthly social-security contribution tracking.
Using Google Sheets as database (ZUS tab).
"""
import re
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from services.sheets_database import get_sheets_db

router = APIRouter(prefix="/api/zus", tags=["zus"])

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_month(month: str):
    """Reject anything that isn't a real, already-due 'YYYY-MM' month"""
    if not MONTH_PATTERN.match(month or ""):
        raise HTTPException(
            status_code=400,
            detail="Month must be in YYYY-MM format, e.g. 2026-08"
        )

    now = datetime.now()
    if month > f"{now.year:04d}-{now.month:02d}":
        raise HTTPException(
            status_code=400,
            detail="Cannot mark a future month — that ZUS payment is not due yet"
        )


@router.get("/")
def list_zus_payments(months: Optional[int] = Query(None, ge=1, le=120)):
    """List ZUS months, newest first, with paid state and the fixed base rate"""
    db = get_sheets_db()
    return db.get_zus_payments(months=months)


@router.post("/{month}/mark-paid")
def mark_zus_paid(month: str):
    """Mark a ZUS month as paid"""
    _validate_month(month)
    db = get_sheets_db()

    result = db.set_zus_paid(month, True)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to record ZUS payment")

    return {"success": True, **result}


@router.post("/{month}/mark-unpaid")
def mark_zus_unpaid(month: str):
    """Un-mark a ZUS month (reverses an accidental tick)"""
    _validate_month(month)
    db = get_sheets_db()

    result = db.set_zus_paid(month, False)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to update ZUS payment")

    return {"success": True, **result}
