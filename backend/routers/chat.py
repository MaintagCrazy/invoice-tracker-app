"""
AI Chat endpoint — function calling agent
Handles: invoices, payments, clients, queries, help, general chat
Read operations execute immediately; write operations need confirmation.
"""
import json
import logging
from fastapi import APIRouter, HTTPException, Depends

from models.schemas import ChatMessage, ChatResponse
from services.ai_service import get_ai_service
from services.sheets_database import get_sheets_db
from middleware.rate_limiter import rate_limit_dependency

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _execute_read_operation(function_name: str, args: dict, db) -> str:
    """Execute a read operation and return a text summary"""
    if function_name == "list_clients":
        clients = db.get_clients()
        if not clients:
            return "No clients found in the database."
        lines = [f"**{c['name']}** (ID: {c['id']})" for c in clients]
        if any(c.get('address') for c in clients):
            lines = []
            for c in clients:
                line = f"**{c['name']}** (ID: {c['id']})"
                if c.get('address'):
                    line += f" — {c['address']}"
                lines.append(line)
        return "Here are your clients:\n" + "\n".join(f"- {l}" for l in lines)

    elif function_name == "query_data":
        query_type = args.get("query_type", "stats")
        client_name = args.get("client_name")

        if query_type == "stats":
            stats = db.get_stats()
            return json.dumps(stats, default=str)

        elif query_type == "balance":
            if client_name:
                client = db.get_client_by_name(client_name)
                if not client:
                    return f"Client '{client_name}' not found."
                summary = db.get_client_summary(client["id"])
                return json.dumps({
                    "client": client_name,
                    "total_invoiced": summary["total_invoiced"],
                    "total_paid": summary["total_paid"],
                    "outstanding": summary["total_due"],
                    "invoice_count": summary["invoice_count"]
                }, default=str)
            stats = db.get_stats()
            return json.dumps({
                "total_due": stats["total_due"],
                "total_paid": stats["total_paid"],
                "due_by_client": stats.get("due_by_client", {})
            }, default=str)

        elif query_type == "invoices":
            if client_name:
                client = db.get_client_by_name(client_name)
                if not client:
                    return f"Client '{client_name}' not found."
                invoices = db.get_invoices(client_id=client["id"])
            else:
                invoices = db.get_invoices()
            summary = [{
                "invoice_number": i["invoice_number"],
                "file_number": i["file_number"],
                "client": i["client"]["name"] if i.get("client") else "?",
                "amount": i["amount"],
                "currency": i.get("currency", "EUR"),
                "amount_due": i["amount_due"],
                "status": i["status"],
                "issue_date": i.get("issue_date", "")
            } for i in invoices[:20]]
            return json.dumps(summary, default=str)

        elif query_type == "payments":
            if client_name:
                client = db.get_client_by_name(client_name)
                if not client:
                    return f"Client '{client_name}' not found."
                payments = db.get_payments(client_id=client["id"])
            else:
                payments = db.get_payments()
            summary = [{
                "id": p["id"],
                "invoice_id": p["invoice_id"],
                "client": p["client"],
                "amount": p["amount"],
                "currency": p.get("currency", "EUR"),
                "date": p.get("date", ""),
                "method": p.get("method", "")
            } for p in payments[:20]]
            return json.dumps(summary, default=str)

        return "Unknown query type."

    elif function_name == "get_invoice_pdf":
        invoice_id = args.get("invoice_id")
        if not invoice_id:
            return "Invoice ID is required."
        invoice = db.get_invoice(int(invoice_id))
        if not invoice:
            return f"Invoice #{invoice_id} not found."
        return json.dumps({
            "invoice_id": invoice["id"],
            "invoice_number": invoice["invoice_number"],
            "client": invoice["client"]["name"] if invoice.get("client") else "?",
            "amount": invoice["amount"],
            "currency": invoice.get("currency", "EUR"),
            "preview_url": f"/api/invoices/{invoice['id']}/preview",
            "download_url": f"/api/invoices/{invoice['id']}/download"
        }, default=str)

    return "Unknown operation."


