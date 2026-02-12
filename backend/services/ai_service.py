"""
AI Service using OpenRouter with native function calling (tool use)
"""
import json
import logging
import uuid
from typing import Optional, Dict, Any, List

import httpx

from config import config

logger = logging.getLogger(__name__)


# ============ FUNCTION TOOL DEFINITIONS ============

FUNCTION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_invoice",
            "description": "Create a new invoice for a client. Descriptions default to German unless the user specifies another language.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {
                        "type": "string",
                        "description": "The client/company name. Must match a known client."
                    },
                    "amount": {
                        "type": "number",
                        "description": "Invoice amount"
                    },
                    "currency": {
                        "type": "string",
                        "enum": ["EUR", "PLN"],
                        "description": "Currency code. Default EUR."
                    },
                    "description": {
                        "type": "string",
                        "description": "Service description. Default to German (e.g. Bauarbeiten, Montagearbeiten)."
                    },
                    "work_dates": {
                        "type": "string",
                        "description": "Optional work period (e.g. '01.01-15.01.2026'). Null if not provided."
                    }
                },
                "required": ["client_name", "amount", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "record_payment",
            "description": "Record a payment against an existing invoice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {
                        "type": "string",
                        "description": "The client name"
                    },
                    "amount": {
                        "type": "number",
                        "description": "Payment amount"
                    },
                    "invoice_id": {
                        "type": "integer",
                        "description": "The invoice file number (e.g. 15)"
                    },
                    "currency": {
                        "type": "string",
                        "enum": ["EUR", "PLN"],
                        "description": "Currency. Default EUR."
                    },
                    "date": {
                        "type": "string",
                        "description": "Payment date in DD.MM.YYYY format. Null for today."
                    },
                    "method": {
                        "type": "string",
                        "description": "Payment method (bank transfer, cash, etc.)"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes"
                    }
                },
                "required": ["client_name", "amount", "invoice_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_client",
            "description": "Add a new client to the database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {
                        "type": "string",
                        "description": "Company/client name"
                    },
                    "address": {
                        "type": "string",
                        "description": "Full address"
                    },
                    "company_id": {
                        "type": "string",
                        "description": "VAT/UST-ID number"
                    },
                    "contact_person": {
                        "type": "string",
                        "description": "Contact person name"
                    },
                    "phone": {
                        "type": "string",
                        "description": "Phone number"
                    },
                    "email": {
                        "type": "string",
                        "description": "Email address"
                    }
                },
                "required": ["client_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_clients",
            "description": "List all clients in the database.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_data",
            "description": "Query invoices, payments, balances, or statistics. Use for questions like 'what does X owe?' or 'show me unpaid invoices'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "enum": ["invoices", "payments", "balance", "stats"],
                        "description": "What kind of data to query"
                    },
                    "client_name": {
                        "type": "string",
                        "description": "Optional: filter by client name"
                    }
                },
                "required": ["query_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_invoice",
            "description": "Edit an existing invoice's amount, description, status, or work dates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "integer",
                        "description": "The invoice file number to edit"
                    },
                    "new_amount": {
                        "type": "number",
                        "description": "New amount (if changing)"
                    },
                    "new_description": {
                        "type": "string",
                        "description": "New description (if changing)"
                    },
                    "new_status": {
                        "type": "string",
                        "enum": ["draft", "sent", "paid"],
                        "description": "New status (if changing)"
                    }
                },
                "required": ["invoice_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_invoice_pdf",
            "description": "Get the preview/download links for an invoice PDF.",
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "integer",
                        "description": "The invoice file number"
                    }
                },
                "required": ["invoice_id"]
            }
        }
    }
]

# Write operations need user confirmation before executing
WRITE_OPERATIONS = {"create_invoice", "record_payment", "add_client", "edit_invoice"}
# Read operations execute immediately
READ_OPERATIONS = {"list_clients", "query_data", "get_invoice_pdf"}


SYSTEM_PROMPT = """You are the AI assistant for C.D. Grupa Budowlana's invoice tracking system.

## CRITICAL RULES:
1. ALWAYS speak to the user in English. Never switch to another language.
2. Invoice descriptions should DEFAULT TO GERMAN unless the user explicitly asks otherwise.
3. The KNOWN CLIENTS list below is your LIVE database — it is accurate and up to date.
4. When the user refers to a client by partial name (e.g., "Schuy" or "Bauceram"), match it to the closest client in the KNOWN CLIENTS list.
5. Dates (work_dates) are OPTIONAL for invoices. If the user doesn't mention dates, don't include them. Never block an invoice because dates are missing.
6. Use the provided function tools to take actions. For questions and greetings, just respond normally without calling tools.

## LANGUAGE RULES:
- ALWAYS speak in English
- Invoice "description" defaults to GERMAN (e.g., "Beratungsleistungen", "Bauarbeiten", "Montagearbeiten")
- If the user explicitly writes the description in English, keep it in English

## CLIENT MATCHING:
- The KNOWN CLIENTS list below is your LIVE, ACCURATE database
- Always fuzzy-match user input to this list: "Schuy" = "Hans Schuy Baustoffges. mbH", "Bauceram" = "Bauceram GmbH"
- NEVER say "I don't have any clients" when the list below contains clients

## KNOWN CLIENTS:
{clients_placeholder}

## HELP (when user types /help):
- Create invoices (client + amount + description, dates optional)
- Record payments (client + amount + invoice number)
- Edit invoices (change amount, description, or status)
- Add new clients (just paste client details)
- List clients ("show my clients")
- Check balances ("what does [client] owe?")
- Get invoice PDFs ("show me invoice 15")
- Tip: Descriptions default to German. Type naturally in English, German, or Polish.
"""


