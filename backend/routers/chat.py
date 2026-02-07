"""
AI Chat endpoint for invoice and payment creation
"""
from fastapi import APIRouter, HTTPException

from models.schemas import ChatMessage, ChatResponse
from services.ai_service import get_ai_service
from services.sheets_database import get_sheets_db

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def chat(message: ChatMessage):
    """
    Process chat message and extract invoice/payment data

    Returns AI response with extracted fields
    """
    ai_service = get_ai_service()
    db = get_sheets_db()

    # Get available clients for context
    clients = db.get_clients()
    client_list = [{"id": c["id"], "name": c["name"]} for c in clients]

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
async def confirm_action(conversation_id: str):
    """
    Confirm and create invoice OR payment from chat conversation

    Expects the conversation to have extracted all required fields
    """
    ai_service = get_ai_service()
    db = get_sheets_db()

    # Get available clients for context
    clients = db.get_clients()
    client_list = [{"id": c["id"], "name": c["name"]} for c in clients]

    # Send confirmation message
    result = await ai_service.chat(
        message="Yes, please confirm.",
        conversation_id=conversation_id,
        available_clients=client_list
    )

    extracted = result.get("extracted_data")
    if not extracted:
        raise HTTPException(
            status_code=400,
            detail="No data available. Please provide details first."
        )

    # Find client by name
    client_name = extracted.get("client_name")
    if not client_name:
        raise HTTPException(status_code=400, detail="Client name is required")

    client = db.get_client_by_name(client_name)
    if not client:
        raise HTTPException(
            status_code=404,
            detail=f"Client '{client_name}' not found"
        )

    # Check action type (default to invoice for backwards compatibility)
    action_type = extracted.get("action_type", "invoice")

    amount = extracted.get("amount")
    if not amount:
        raise HTTPException(status_code=400, detail="Amount is required")

    if action_type == "payment":
        # Create payment
        invoice_id = extracted.get("invoice_id")
        if not invoice_id:
            raise HTTPException(
                status_code=400,
                detail="Invoice number is required for payments"
            )

        try:
            payment = db.create_payment(
                invoice_id=int(invoice_id),
                amount=float(amount),
                currency=extracted.get("currency", "EUR"),
                date=extracted.get("date"),
                method=extracted.get("method"),
                notes=extracted.get("notes")
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Clear conversation
        ai_service.clear_conversation(conversation_id)

        return {
            "success": True,
            "action_type": "payment",
            "payment_id": payment["id"],
            "invoice_id": invoice_id,
            "amount": payment["amount"],
            "message": f"Payment of {payment['currency']} {payment['amount']:,.2f} recorded for Invoice #{invoice_id}"
        }
    else:
        # Create invoice
        invoice = db.create_invoice(
            client_id=client["id"],
            description=extracted.get("description", ""),
            amount=float(amount),
            currency=extracted.get("currency", "EUR"),
            work_dates=extracted.get("work_dates")
        )

        # Clear conversation
        ai_service.clear_conversation(conversation_id)

        return {
            "success": True,
            "action_type": "invoice",
            "invoice_id": invoice["id"],
            "invoice_number": invoice["invoice_number"],
            "message": f"Invoice {invoice['invoice_number']} created successfully!"
        }


@router.delete("/{conversation_id}")
def clear_conversation(conversation_id: str):
    """Clear a conversation"""
    ai_service = get_ai_service()
    ai_service.clear_conversation(conversation_id)
    return {"success": True}
