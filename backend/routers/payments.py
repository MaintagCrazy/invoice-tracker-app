"""
Payment endpoints - using Google Sheets as database
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException

from services.sheets_database import get_sheets_db
from models.schemas import PaymentCreate

router = APIRouter(prefix="/api/payments", tags=["payments"])


@router.get("/")
def list_payments(client_id: Optional[int] = None, invoice_id: Optional[int] = None):
    """List all payments with optional filters"""
    db = get_sheets_db()
    return db.get_payments(client_id=client_id, invoice_id=invoice_id)


@router.post("/")
def create_payment(payment: PaymentCreate):
    """Create a new payment"""
    db = get_sheets_db()

    # Verify invoice exists
    invoice = db.get_invoice(payment.invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Validate payment amount
    if payment.amount <= 0:
        raise HTTPException(status_code=400, detail="Payment amount must be positive")

    if payment.amount > invoice['amount_due']:
        raise HTTPException(
            status_code=400,
            detail=f"Payment amount ({payment.amount}) exceeds remaining due ({invoice['amount_due']})"
        )

    try:
        return db.create_payment(
            invoice_id=payment.invoice_id,
            amount=payment.amount,
            currency=payment.currency,
            date=payment.date,
            method=payment.method,
            notes=payment.notes
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{payment_id}")
def get_payment(payment_id: int):
    """Get a single payment by ID"""
    db = get_sheets_db()
    payment = db.get_payment(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


@router.delete("/{payment_id}")
def delete_payment(payment_id: int):
    """Delete a payment"""
    db = get_sheets_db()

    # Verify payment exists
    payment = db.get_payment(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    success = db.delete_payment(payment_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete payment")

    return {"success": True, "message": f"Payment {payment_id} deleted"}
