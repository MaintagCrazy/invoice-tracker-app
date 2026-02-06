"""
Configuration for Invoice Tracker App
"""
import os
from typing import Optional


class Config:
    """Application configuration from environment variables"""

    # API Keys
    OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
    API_KEY: str = os.environ.get("API_KEY", "")

    # Database
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./invoices.db")

    # Gmail (base64 encoded credentials)
    GMAIL_CREDENTIALS_B64: str = os.environ.get("GMAIL_CREDENTIALS_B64", "")
    GMAIL_TOKEN_B64: str = os.environ.get("GMAIL_TOKEN_B64", "")

    # OpenRouter Settings
    AI_MODEL: str = "google/gemini-2.0-flash-001"
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
        'address': 'Grójecka 214/118',
        'city': '02-390 Warszawa',
        'phone': '0048 792678888',
        'email': 'c.d.consulting.warsaw@gmail.com',
        'nip': '7011092699',
        'bank': 'Bank Millennium Spółka Akcyjna',
        'iban': 'PL 88 1160 2202 0000 0005 3052 8886',
        'swift': 'BIGBPLPW'
    }

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
