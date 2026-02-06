"""
Client management endpoints
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models.database import get_db
from models.schemas import ClientCreate, Client as ClientSchema
from services.invoice_service import ClientService

router = APIRouter(prefix="/api/clients", tags=["clients"])


@router.get("/", response_model=List[ClientSchema])
def list_clients(db: Session = Depends(get_db)):
    """List all clients"""
    service = ClientService(db)
    return service.list_clients()


@router.post("/", response_model=ClientSchema)
def create_client(client: ClientCreate, db: Session = Depends(get_db)):
    """Create a new client"""
    service = ClientService(db)
    return service.create_client(
        name=client.name,
        address=client.address,
        company_id=client.company_id,
        email=client.email
    )


@router.get("/{client_id}", response_model=ClientSchema)
def get_client(client_id: int, db: Session = Depends(get_db)):
    """Get a single client"""
    service = ClientService(db)
    client = service.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.patch("/{client_id}", response_model=ClientSchema)
def update_client(
    client_id: int,
    update: ClientCreate,
    db: Session = Depends(get_db)
):
    """Update a client"""
    service = ClientService(db)
    client = service.update_client(
        client_id,
        name=update.name,
        address=update.address,
        company_id=update.company_id,
        email=update.email
    )
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.delete("/{client_id}")
def delete_client(client_id: int, db: Session = Depends(get_db)):
    """Delete a client (only if no invoices)"""
    service = ClientService(db)
    success = service.delete_client(client_id)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete client with existing invoices"
        )
    return {"success": True}
