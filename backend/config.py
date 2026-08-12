"""
Configuration for Invoice Tracker App
"""
import os
from typing import Optional, List


class Config:
    """Application configuration from environment variables"""

    # API Keys
    OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
    API_KEY: str = os.environ.get("API_KEY", "")

    # Database
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./invoices.db")

    # Gmail (base64 encoded credentials) - c.d.consulting.warsaw@gmail.com
    GMAIL_CREDENTIALS_B64: str = os.environ.get("GMAIL_CREDENTIALS_B64", "")
    GMAIL_TOKEN_B64: str = os.environ.get("GMAIL_TOKEN_B64", "")

    # Google Drive (base64 encoded OAuth token) - glamova.hdht@gmail.com
    DRIVE_TOKEN_B64: str = os.environ.get("DRIVE_TOKEN_B64", "")

    # Google Drive (auto-share invoice folder with this account)
    USER_EMAIL: str = os.environ.get("USER_EMAIL", "")

    # OpenRouter Settings
    # Ordered fallback chain of flash models, newest first. The AI service tries
    # each in order and falls through to the next ONLY when a model is retired /
    # unavailable (OpenRouter 404). Override the whole chain with AI_MODELS
    # ("a,b,c"), or pin a single primary with AI_MODEL. All entries below are
    # verified to support OpenRouter tool/function calling.
    _DEFAULT_AI_MODELS = "anthropic/claude-sonnet-5,google/gemini-3.5-flash,google/gemini-2.5-flash"
    AI_MODELS: List[str] = [
        m.strip()
        for m in (os.environ.get("AI_MODELS") or os.environ.get("AI_MODEL") or _DEFAULT_AI_MODELS).split(",")
        if m.strip()
    ]
    # Back-compat: anything still reading config.AI_MODEL gets the primary model.
    AI_MODEL: str = AI_MODELS[0] if AI_MODELS else "google/gemini-2.5-flash"
    AI_BASE_URL: str = "https://openrouter.ai/api/v1"

    # Google Sheets for migration
    MIGRATION_SHEET_ID: str = "1xETHFJZO29qJj_UlyTqB29CRyOp7UFi49oEOvmfd084"

    # Tax accountants (always receive all invoices)
    TAX_ACCOUNTANT_EMAILS: list = [
        "edyta.karczewska@kdik.pl",
        "iwona.haliburda@kdik.pl"
    ]

    # Company info (from invoice_editor.py)
    COMPANY = {
        'name': 'C.D. Grupa Budowlana Hung Dat Nguyen',
        'address': 'Gr\u00f3jecka 214/118',
        'city': '02-390 Warszawa',
        'phone': '0048 792678888',
        'email': 'c.d.consulting.warsaw@gmail.com',
        'nip': '7011092699',
        'bank': 'Bank Millennium Sp\u00f3\u0142ka Akcyjna',
        'iban': 'PL 88 1160 2202 0000 0005 3052 8886',
        'swift': 'BIGBPLPW'
    }

    # KSeF 2.0 (Polish National e-Invoice System)
    KSEF_TOKEN: str = os.environ.get("KSEF_TOKEN", "")
    KSEF_ENVIRONMENT: str = os.environ.get("KSEF_ENVIRONMENT", "production")

    # ZUS (Polish monthly social-security contribution)
    # Fixed base rate supplied by the CEO. THIS IS THE ONLY PLACE IT IS DEFINED —
    # never hardcode the figure anywhere else. In months where invoices were
    # issued the real ZUS is usually higher (the health part scales with income),
    # but we have no formula for it: the UI flags those months, it never
    # calculates or displays an estimated higher figure.
    ZUS_BASE_AMOUNT_PLN: float = float(os.environ.get("ZUS_BASE_AMOUNT_PLN", "3500"))
    ZUS_CURRENCY: str = "PLN"
    # How many months back the ZUS tracker lists by default (newest first)
    ZUS_DEFAULT_MONTHS: int = 12

    @classmethod
    def is_production(cls) -> bool:
        """Check if running in production (Railway)"""
        return bool(os.environ.get("RAILWAY_ENVIRONMENT"))

    @classmethod
    def get_database_url(cls) -> str:
        """Get appropriate database URL"""
        url = cls.DATABASE_URL
        # Railway provides postgres:// but SQLAlchemy needs postgresql://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url


config = Config()
