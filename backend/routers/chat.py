"""
AI Chat endpoint — full agent capabilities
Handles: invoices, payments, add client, list clients, queries, help, general chat
"""
import logging
from fastapi import APIRouter, HTTPException

from models.schemas import ChatMessage, ChatResponse
from services.ai_service import get_ai_service
from services.sheets_database import get_sheets_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def chat(message: ChatMessage):
    """
    Process chat message with full AI agent capabilities.
    Handles invoices, payments, clients, queries, and general conversation.
    """
    ai_service = get_ai_service()
    db = get_sheets_db()

    # Build context for the AI
    clients = db.get_clients()
    client_list = [{"id": c["id"], "name": c["name"]} for c in clients]

    # Provide stats context so AI can answer questions
    try:
        stats = db.get_stats()
        context_data = {
            "stats": stats,
            "client_count": len(clients),
        }
    except Exception:
        context_data = {"client_count": len(clients)}

    # Process with AI
    result = await ai_service.chat(
        message=message.message,
        conversation_id=message.conversation_id,
        available_clients=client_list,
        context_data=context_data
    )

    extracted = result.get("extracted_data") or {}
    action_type = extracted.get("action_type") if extracted else None
    needs_confirmation = result.get("needs_confirmation", False)

    # For list_clients action, enrich the response with actual client data
    if action_type == "list_clients":
        needs_confirmation = False

    # For query/help/general, never need confirmation
    if action_type in ("query", "help", "general", "list_clients"):
        needs_confirmation = False

    return ChatResponse(
        response=result.get("response", ""),
        conversation_id=result.get("conversation_id", ""),
        extracted_data=result.get("extracted_data"),
        needs_confirmation=needs_confirmation
    )


@router.post("/confirm")
async def confirm_action(conversation_id: str):
    """
    Confirm and execute the pending action from chat conversation.
    Supports: invoice creation, payment recording, client addition.
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

    action_type = extracted.get("action_type", "invoice")

    # ============ ADD CLIENT ============
    if action_type == "add_client":
        client_name = extracted.get("client_name")
        if not client_name:
            raise HTTPException(status_code=400, detail="Client name is required")

        try:
            new_client = db.create_client(
                name=client_name,
                address=extracted.get("address", ""),
                company_id=extracted.get("company_id", ""),
                email=extracted.get("email", ""),
                contact_person=extracted.get("contact_person", ""),
                phone=extracted.get("phone", "")
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        ai_service.clear_conversation(conversation_id)

        return {
            "success": True,
            "action_type": "add_client",
            "client_id": new_client["id"],
            "client_name": new_client["name"],
            "message": f"Client '{new_client['name']}' added successfully! (ID: {new_client['id']})"
        }

    # ============ PAYMENT ============
    if action_type == "payment":
        client_name = extracted.get("client_name")
        if not client_name:
            raise HTTPException(status_code=400, detail="Client name is required")

        client = db.get_client_by_name(client_name)
        if not client:
            raise HTTPException(status_code=404, detail=f"Client '{client_name}' not found")

        amount = extracted.get("amount")
        if not amount:
            raise HTTPException(status_code=400, detail="Amount is required")

        invoice_id = extracted.get("invoice_id")
        if not invoice_id:
            raise HTTPException(status_code=400, detail="Invoice number is required for payments")

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

        ai_service.clear_conversation(conversation_id)

        return {
            "success": True,
            "action_type": "payment",
            "payment_id": payment["id"],
            "invoice_id": invoice_id,
            "amount": payment["amount"],
            "message": f"Payment of {payment['currency']} {payment['amount']:,.2f} recorded for Invoice #{invoice_id}"
        }

    # ============ INVOICE (default) ============
    client_name = extracted.get("client_name")
    if not client_name:
        raise HTTPException(status_code=400, detail="Client name is required")

    client = db.get_client_by_name(client_name)
    if not client:
        raise HTTPException(status_code=404, detail=f"Client '{client_name}' not found")

    amount = extracted.get("amount")
    if not amount:
        raise HTTPException(status_code=400, detail="Amount is required")

    invoice = db.create_invoice(
        client_id=client["id"],
        description=extracted.get("description", ""),
        amount=float(amount),
        currency=extracted.get("currency", "EUR"),
        work_dates=extracted.get("work_dates")
    )

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
