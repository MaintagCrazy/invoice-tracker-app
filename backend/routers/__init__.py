from .invoices import router as invoices_router
from .clients import router as clients_router
from .chat import router as chat_router
from .email import router as email_router
from .payments import router as payments_router
from .sync import router as sync_router

# EFB 223 has heavy deps (anthropic, openpyxl, fpdf2, pikepdf).
# If they're not installed, don't crash the rest of the app.
try:
    from .efb223 import router as efb223_router
except ImportError:
    efb223_router = None
