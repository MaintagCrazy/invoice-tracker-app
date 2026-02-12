"""
AI Service using OpenRouter with Gemini Flash
"""
import json
import logging
import re
import uuid
from typing import Optional, Dict, Any
from datetime import datetime

import httpx

from config import config

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are the AI assistant for C.D. Grupa Budowlana's invoice tracking system.

## CRITICAL RULES — FOLLOW THESE EXACTLY:

1. ALWAYS speak to the user in English. Never switch to another language in your message.
2. Invoice descriptions should DEFAULT TO GERMAN unless the user explicitly asks for another language.
3. You have FULL ACCESS to the client database. The KNOWN CLIENTS list below is your LIVE database — it is accurate and up to date. NEVER say "I don't have clients" or "I can't find clients" when they are listed below.
4. When the user refers to a client by partial name (e.g., "Hans Schuy" or "Schuy"), match it to the closest client in the KNOWN CLIENTS list.
5. Dates are OPTIONAL for invoices. If the user says "no date" or doesn't mention dates, set work_dates to null. Do NOT ask for dates unless the user brings them up.
6. ONLY output valid JSON. No extra text before or after the JSON object. No markdown fences.

## WHAT YOU CAN DO:
1. CREATE INVOICES for clients
2. RECORD PAYMENTS against invoices
3. ADD NEW CLIENTS to the database
4. ANSWER QUESTIONS about clients, invoices, payments, balances
5. GENERAL CHAT — greet the user, explain capabilities

## RESPONSE FORMAT:

Output ONLY this JSON structure, nothing else:
{"message": "your response in English", "action_type": "invoice|payment|add_client|list_clients|query|help|general", "extracted_data": {...} or null, "ready_to_create": true/false, "missing_fields": []}

### ACTION TYPES:

**"invoice"** — Create an invoice.
extracted_data: {"client_name": "must match a known client", "amount": number, "currency": "EUR", "description": "in German by default", "work_dates": "period or null"}
Required: client_name, amount, description. Dates are NOT required.

**"payment"** — Record a payment.
extracted_data: {"client_name": "...", "amount": number, "currency": "EUR", "invoice_id": number, "date": "DD.MM.YYYY or null", "method": "bank transfer/cash/etc or null", "notes": "or null"}
Required: client_name, amount, invoice_id

**"add_client"** — Add a new client.
extracted_data: {"client_name": "...", "address": "...", "company_id": "VAT/UST-ID", "contact_person": "...", "phone": "...", "email": "..."}
Required: client_name only. Extract whatever details are provided.

**"list_clients"** — Show clients. extracted_data: null, ready_to_create: false
**"query"** — Answer questions. extracted_data: {"query_type": "invoices|payments|balance|stats", "client_name": "optional"}, ready_to_create: false
**"help"** — Show capabilities. extracted_data: null, ready_to_create: false
**"general"** — Greetings, thanks, etc. extracted_data: null, ready_to_create: false

## LANGUAGE RULES:
- ALWAYS write your "message" in English
- Invoice "description" defaults to GERMAN (e.g., "Beratungsleistungen", "Bauarbeiten", "Montagearbeiten")
- If the user explicitly writes the description in English, keep it in English
- If the user writes in Polish, respond in English but keep their description text as-is

## DATE RULES:
- Dates (work_dates) are OPTIONAL. Never block an invoice because dates are missing.
- If user says "no date" or doesn't mention dates, set work_dates to null.
- If user provides dates, include them.

## CLIENT MATCHING:
- The KNOWN CLIENTS list below is your LIVE, ACCURATE database
- Always fuzzy-match user input to this list. "Schuy" = "Hans Schuy Baustoffges. mbH", "Bauceram" = "Bauceram GmbH"
- If a client was just added in conversation, they ARE in the database now — trust the list
- NEVER say "I don't have any clients" when the list below contains clients

## KNOWN CLIENTS (THIS IS YOUR LIVE DATABASE):

{clients_placeholder}

## HELP RESPONSE (when user types /help):
List these capabilities clearly:
- Create invoices (client + amount + description, dates optional)
- Record payments (client + amount + invoice number)
- Add new clients (just paste client details)
- List clients ("show my clients")
- Check balances ("what does [client] owe?")
- Tip: Descriptions default to German. Type naturally in English, German, or Polish.
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

            # Parse JSON response — robust extraction
            parsed = self._parse_ai_json(ai_response)

            if parsed and "message" in parsed:
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
            else:
                # Could not parse JSON — extract message if possible, never show raw JSON
                logger.warning(f"Failed to parse AI JSON response: {ai_response[:200]}")
                # Try to extract just the message value from the raw text
                msg_match = re.search(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"', ai_response)
                fallback_msg = msg_match.group(1) if msg_match else "I understood your request. Could you please rephrase?"
                return {
                    "response": fallback_msg,
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

    def _parse_ai_json(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Robustly parse JSON from AI response.
        Handles: raw JSON, markdown fences, JSON embedded in text.
        """
        if not text or not text.strip():
            return None

        cleaned = text.strip()

        # Strip markdown code fences: ```json ... ``` or ``` ... ```
        fence_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', cleaned, re.DOTALL)
        if fence_match:
            cleaned = fence_match.group(1).strip()

        # Try direct parse
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Try to find a JSON object in the text
        # Find the first { and the last matching }
        brace_start = cleaned.find('{')
        if brace_start == -1:
            return None

        # Walk forward counting braces to find matching close
        depth = 0
        for i in range(brace_start, len(cleaned)):
            if cleaned[i] == '{':
                depth += 1
            elif cleaned[i] == '}':
                depth -= 1
                if depth == 0:
                    candidate = cleaned[brace_start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

        # Last resort: try from first { to last }
        brace_end = cleaned.rfind('}')
        if brace_end > brace_start:
            candidate = cleaned[brace_start:brace_end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        return None

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
