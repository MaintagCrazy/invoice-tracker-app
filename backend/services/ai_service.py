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


SYSTEM_PROMPT = """You are an invoice creation assistant for C.D. Grupa Budowlana, a Polish construction company.

Your job is to help create invoices through natural conversation. Extract invoice details from user messages.

REQUIRED FIELDS (you must collect all of these):
- client: The client company name (must match one of our existing clients)
- amount: The invoice amount (number, in EUR unless specified otherwise)
- description: A description of the service/work performed

OPTIONAL BUT RECOMMENDED:
- work_dates: The period when work was performed (e.g., "January 2025", "15-20 December 2024")

INVOICE NUMBER FORMAT: XX/MM/YYYY (auto-generated based on current month)
- XX = Sequential number within the month (01, 02, 03...)
- MM = Current month (01-12)
- YYYY = Current year

RESPONSE FORMAT:
Always respond in JSON with this structure:
{
    "message": "Your response to the user in natural language",
    "extracted_data": {
        "client_name": "extracted client name or null",
        "amount": extracted number or null,
        "currency": "EUR" (or other if specified),
        "description": "extracted description or null",
        "work_dates": "extracted work period or null"
    },
    "ready_to_create": true/false (true only when ALL required fields are present),
    "missing_fields": ["list of missing required fields"]
}

CONVERSATION RULES:
1. Be helpful and conversational, but stay focused on invoice creation
2. If information is missing, ask for it naturally
3. Confirm details before marking ready_to_create as true
4. If user provides all info at once, confirm and mark ready
5. Support both English and Polish messages
6. When ready_to_create is true, summarize the invoice details for confirmation

KNOWN CLIENTS (match user input to these):
- Bauceram GmbH (or "bauceram")
- Clinker Bau Schweiz GmbH (or "clinker")
- Stuckgeschäft Laufenberg (or "laufenberg")

EXAMPLE INTERACTIONS:

User: "Create invoice for Bauceram, 30k EUR for construction work in January"
Response: {
    "message": "I'll create an invoice for Bauceram GmbH for EUR 30,000 for construction work in January. Is this correct?",
    "extracted_data": {
        "client_name": "Bauceram GmbH",
        "amount": 30000,
        "currency": "EUR",
        "description": "Construction work",
        "work_dates": "January"
    },
    "ready_to_create": true,
    "missing_fields": []
}

User: "I need to invoice clinker"
Response: {
    "message": "I'll help you create an invoice for Clinker Bau Schweiz GmbH. What is the amount and what work was performed?",
    "extracted_data": {
        "client_name": "Clinker Bau Schweiz GmbH",
        "amount": null,
        "currency": "EUR",
        "description": null,
        "work_dates": null
    },
    "ready_to_create": false,
    "missing_fields": ["amount", "description"]
}
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
        available_clients: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Process user message and extract invoice data

        Returns:
            dict with keys: response, conversation_id, extracted_data, needs_confirmation
        """
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        # Add client list to context
        system_prompt = SYSTEM_PROMPT
        if available_clients:
            client_list = "\n".join(f"- {c['name']}" for c in available_clients)
            system_prompt = system_prompt.replace(
                "KNOWN CLIENTS (match user input to these):",
                f"KNOWN CLIENTS (match user input to these, with IDs):\n{client_list}\n\nOriginal list:"
            )

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
                        "temperature": 0.3,
                        "max_tokens": 1000
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

                return {
                    "response": parsed.get("message", ""),
                    "conversation_id": conversation_id,
                    "extracted_data": parsed.get("extracted_data"),
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
                "response": "Sorry, I encountered an error processing your request. Please try again.",
                "conversation_id": conversation_id,
                "extracted_data": None,
                "needs_confirmation": False,
                "error": str(e)
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
