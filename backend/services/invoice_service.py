"""
Invoice business logic service
"""
from datetime import datetime, date, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from models.database import Invoice, Client, EmailLog


class InvoiceService:
    """Invoice business logic"""

    def __init__(self, db: Session):
        self.db = db

    def get_next_file_number(self) -> int:
        """Get next available file number"""
        max_file = self.db.query(func.max(Invoice.file_number)).scalar()
        return (max_file or 0) + 1

    def get_next_invoice_number(self) -> str:
        """
        Generate invoice number: XX/MM/YYYY
        XX = sequential within current month
        """
        now = datetime.now()
        month_suffix = f"/{now.month:02d}/{now.year}"

        # Find invoices from this month
        month_invoices = self.db.query(Invoice).filter(
            Invoice.invoice_number.like(f"%{month_suffix}")
        ).all()

        # Extract sequence numbers
        seq_numbers = []
        for inv in month_invoices:
            try:
                seq = int(inv.invoice_number.split('/')[0])
                seq_numbers.append(seq)
            except (ValueError, IndexError):
                pass

        next_seq = max(seq_numbers, default=0) + 1
        return f"{next_seq:02d}/{now.month:02d}/{now.year}"

    def create_invoice(
        self,
        client_id: int,
        description: str,
        amount: float,
        currency: str = "EUR",
        issue_date: Optional[date] = None,
        due_date: Optional[date] = None,
        work_dates: Optional[str] = None
    ) -> Invoice:
        """Create a new invoice"""
        # Get next numbers
        file_number = self.get_next_file_number()
        invoice_number = self.get_next_invoice_number()

        # Default dates
        if not issue_date:
            issue_date = date.today()
        if not due_date:
            due_date = issue_date + timedelta(days=30)

        invoice = Invoice(
            invoice_number=invoice_number,
            file_number=file_number,
            client_id=client_id,
            description=description,
            amount=amount,
            currency=currency,
            issue_date=issue_date,
            due_date=due_date,
            work_dates=work_dates,
            status="draft"
        )

        self.db.add(invoice)
        self.db.commit()
        self.db.refresh(invoice)

        return invoice

    def get_invoice(self, invoice_id: int) -> Optional[Invoice]:
        """Get invoice by ID"""
        return self.db.query(Invoice).filter(Invoice.id == invoice_id).first()

    def get_invoice_by_file_number(self, file_number: int) -> Optional[Invoice]:
        """Get invoice by file number"""
        return self.db.query(Invoice).filter(Invoice.file_number == file_number).first()

    def list_invoices(
        self,
        status: Optional[str] = None,
        client_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Invoice]:
        """List invoices with optional filters"""
        query = self.db.query(Invoice)

        if status:
            query = query.filter(Invoice.status == status)
        if client_id:
            query = query.filter(Invoice.client_id == client_id)

        return query.order_by(Invoice.file_number.desc()).offset(offset).limit(limit).all()

    def update_invoice(self, invoice_id: int, **kwargs) -> Optional[Invoice]:
        """Update invoice fields"""
        invoice = self.get_invoice(invoice_id)
        if not invoice:
            return None

        for key, value in kwargs.items():
            if value is not None and hasattr(invoice, key):
                setattr(invoice, key, value)

        self.db.commit()
        self.db.refresh(invoice)
        return invoice

    def mark_as_sent(self, invoice_id: int) -> Optional[Invoice]:
        """Mark invoice as sent"""
        invoice = self.get_invoice(invoice_id)
        if invoice:
            invoice.status = "sent"
            invoice.sent_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(invoice)
        return invoice

    def mark_as_paid(self, invoice_id: int) -> Optional[Invoice]:
        """Mark invoice as paid"""
        invoice = self.get_invoice(invoice_id)
        if invoice:
            invoice.status = "paid"
            invoice.paid_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(invoice)
        return invoice

    def get_dashboard_stats(self) -> dict:
        """Get dashboard statistics"""
        total = self.db.query(Invoice).count()
        draft = self.db.query(Invoice).filter(Invoice.status == "draft").count()
        sent = self.db.query(Invoice).filter(Invoice.status == "sent").count()
        paid = self.db.query(Invoice).filter(Invoice.status == "paid").count()

        total_amount = self.db.query(func.sum(Invoice.amount)).scalar() or 0

        # Total by client
        client_totals = self.db.query(
            Client.name,
            func.sum(Invoice.amount).label('total')
        ).join(Invoice).group_by(Client.id).all()

        return {
            "total_invoices": total,
            "draft_count": draft,
            "sent_count": sent,
            "paid_count": paid,
            "total_amount": float(total_amount),
            "total_by_client": {name: float(total) for name, total in client_totals}
        }

    def log_email(
        self,
        invoice_id: int,
        recipient: str,
        subject: str,
        status: str,
        error_message: Optional[str] = None
    ):
        """Log email send attempt"""
        log = EmailLog(
            invoice_id=invoice_id,
            recipient=recipient,
            subject=subject,
            status=status,
            error_message=error_message
        )
        self.db.add(log)
        self.db.commit()


class ClientService:
    """Client business logic"""

    def __init__(self, db: Session):
        self.db = db

    def create_client(
        self,
        name: str,
        address: str,
        company_id: str,
        email: Optional[str] = None
    ) -> Client:
        """Create a new client"""
        client = Client(
            name=name,
            address=address,
            company_id=company_id,
            email=email
        )
        self.db.add(client)
        self.db.commit()
        self.db.refresh(client)
        return client

    def get_client(self, client_id: int) -> Optional[Client]:
        """Get client by ID"""
        return self.db.query(Client).filter(Client.id == client_id).first()

    def get_client_by_name(self, name: str) -> Optional[Client]:
        """Get client by name (case-insensitive partial match)"""
        return self.db.query(Client).filter(
            Client.name.ilike(f"%{name}%")
        ).first()

    def list_clients(self) -> List[Client]:
        """List all clients"""
        return self.db.query(Client).order_by(Client.name).all()

    def update_client(self, client_id: int, **kwargs) -> Optional[Client]:
        """Update client fields"""
        client = self.get_client(client_id)
        if not client:
            return None

        for key, value in kwargs.items():
            if value is not None and hasattr(client, key):
                setattr(client, key, value)

        self.db.commit()
        self.db.refresh(client)
        return client

    def delete_client(self, client_id: int) -> bool:
        """Delete client if no invoices"""
        client = self.get_client(client_id)
        if not client:
            return False

        if client.invoices:
            return False  # Can't delete client with invoices

        self.db.delete(client)
        self.db.commit()
        return True
