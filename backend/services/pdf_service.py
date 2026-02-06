"""
PDF generation service using WeasyPrint
"""
import os
import io
from datetime import date
from typing import Optional

from config import config

# WeasyPrint may not be available locally (system deps)
try:
    from weasyprint import HTML
    from weasyprint.text.fonts import FontConfiguration
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    HTML = None
    FontConfiguration = None


class PDFService:
    """Generate invoice PDFs"""

    def __init__(self):
        self.company = config.COMPANY
        self.font_config = FontConfiguration() if WEASYPRINT_AVAILABLE else None

    def generate_html(self, invoice_data: dict, client_data: dict) -> str:
        """Generate invoice HTML template"""
        # Format amount
        amount = float(invoice_data.get('amount', 0))
        currency = invoice_data.get('currency', 'EUR')
        formatted_amount = f"{currency} {amount:,.2f}"

        # Format dates
        issue_date = invoice_data.get('issue_date')
        due_date = invoice_data.get('due_date')

        if isinstance(issue_date, date):
            issue_date = issue_date.strftime("%d.%m.%Y")
        if isinstance(due_date, date):
            due_date = due_date.strftime("%d.%m.%Y")

        # Client address with line breaks
        client_address = client_data.get('address', '').replace('\n', '<br>')

        html_template = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Faktura</title>
    <style>
        @page {{ size: A4; margin: 20mm; }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: Arial, Helvetica, sans-serif; font-size: 11px; line-height: 1.4; color: #000; background: white; }}
        .faktura-title {{ text-align: center; font-size: 24px; font-weight: bold; margin: 30px 0; letter-spacing: 3px; }}
        .invoice-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        .invoice-table th {{ background-color: #3366AA; color: white; padding: 12px; text-align: left; font-weight: bold; border: 1px solid #3366AA; }}
        .invoice-table th.amount-header {{ text-align: center; width: 120px; }}
        .invoice-table td {{ padding: 12px; border: 1px solid #3366AA; vertical-align: top; }}
        .invoice-table td.amount {{ text-align: right; white-space: nowrap; }}
        .total-row {{ background-color: #D6E3F8; font-weight: bold; }}
        .total-row td:first-child {{ text-align: right; }}
        .empty-row td {{ height: 25px; }}
    </style>
</head>
<body>
    <div class="faktura-title">FAKTURA</div>

    <table style="width: 100%; margin-bottom: 20px;">
        <tr>
            <td style="width: 60%; vertical-align: top;">
                <strong>{self.company['name']}</strong><br>
                {self.company['address']}<br>
                {self.company['city']}<br>
                {self.company['phone']}<br>
                {self.company['email']}<br>
                NIP: {self.company['nip']}
            </td>
            <td style="width: 40%; text-align: right; vertical-align: top;">
                <strong>NR FAKTURY {invoice_data.get('invoice_number', '')}</strong>
            </td>
        </tr>
    </table>

    <table style="width: 100%; margin-bottom: 20px;">
        <tr>
            <td style="width: 50%; vertical-align: top;">
                <strong>Nabywca:</strong><br>
                {client_data.get('name', '')}<br>
                {client_address}<br>
                {client_data.get('company_id', '')}
            </td>
            <td style="width: 50%; vertical-align: top;">
                <strong>Platnosc:</strong> przelewem<br>
                <strong>Termin:</strong> {due_date}<br>
                <strong>Data Wystawienia Faktury:</strong> {issue_date}<br><br>
                {self.company['bank']}<br>
                IBAN: {self.company['iban']}<br>
                SWIFT: {self.company['swift']}
            </td>
        </tr>
    </table>

    <table class="invoice-table">
        <thead>
            <tr>
                <th>OPIS USLUGI</th>
                <th class="amount-header">SUMA</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>{invoice_data.get('description', '')}</td>
                <td class="amount">{formatted_amount}</td>
            </tr>
            <tr class="empty-row"><td></td><td></td></tr>
            <tr class="empty-row"><td></td><td></td></tr>
            <tr class="empty-row"><td></td><td></td></tr>
            <tr class="empty-row"><td></td><td></td></tr>
            <tr class="total-row">
                <td>RAZEM DO ZAPLATY</td>
                <td class="amount">{formatted_amount}</td>
            </tr>
        </tbody>
    </table>
</body>
</html>
"""
        return html_template

    def generate_pdf_bytes(self, invoice_data: dict, client_data: dict) -> bytes:
        """Generate PDF as bytes (for in-memory use)"""
        if not WEASYPRINT_AVAILABLE:
            # Return a simple HTML for preview when WeasyPrint not available
            html = self.generate_html(invoice_data, client_data)
            return html.encode('utf-8')

        html = self.generate_html(invoice_data, client_data)
        pdf_bytes = HTML(string=html).write_pdf(font_config=self.font_config)
        return pdf_bytes

    def generate_pdf_file(
        self,
        invoice_data: dict,
        client_data: dict,
        output_path: str
    ) -> str:
        """Generate PDF and save to file"""
        if not WEASYPRINT_AVAILABLE:
            raise RuntimeError("WeasyPrint not available - install with system dependencies")

        html = self.generate_html(invoice_data, client_data)

        # Ensure directory exists
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

        HTML(string=html).write_pdf(output_path, font_config=self.font_config)
        return output_path


# Singleton instance
_pdf_service: Optional[PDFService] = None


def get_pdf_service() -> PDFService:
    """Get PDF service singleton"""
    global _pdf_service
    if _pdf_service is None:
        _pdf_service = PDFService()
    return _pdf_service