class AIService:
    """AI service for invoice operations using OpenRouter with function calling"""

    def __init__(self):
        self.api_key = config.OPENROUTER_API_KEY
        self.model = config.AI_MODEL
        self.base_url = config.AI_BASE_URL
        self.conversations: Dict[str, list] = {}
        self.pending_actions: Dict[str, Dict[str, Any]] = {}

    def _get_conversation(self, conversation_id: str) -> list:
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = []
        return self.conversations[conversation_id]

    def _add_to_conversation(self, conversation_id: str, message: dict):
        """Add a message dict to conversation history"""
        history = self._get_conversation(conversation_id)
        history.append(message)
        if len(history) > 20:
            self.conversations[conversation_id] = history[-20:]

    def store_pending_action(self, conversation_id: str, action: Dict[str, Any]):
        """Store a pending write action for later confirmation"""
        self.pending_actions[conversation_id] = action

    def get_pending_action(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve and remove a pending action"""
        return self.pending_actions.pop(conversation_id, None)

    def _generate_confirmation_message(self, function_name: str, args: dict) -> str:
        """Generate a human-readable confirmation message for a tool call"""
        if function_name == "create_invoice":
            currency = args.get("currency", "EUR")
            msg = f"I'll create an invoice for **{args.get('client_name', '?')}**:\n"
            msg += f"- Amount: {currency} {args.get('amount', 0):,.2f}\n"
            msg += f"- Description: {args.get('description', '-')}\n"
            if args.get("work_dates"):
                msg += f"- Work period: {args['work_dates']}\n"
            msg += "\nPlease review the details and confirm."
            return msg

        elif function_name == "record_payment":
            currency = args.get("currency", "EUR")
            msg = f"I'll record a payment for **{args.get('client_name', '?')}**:\n"
            msg += f"- Amount: {currency} {args.get('amount', 0):,.2f}\n"
            msg += f"- Invoice #: {args.get('invoice_id', '?')}\n"
            if args.get("method"):
                msg += f"- Method: {args['method']}\n"
            if args.get("date"):
                msg += f"- Date: {args['date']}\n"
            msg += "\nPlease review and confirm."
            return msg

        elif function_name == "add_client":
            msg = f"I'll add a new client: **{args.get('client_name', '?')}**\n"
            if args.get("address"):
                msg += f"- Address: {args['address']}\n"
            if args.get("company_id"):
                msg += f"- VAT/Tax ID: {args['company_id']}\n"
            if args.get("contact_person"):
                msg += f"- Contact: {args['contact_person']}\n"
            if args.get("email"):
                msg += f"- Email: {args['email']}\n"
            msg += "\nPlease review and confirm."
            return msg

        elif function_name == "edit_invoice":
            msg = f"I'll edit invoice **#{args.get('invoice_id', '?')}**:\n"
            if args.get("new_amount") is not None:
                msg += f"- New amount: {args['new_amount']:,.2f}\n"
            if args.get("new_description"):
                msg += f"- New description: {args['new_description']}\n"
            if args.get("new_status"):
                msg += f"- New status: {args['new_status']}\n"
            msg += "\nPlease review and confirm."
            return msg

        return "Please confirm this action."

    async def chat(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        available_clients: Optional[list] = None,
        context_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        # Build system prompt
        system_prompt = SYSTEM_PROMPT
        if available_clients:
            client_list = "\n".join(f"- {c['name']} (ID: {c['id']})" for c in available_clients)
        else:
            client_list = "(No clients loaded)"
        system_prompt = system_prompt.replace("{clients_placeholder}", client_list)

        if context_data:
            context_str = "\n\n## CURRENT DATA CONTEXT:\n"
            if "stats" in context_data:
                s = context_data["stats"]
                context_str += f"- Total invoices: {s.get('total_invoices', 0)}\n"
                context_str += f"- Unpaid/Due: EUR {s.get('total_due', 0):,.2f}\n"
                context_str += f"- Total paid: EUR {s.get('total_paid', 0):,.2f}\n"
            if "client_count" in context_data:
                context_str += f"- Total clients: {context_data['client_count']}\n"
            system_prompt += context_str

        # Add user message to history
        self._add_to_conversation(conversation_id, {"role": "user", "content": message})
        history = self._get_conversation(conversation_id)

        messages = [{"role": "system", "content": system_prompt}] + history

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://invoice-tracker.railway.app",
                        "X-Title": "Invoice Tracker App"
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "tools": FUNCTION_TOOLS,
                        "tool_choice": "auto",
                        "temperature": 0.4,
                        "max_tokens": 1500
                    }
                )
                response.raise_for_status()
                result = response.json()

            choice = result["choices"][0]
            assistant_message = choice["message"]
            finish_reason = choice.get("finish_reason", "stop")

            # Store assistant message in conversation
            self._add_to_conversation(conversation_id, assistant_message)

            # Check for tool calls
            tool_calls = assistant_message.get("tool_calls", [])

            if tool_calls:
                tool_call = tool_calls[0]  # Handle one tool call at a time
                function_name = tool_call["function"]["name"]
                try:
                    function_args = json.loads(tool_call["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    function_args = {}

                if function_name in WRITE_OPERATIONS:
                    # Write operation: needs user confirmation
                    confirmation_msg = self._generate_confirmation_message(function_name, function_args)

                    # Map function name to action_type for frontend
                    action_type_map = {
                        "create_invoice": "invoice",
                        "record_payment": "payment",
                        "add_client": "add_client",
                        "edit_invoice": "edit_invoice"
                    }

                    extracted_data = {**function_args, "action_type": action_type_map.get(function_name, function_name)}

                    # Store the pending action server-side
                    self.store_pending_action(conversation_id, {
                        "function_name": function_name,
                        "arguments": function_args,
                        "tool_call_id": tool_call.get("id", "")
                    })

                    return {
                        "response": confirmation_msg,
                        "conversation_id": conversation_id,
                        "extracted_data": extracted_data,
                        "needs_confirmation": True,
                    }

                elif function_name in READ_OPERATIONS:
                    # Read operation: execute immediately via callback, return result
                    return {
                        "response": "",  # Will be filled by the router
                        "conversation_id": conversation_id,
                        "extracted_data": {**function_args, "action_type": function_name},
                        "needs_confirmation": False,
                        "execute_read": function_name,
                        "read_args": function_args,
                        "tool_call_id": tool_call.get("id", "")
                    }

            # No tool calls — conversational response
            text_response = assistant_message.get("content", "") or ""
            return {
                "response": text_response,
                "conversation_id": conversation_id,
                "extracted_data": None,
                "needs_confirmation": False,
            }

        except httpx.HTTPError as e:
            logger.error(f"OpenRouter API error: {e}")
            return {
                "response": "Sorry, I'm having trouble connecting to the AI service. Please try again.",
                "conversation_id": conversation_id,
                "extracted_data": None,
                "needs_confirmation": False,
            }
        except Exception as e:
            logger.error(f"Unexpected error in AI chat: {type(e).__name__}: {e}")
            return {
                "response": "Something went wrong. Please try again.",
                "conversation_id": conversation_id,
                "extracted_data": None,
                "needs_confirmation": False,
            }

    async def send_tool_result(
        self,
        conversation_id: str,
        tool_call_id: str,
        result_content: str,
        available_clients: Optional[list] = None,
        context_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """Send a tool result back to the AI and get a natural language summary"""
        # Add tool result to conversation
        self._add_to_conversation(conversation_id, {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result_content
        })

        # Build system prompt
        system_prompt = SYSTEM_PROMPT
        if available_clients:
            client_list = "\n".join(f"- {c['name']} (ID: {c['id']})" for c in available_clients)
        else:
            client_list = "(No clients loaded)"
        system_prompt = system_prompt.replace("{clients_placeholder}", client_list)

        history = self._get_conversation(conversation_id)
        messages = [{"role": "system", "content": system_prompt}] + history

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://invoice-tracker.railway.app",
                        "X-Title": "Invoice Tracker App"
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "tools": FUNCTION_TOOLS,
                        "tool_choice": "auto",
                        "temperature": 0.4,
                        "max_tokens": 1500
                    }
                )
                response.raise_for_status()
                result = response.json()

            assistant_message = result["choices"][0]["message"]
            self._add_to_conversation(conversation_id, assistant_message)
            return assistant_message.get("content", "") or result_content

        except Exception as e:
            logger.error(f"Error sending tool result: {e}")
            return result_content

    def clear_conversation(self, conversation_id: str):
        if conversation_id in self.conversations:
            del self.conversations[conversation_id]
        self.pending_actions.pop(conversation_id, None)


# Singleton
_ai_service: Optional[AIService] = None


def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service