@router.post("/", response_model=ChatResponse, dependencies=[Depends(rate_limit_dependency)])
async def chat(message: ChatMessage):
    """Process chat message with AI function calling"""
    ai_service = get_ai_service()
    db = get_sheets_db()

    # Sanitize input
    user_message = message.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Build context
    clients = db.get_clients()
    client_list = [{"id": c["id"], "name": c["name"]} for c in clients]

    try:
        stats = db.get_stats()
        context_data = {"stats": stats, "client_count": len(clients)}
    except Exception:
        context_data = {"client_count": len(clients)}

    # Process with AI
    result = await ai_service.chat(
        message=user_message,
        conversation_id=message.conversation_id,
        available_clients=client_list,
        context_data=context_data
    )

    # Handle read operations — execute immediately
    if result.get("execute_read"):
        function_name = result["execute_read"]
        read_args = result.get("read_args", {})
        tool_call_id = result.get("tool_call_id", "")

        # Execute the read operation
        read_result = _execute_read_operation(function_name, read_args, db)

        # For get_invoice_pdf, send to AI for natural language + include action buttons
        # For list_clients and query_data, return the formatted text directly
        # (AI tends to lose data when rephrasing lists/tables)
        extracted_data = None

        if function_name == "get_invoice_pdf":
            # AI roundtrip only for PDF context (needs conversational wrapper)
            ai_response = await ai_service.send_tool_result(
                conversation_id=result["conversation_id"],
                tool_call_id=tool_call_id,
                result_content=read_result,
                available_clients=client_list,
                context_data=context_data
            )
            try:
                pdf_data = json.loads(read_result)
                extracted_data = {
                    "action_type": "get_invoice_pdf",
                    "invoice_id": pdf_data.get("invoice_id"),
                    "preview_url": pdf_data.get("preview_url"),
                    "download_url": pdf_data.get("download_url")
                }
            except (json.JSONDecodeError, KeyError):
                pass
        else:
            # Return pre-formatted text directly — no AI roundtrip
            ai_response = read_result

        return ChatResponse(
            response=ai_response,
            conversation_id=result["conversation_id"],
            extracted_data=extracted_data,
            needs_confirmation=False
        )

    # Normal response (conversational or write needing confirmation)
    return ChatResponse(
        response=result.get("response", ""),
        conversation_id=result.get("conversation_id", ""),
        extracted_data=result.get("extracted_data"),
        needs_confirmation=result.get("needs_confirmation", False)
    )


@router.post("/confirm", dependencies=[Depends(rate_limit_dependency)])
async def confirm_action(conversation_id: str):
    """
    Confirm a pending write action.
    Uses server-side stored pending action — no AI roundtrip needed.
    """
    ai_service = get_ai_service()
    db = get_sheets_db()

    pending = ai_service.get_pending_action(conversation_id)
    if not pending:
        raise HTTPException(
            status_code=400,
            detail="No pending action found. Please start a new request."
        )

    function_name = pending["function_name"]
    args = pending["arguments"]

    try:
        if function_name == "create_invoice":
            client = db.get_client_by_name(args["client_name"])
            if not client:
                raise HTTPException(status_code=404, detail=f"Client '{args['client_name']}' not found")

            invoice = db.create_invoice(
                client_id=client["id"],
                description=args.get("description", ""),
                amount=float(args["amount"]),
                currency=args.get("currency", "EUR"),
                work_dates=args.get("work_dates")
            )
            ai_service.clear_conversation(conversation_id)
            return {
                "success": True,
                "action_type": "invoice",
                "invoice_id": invoice["id"],
                "invoice_number": invoice["invoice_number"],
                "message": f"Invoice {invoice['invoice_number']} created successfully!"
            }

        elif function_name == "record_payment":
            amount = float(args["amount"])
            invoice_id = int(args["invoice_id"])

            payment = db.create_payment(
                invoice_id=invoice_id,
                amount=amount,
                currency=args.get("currency", "EUR"),
                date=args.get("date"),
                method=args.get("method"),
                notes=args.get("notes")
            )
            ai_service.clear_conversation(conversation_id)
            return {
                "success": True,
                "action_type": "payment",
                "payment_id": payment["id"],
                "invoice_id": invoice_id,
                "amount": payment["amount"],
                "message": f"Payment of {payment['currency']} {payment['amount']:,.2f} recorded for Invoice #{invoice_id}"
            }

        elif function_name == "add_client":
            new_client = db.create_client(
                name=args["client_name"],
                address=args.get("address", ""),
                company_id=args.get("company_id", ""),
                email=args.get("email", ""),
                contact_person=args.get("contact_person", ""),
                phone=args.get("phone", "")
            )
            ai_service.clear_conversation(conversation_id)
            return {
                "success": True,
                "action_type": "add_client",
                "client_id": new_client["id"],
                "client_name": new_client["name"],
                "message": f"Client '{new_client['name']}' added successfully! (ID: {new_client['id']})"
            }

        elif function_name == "edit_invoice":
            invoice_id = int(args["invoice_id"])
            updates = {}
            if args.get("new_amount") is not None:
                updates["amount"] = float(args["new_amount"])
            if args.get("new_description"):
                updates["description"] = args["new_description"]
            if args.get("new_status"):
                updates["status"] = args["new_status"]

            if not updates:
                raise HTTPException(status_code=400, detail="No changes specified")

            success = db.update_invoice(invoice_id, updates)
            if not success:
                raise HTTPException(status_code=404, detail=f"Invoice #{invoice_id} not found")

            ai_service.clear_conversation(conversation_id)
            return {
                "success": True,
                "action_type": "edit_invoice",
                "invoice_id": invoice_id,
                "message": f"Invoice #{invoice_id} updated successfully!"
            }

        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {function_name}")

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{conversation_id}")
def clear_conversation(conversation_id: str):
    """Clear a conversation"""
    ai_service = get_ai_service()
    ai_service.clear_conversation(conversation_id)
    return {"success": True}
