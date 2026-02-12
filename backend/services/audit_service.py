"""
Audit Log Service — logs actions to a dedicated Google Sheets tab.
Fire-and-forget: never blocks, never crashes the request.
"""
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

AUDIT_TAB = "Audit Log"


class AuditService:
    """Audit logging to Google Sheets"""

    def __init__(self):
        self._worksheet = None
        self._init_done = False

    def _get_worksheet(self):
        """Lazy-init: get or create the Audit Log worksheet"""
        if self._worksheet and self._init_done:
            return self._worksheet

        try:
            from services.sheets_database import get_sheets_db
            db = get_sheets_db()

            try:
                self._worksheet = db.sheet.worksheet(AUDIT_TAB)
            except Exception:
                self._worksheet = db.sheet.add_worksheet(
                    title=AUDIT_TAB, rows=2000, cols=5
                )
                headers = ["Timestamp", "Action", "Entity Type", "Entity ID", "Details"]
                self._worksheet.append_row(headers)
                logger.info("Created Audit Log worksheet")

            self._init_done = True
            return self._worksheet
        except Exception as e:
            logger.error(f"Failed to init audit worksheet: {e}")
            return None

    def log_action(
        self,
        action: str,
        entity_type: str = "",
        entity_id: str = "",
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Log an action. Fire-and-forget — catches all exceptions.

        Actions: invoice_created, invoice_edited, invoice_deleted,
                 payment_recorded, payment_deleted, client_added, client_deleted,
                 email_sent, email_send_failed
        """
        try:
            ws = self._get_worksheet()
            if not ws:
                return

            row = [
                datetime.now().isoformat(),
                action,
                entity_type,
                str(entity_id),
                json.dumps(details, default=str) if details else ""
            ]
            ws.append_row(row)
        except Exception as e:
            # Never crash — audit is non-critical
            logger.warning(f"Audit log failed ({action}): {e}")


# Singleton
_audit_service: Optional[AuditService] = None


def get_audit_service() -> AuditService:
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditService()
    return _audit_service
