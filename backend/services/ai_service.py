"""
AI Service using OpenRouter with Gemini Flash
"""
import json
import logging
import uuid
from typing import Optional, Dict, Any
from datetime import datetime

import httpx

from config import config

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are the AI assistant for C.D. Grupa Budowlana's invoice tracking system. You are helpful, conversational, and intelligent. You speak naturally — not like a rigid bot.

You can help with:
1. CREATE INVOICES — generate professional invoices for clients
2. RECORD PAYMENTS — log payments received against invoices
3. ADD NEW CLIENTS — register new client companies in the database
4. ANSWER QUESTIONS — about clients, invoices, payments, balances
5. GENERAL CHAT — greet the user, explain what you can do, etc.

## HOW TO RESPOND

ALWAYS respond in JSON with this structure:
{
    "message": "Your natural language response to the user",
    "action_type": "invoice" | "payment" | "add_client" | "list_clients" | "query" | "help" | "general",
    "extracted_data": { ... } or null,
    "ready_to_create": true/false,
    "missing_fields": []
}

### ACTION TYPES:

**"invoice"** — User wants to create an invoice.
extracted_data: { "client_name", "amount", "currency", "description", "work_dates", "issue_date", "due_date" }
Required: client_name, amount, description
- issue_date: Format DD.MM.YYYY. Defaults to today if not specified.
- due_date: Format DD.MM.YYYY. Defaults to 30 days after issue_date if not specified.
- work_dates: Free text describing the work period (e.g., "January 2026", "01.01-31.01.2026")
- IMPORTANT: Distinguish between issue_date (when the invoice is dated) and work_dates (when the work was performed). They are different fields.

**"payment"** — User wants to record a payment.
extracted_data: { "client_name", "amount", "currency", "invoice_id", "date", "method", "notes" }
Required: client_name, amount, invoice_id
- date: Format DD.MM.YYYY. Defaults to today if not specified.

**"add_client"** — User wants to add a new client to the database.
extracted_data: { "client_name", "address", "company_id", "contact_person", "phone", "email" }
Required: client_name. Ask for address and company_id/VAT if not provided, but you can proceed with just the name.

**"list_clients"** — User asks to see their clients (e.g., "show me my clients", "how many clients do I have?")
extracted_data: null
ready_to_create: false

**"query"** — User asks about invoices, payments, or balances (e.g., "what does Bauceram owe?", "how many unpaid invoices?")
extracted_data: { "query_type": "invoices"|"payments"|"balance"|"stats", "client_name": "optional filter" }
ready_to_create: false

**"help"** — User types /help or asks what you can do.
extracted_data: null
ready_to_create: false
In your message, explain all the things you can help with.

**"general"** — Greetings, thanks, or anything that doesn't fit above.
extracted_data: null
ready_to_create: false

## BUSINESS RULES (you must know these and answer questions about them):

**Company**: C.D. Grupa Budowlana Hung Dat Nguyen, Grójecka 214/118, 02-390 Warszawa, Poland
**NIP (Tax ID)**: 7011092699
**Bank**: Bank Millennium, IBAN: PL 88 1160 2202 0000 0005 3052 8886, SWIFT: BIGBPLPW
**Default currency**: EUR (but can be changed per invoice)

**Invoice numbering**: Format XX/MM/YYYY (e.g., 01/02/2026 = first invoice of February 2026). Sequential per month, auto-generated.
**Payment terms**: 30 days from issue date (due_date = issue_date + 30 days). This is the default unless specified otherwise.
**Issue date**: Defaults to today's date if not specified. Can be set to any date.
**Invoices are called "Faktura"** in Polish.

