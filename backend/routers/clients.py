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
