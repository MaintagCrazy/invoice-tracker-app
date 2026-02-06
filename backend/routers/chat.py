"""
AI Chat endpoint for invoice creation
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models.database import get_db, Client
from models.schemas import ChatMessage, ChatResponse
from services.ai_service import get_ai_service
from services.invoice_service import InvoiceService, ClientService

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def chat(message: ChatMessage, db: Session = Depends(get_db)):
    """
    Process chat message and extract invoice data

    Returns AI response with extracted invoice fields
    """
    ai_service = get_ai_service()
    client_service = ClientService(db)

    # Get available clients for context
    clients = client_service.list_clients()
    client_list = [{"id": c.id, "name": c.name} for c in clients]

    # Process with AI
    result = await ai_service.chat(
        message=message.message,
        conversation_id=message.conversation_id,
        available_clients=client_list
    )

    return ChatResponse(
        response=result.get("response", ""),
        conversation_id=result.get("conversation_id", ""),
        extracted_data=result.get("extracted_data"),
        needs_confirmation=result.get("needs_confirmation", False)
    )


@router.post("/confirm")
async def confirm_invoice(
    conversation_id: str,
    db: Session = Depends(get_db)
):
    """
    Confirm and create invoice from chat conversation

    Expects the conversation to have extracted all required fields
    """
    ai_service = get_ai_service()
    invoice_service = InvoiceService(db)
    client_service = ClientService(db)

    # Get the last message with extracted data
    # For now, we'll use the conversation state to get the data
    clients = client_service.list_clients()
    client_list = [{"id": c.id, "name": c.name} for c in clients]

    # Send confirmation message
    result = await ai_service.chat(
        message="Yes, please create this invoice.",
        conversation_id=conversation_id,
        available_clients=client_list
    )

    extracted = result.get("extracted_data")
    if not extracted:
        raise HTTPException(
            status_code=400,
            detail="No invoice data available. Please provide invoice details first."
        )

    # Find client by name
    client_name = extracted.get("client_name")
    if not client_name:
        raise HTTPException(status_code=400, detail="Client name is required")

    client = client_service.get_client_by_name(client_name)
    if not client:
        raise HTTPException(
            status_code=404,
            detail=f"Client '{client_name}' not found"
        )

    # Create invoice
    amount = extracted.get("amount")
    if not amount:
        raise HTTPException(status_code=400, detail="Amount is required")

    invoice = invoice_service.create_invoice(
        client_id=client.id,
        description=extracted.get("description", ""),
        amount=float(amount),
        currency=extracted.get("currency", "EUR"),
        work_dates=extracted.get("work_dates")
    )

    # Clear conversation
    ai_service.clear_conversation(conversation_id)

    return {
        "success": True,
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "message": f"Invoice {invoice.invoice_number} created successfully!"
    }


@router.delete("/{conversation_id}")
def clear_conversation(conversation_id: str):
    """Clear a conversation"""
    ai_service = get_ai_service()
    ai_service.clear_conversation(conversation_id)
    return {"success": True}
