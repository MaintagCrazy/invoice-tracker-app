"""
SQLAlchemy database models for Invoice Tracker App
"""
from datetime import datetime, date, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Date, ForeignKey, Enum, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import enum

from config import config

# Create engine based on environment
engine = create_engine(
    config.get_database_url(),
    echo=False,
    # SQLite specific settings
    connect_args={"check_same_thread": False} if "sqlite" in config.DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class InvoiceStatusEnum(enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"


class Client(Base):
    """Client/Customer model"""
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    address = Column(Text, nullable=False)
    company_id = Column(String(100), nullable=False)  # VAT/Tax number
    email = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    invoices = relationship("Invoice", back_populates="client")


class Invoice(Base):
    """Invoice model"""
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String(20), unique=True, nullable=False)  # XX/MM/YYYY format
    file_number = Column(Integer, unique=True, nullable=False)

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    description = Column(Text, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="EUR")

    issue_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    work_dates = Column(String(255), nullable=True)

    status = Column(String(20), default="draft")
    pdf_path = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)

    # Relationships
    client = relationship("Client", back_populates="invoices")
    email_logs = relationship("EmailLog", back_populates="invoice")


class EmailLog(Base):
    """Email send log"""
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    recipient = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    status = Column(String(50), nullable=False)  # SUCCESS, FAILED
    sent_at = Column(DateTime, default=datetime.utcnow)
    error_message = Column(Text, nullable=True)

    # Relationships
    invoice = relationship("Invoice", back_populates="email_logs")


class ConversationState(Base):
    """Store AI conversation state"""
    __tablename__ = "conversation_states"

    id = Column(String(100), primary_key=True)
    state = Column(Text, nullable=False)  # JSON string
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def init_db():
    """Create all tables"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_default_clients(db):
    """Seed default clients if they don't exist"""
    default_clients = [
        {
            "name": "Bauceram GmbH",
            "address": "Am Tonscuppen.2\n53347 Alfter",
            "company_id": "DE306313681",
            "email": "info@bauceram.de"
        },
        {
            "name": "Clinker Bau Schweiz GmbH",
            "address": "Hinterbergstrasse 26\n6312 Steinhausen",
            "company_id": "CHE-271.aborak.764",
            "email": "info@clinkerbau.ch"
        },
        {
            "name": "Stuckgeschäft Laufenberg",
            "address": "Servatiusweg 33\n53332 Bornheim",
            "company_id": "",
            "email": None
        }
    ]

    for client_data in default_clients:
        existing = db.query(Client).filter(Client.name == client_data["name"]).first()
        if not existing:
            client = Client(**client_data)
            db.add(client)

    db.commit()
