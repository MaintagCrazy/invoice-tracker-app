"""
Client endpoints - using Google Sheets as database
"""
from typing import List
from fastapi import APIRouter, HTTPException

from services.sheets_database import get_sheets_db

router = APIRouter(prefix="/api/clients", tags=["clients"])


@router.get("/")
def list_clients():
    """List all clients"""
    db = get_sheets_db()
    return db.get_clients()


@router.get("/{client_id}")
def get_client(client_id: int):
    """Get a single client"""
    db = get_sheets_db()
    client = db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.get("/{client_id}/summary")
def get_client_summary(client_id: int):
    """Get client summary with invoices, payments, and totals"""
    db = get_sheets_db()
    summary = db.get_client_summary(client_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Client not found")
    return summary


@router.get("/{client_id}/unpaid-invoices")
def get_client_unpaid_invoices(client_id: int):
    """Get unpaid or partially paid invoices for a client"""
    db = get_sheets_db()
    client = db.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    invoices = db.get_unpaid_invoices_for_client(client_id)
    return {
        "client": client,
        "unpaid_invoices": invoices
    }