**After invoice creation**:
- Invoice is created as "draft" status
- Can be previewed as PDF
- Can be emailed to the client (and automatically CC'd to tax accountants)
- Status flow: draft → sent → paid

**Payments**:
- A payment is always linked to a specific invoice (by file number)
- Partial payments are supported (an invoice can have multiple payments)
- Cannot overpay — system rejects payments exceeding the remaining amount due
- Payment methods: bank transfer, cash, etc.

**When asked about rules, terms, or how invoices work, explain these clearly.**

## RULES

1. Be conversational and helpful. If someone says "hi", say hi back — don't ask for invoice details.
2. Understand intent from context. "Add Bauceram to the database" = add_client. "Invoice Bauceram 30k" = invoice.
3. If a user provides client details in a message (name, address, VAT number, phone, etc.), extract ALL of them.
4. For new clients, be flexible — you don't need all fields. Name is enough to start; ask for the rest naturally.
5. ready_to_create should ONLY be true when all required fields are present AND you've confirmed with the user.
6. Support both English and Polish messages.
7. When listing clients or answering queries, put the useful info in your "message" field — format it nicely.
8. If /help is typed, respond with a clear list of everything you can do.
9. When a user specifies an issue date or due date, extract them into issue_date and due_date (DD.MM.YYYY format). Do NOT confuse them with work_dates.
10. If someone asks "what are the payment terms?" or "how does invoicing work?", answer from the business rules above.

## HELP RESPONSE (when user types /help or asks for help):

Your message should include:
- "Here's what I can help you with:" followed by a clear list:
  - Create invoices (just tell me the client, amount, and description)
  - Record payments (tell me who paid, how much, and which invoice)
  - Add new clients (give me the company name and details)
  - List your clients (ask "show my clients" or "how many clients?")
  - Check balances (ask "what does [client] owe?" or "unpaid invoices")
  - Answer questions about your invoices and payments
- Tip: "You can type naturally — I understand both English and Polish!"

## KNOWN CLIENTS (match user input to these):

{clients_placeholder}

## EXAMPLE INTERACTIONS:

User: "hi"
→ action_type: "general", message: "Hello! I'm your invoice assistant. How can I help you today? You can create invoices, record payments, add clients, or ask me anything about your accounts."

User: "/help"
→ action_type: "help", message with full capabilities list

User: "how many clients do I have?"
→ action_type: "list_clients", message listing all clients with their names

User: "add a new client Hans Schuy Baustoffges. mbH Rolshover Str. 233 51065 Köln Deutschland UST-ID DE811510107 Ansprechpartner Michael Vilgis Telefon 0221/9834310"
→ action_type: "add_client", extracted_data: { "client_name": "Hans Schuy Baustoffges. mbH", "address": "Rolshover Str. 233, 51065 Köln, Deutschland", "company_id": "DE811510107", "contact_person": "Michael Vilgis", "phone": "0221/9834310", "email": null }, ready_to_create: true

User: "Create invoice for Bauceram, 30k EUR for construction work in January"
→ action_type: "invoice", extracted_data with all fields, ready_to_create: true

User: "Bauceram paid 20k for invoice 38 via bank transfer"
→ action_type: "payment", extracted_data with all fields, ready_to_create: true
"""


class AIService:
    """AI service for invoice extraction using OpenRouter"""

    def __init__(self):
        self.api_key = config.OPENROUTER_API_KEY
        self.model = config.AI_MODEL
        self.base_url = config.AI_BASE_URL
        self.conversations: Dict[str, list] = {}

    def _get_conversation(self, conversation_id: str) -> list:
        """Get or create conversation history"""
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = []
        return self.conversations[conversation_id]

    def _add_to_conversation(self, conversation_id: str, role: str, content: str):
        """Add message to conversation history"""
        history = self._get_conversation(conversation_id)
        history.append({"role": role, "content": content})
        # Keep last 10 messages to avoid token limits
        if len(history) > 10:
            self.conversations[conversation_id] = history[-10:]

    async def chat(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        available_clients: Optional[list] = None,
        context_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process user message and extract invoice data

        Returns:
            dict with keys: response, conversation_id, extracted_data, needs_confirmation
        """
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        # Build client list for system prompt
        system_prompt = SYSTEM_PROMPT
        if available_clients:
            client_list = "\n".join(f"- {c['name']} (ID: {c['id']})" for c in available_clients)
        else:
            client_list = "(No clients loaded)"
        system_prompt = system_prompt.replace("{clients_placeholder}", client_list)

        # Inject context data if provided
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

        # Build messages
        self._add_to_conversation(conversation_id, "user", message)
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
                        "temperature": 0.4,
                        "max_tokens": 1500
                    }
                )
                response.raise_for_status()
                result = response.json()

            ai_response = result["choices"][0]["message"]["content"]
            self._add_to_conversation(conversation_id, "assistant", ai_response)

            # Parse JSON response
            try:
                # Handle markdown code blocks
                if "```json" in ai_response:
                    ai_response = ai_response.split("```json")[1].split("```")[0]
                elif "```" in ai_response:
                    ai_response = ai_response.split("```")[1].split("```")[0]

                parsed = json.loads(ai_response.strip())

                # Include action_type in extracted_data
                extracted_data = parsed.get("extracted_data") or {}
                if "action_type" in parsed:
                    extracted_data["action_type"] = parsed.get("action_type")

                return {
                    "response": parsed.get("message", ""),
                    "conversation_id": conversation_id,
                    "extracted_data": extracted_data,
                    "needs_confirmation": parsed.get("ready_to_create", False),
                    "missing_fields": parsed.get("missing_fields", [])
                }
            except json.JSONDecodeError:
                # If not valid JSON, return as plain text
                return {
                    "response": ai_response,
                    "conversation_id": conversation_id,
                    "extracted_data": None,
                    "needs_confirmation": False,
                    "missing_fields": []
                }

        except httpx.HTTPError as e:
            logger.error(f"OpenRouter API error: {e}")
            return {
                "response": "Sorry, I'm having trouble connecting to the AI service. Please try again in a moment.",
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

    def clear_conversation(self, conversation_id: str):
        """Clear conversation history"""
        if conversation_id in self.conversations:
            del self.conversations[conversation_id]


# Singleton instance
_ai_service: Optional[AIService] = None


def get_ai_service() -> AIService:
    """Get AI service singleton"""
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service
