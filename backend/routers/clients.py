"""
Client endpoints - using Google Sheets as database
"""
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.sheets_database import get_sheets_db

router = APIRouter(prefix="/api/clients", tags=["clients"])


class CreateClientRequest(BaseModel):
    name: str
    address: str = ""
    company_id: str = ""
    email: Optional[str] = None


@router.get("/")
def list_clients():
    """List all clients"""
    db = get_sheets_db()
    return db.get_clients()


@router.post("/")
def create_client(data: CreateClientRequest):
    """Create a new client"""
    db = get_sheets_db()
    try:
        client = db.create_client(
            name=data.name,
            address=data.address,
            company_id=data.company_id,
            email=data.email or ""
        )
        return client
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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


@router.delete("/{client_id}")
def delete_client(client_id: int):
    """Delete a client"""
    db = get_sheets_db()
    success = db.delete_client(client_id)
    if not success:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"success": True, "client_id": client_id}


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
