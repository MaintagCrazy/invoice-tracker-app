"""
Pydantic models for Invoice Tracker App
"""
from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field
from enum import Enum


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"


class ClientBase(BaseModel):
    """Base client model"""
    name: str
    address: str
    company_id: str  # VAT/Tax number
    email: Optional[str] = None


class ClientCreate(ClientBase):
    """Create client request"""
    pass


class Client(ClientBase):
    """Client with ID"""
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class InvoiceBase(BaseModel):
    """Base invoice model"""
    client_id: int
    description: str
    amount: float
    currency: str = "EUR"
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    work_dates: Optional[str] = None  # Optional work period description


class InvoiceCreate(InvoiceBase):
    """Create invoice request"""
    pass


class InvoiceUpdate(BaseModel):
    """Update invoice request"""
    description: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    work_dates: Optional[str] = None
    status: Optional[InvoiceStatus] = None


class Invoice(InvoiceBase):
    """Invoice with all fields"""
    id: int
    invoice_number: str
    file_number: int
    status: InvoiceStatus = InvoiceStatus.DRAFT
    created_at: datetime
    sent_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    pdf_path: Optional[str] = None

    class Config:
        from_attributes = True


class InvoiceWithClient(Invoice):
    """Invoice with client details"""
    client: Client


class ChatMessage(BaseModel):
    """Chat message from user"""
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[str] = Field(None, max_length=100)


class ChatResponse(BaseModel):
    """Chat response from AI"""
    response: str
    conversation_id: str
    extracted_data: Optional[dict] = None
    needs_confirmation: bool = False
    invoice_id: Optional[int] = None


class SendEmailRequest(BaseModel):
    """Request to send invoice via email. confirmed=True required."""
    additional_recipients: Optional[List[str]] = None
    custom_subject: Optional[str] = None
    custom_message: Optional[str] = None
    confirmed: bool = False


class EmailLog(BaseModel):
    """Email send log entry"""
    id: int
    invoice_id: int
    recipient: str
    subject: str
    status: str
    sent_at: datetime

    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    """Dashboard statistics"""
    total_invoices: int
    draft_count: int
    sent_count: int
    paid_count: int
    total_amount: float
    total_paid: float = 0
    total_due: float = 0
    total_by_client: dict


class PaymentStatus(str, Enum):
    UNPAID = "unpaid"
    PARTIAL = "partial"
    PAID = "paid"


class PaymentBase(BaseModel):
    """Base payment model"""
    invoice_id: int
    amount: float
    currency: str = "EUR"
    date: Optional[str] = None  # DD.MM.YYYY format, defaults to today
    method: Optional[str] = None  # e.g., "bank transfer", "cash"
    notes: Optional[str] = None


class PaymentCreate(PaymentBase):
    """Create payment request"""
    pass


class Payment(PaymentBase):
    """Payment with all fields"""
    id: int
    client: str
    created_at: str

    class Config:
        from_attributes = True


class ClientSummary(BaseModel):
    """Client summary with totals"""
    client: dict
    total_invoiced: float
    total_paid: float
    total_due: float
    invoice_count: int
    payment_count: int
    invoices: List[dict]
    payments: List[dict]
