"""
PDF generation service using WeasyPrint
"""
import os
import io
import base64
import logging
from datetime import date
from typing import Optional

from config import config

logger = logging.getLogger(__name__)

# WeasyPrint may not be available locally (system deps)
try:
    from weasyprint import HTML
    from weasyprint.text.fonts import FontConfiguration
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    HTML = None
    FontConfiguration = None


def ksef_qr_url(nip: str, issue_date: str, invoice_hash: str, environment: str = "production") -> str:
    """KOD I link: https://<qr host>/invoice/<seller NIP>/<DD-MM-YYYY of P_1>/<base64url SHA-256 of the XML>."""
    from services.ksef_service import parse_issue_date
    d = parse_issue_date(issue_date)
    if not d:
        raise ValueError(f"Cannot build the KSeF QR: issue date {issue_date!r} is not a valid date")
    host = "qr.ksef.mf.gov.pl" if environment == "production" else "qr-test.ksef.mf.gov.pl"
    return f"https://{host}/invoice/{nip}/{d:%d-%m-%Y}/{invoice_hash}"


def _ksef_block(company: dict, invoice_data: dict, issue_date: str) -> str:
    """Green KSeF box: QR (KOD I) with the KSeF number printed under it. Empty unless filed AND hash known."""
    number = invoice_data.get('ksef_reference') or ''
    inv_hash = invoice_data.get('ksef_hash') or ''
    if not number:
        return ''
    if not inv_hash:  # filed, but QR cannot be built yet: still print the KSeF number
        return (
            '<table style="width:100%;margin-top:24px;border:1px solid #008000;background:#f0fff0;"><tr>'
            '<td style="padding:8px;"><strong style="color:#006400;">KSeF - Krajowy System e-Faktur</strong><br>'
            f'Numer KSeF: {number}</td></tr></table>'
        )
    import qrcode
    try:
        url = ksef_qr_url(company['nip'], issue_date, inv_hash, config.KSEF_ENVIRONMENT)
    except ValueError as e:
        logger.error(str(e))
        return ''

    buf = io.BytesIO()
    qrcode.make(url, box_size=4, border=1).save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode()
    return (
        '<table style="width:100%;margin-top:24px;border:1px solid #008000;background:#f0fff0;"><tr>'
        '<td style="padding:8px;vertical-align:top;"><strong style="color:#006400;">KSeF - Krajowy System e-Faktur</strong><br>'
        f'Numer KSeF: {number}</td>'
        f'<td style="padding:8px;width:230px;text-align:center;"><img src="data:image/png;base64,{b64}" style="width:90px;height:90px;"><br>'
        f'<span style="font-size:7px;white-space:nowrap;">{number}</span></td></tr></table>'
    )


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

        ksef_block = _ksef_block(self.company, invoice_data, issue_date or '')

        # Client address with line breaks
        client_address = client_data.get('address', '').replace('\n', '<br>')

        title = "FAKTURA"
        number_label = f"NR FAKTURY {invoice_data.get('invoice_number', '')}"
        correction_block = ""
        line_rows = (
            f"""<tr>
                <td>{invoice_data.get('description', '')}</td>
                <td class="amount">{formatted_amount}</td>
            </tr>""" + '\n            <tr class="empty-row"><td></td><td></td></tr>' * 4)
        total_rows = f"""<tr class="total-row">
                <td>RAZEM DO ZAPLATY</td>
                <td class="amount">{formatted_amount}</td>
            </tr>"""

        corr = invoice_data.get('correction')
        if corr:
            # Faktura korygująca: the original it corrects, the line before and after, the
            # difference (= this document's own total, P_15) and the invoice's new value.
            from html import escape
            # a broken link (correction["error"]) prints dashes, never invented zeros
            money = lambda v: "-" if v in (None, "") else f"{currency} {float(v):,.2f}"
            desc = escape(str(invoice_data.get('description', '')))
            title = "FAKTURA KORYGUJACA"
            number_label = f"NR FAKTURY KORYGUJACEJ {escape(str(invoice_data.get('invoice_number', '')))}"
            reason = escape(str(corr.get('reason') or ''))
            error_html = ""
            if corr.get('error'):
                error_html = '<br><strong style="color:#B00020;">BLAD: ' + escape(str(corr['error'])) + '</strong>'
            correction_block = f"""
    <table style="width: 100%; margin-bottom: 20px; border: 1px solid #3366AA; background: #F3F7FD;">
        <tr>
            <td style="padding: 8px; vertical-align: top;">
                <strong>Dotyczy faktury nr:</strong> {escape(str(corr.get('original_invoice_number', '')))}
                &nbsp;&nbsp;<strong>z dnia:</strong> {escape(str(corr.get('original_issue_date', '')))}<br>
                <strong>Numer KSeF faktury korygowanej:</strong> {escape(str(corr.get('original_ksef_reference', '')))}<br>
                <strong>Przyczyna korekty:</strong> {reason}
                {error_html}
            </td>
        </tr>
    </table>"""
            line_rows = (
                f"""<tr>
                <td>Stan przed korekta: {desc}</td>
                <td class="amount">{money(corr.get('amount_before'))}</td>
            </tr>
            <tr>
                <td>Stan po korekcie: {desc}</td>
                <td class="amount">{money(corr.get('amount_after'))}</td>
            </tr>""" + '\n            <tr class="empty-row"><td></td><td></td></tr>' * 2)
            total_rows = f"""<tr class="total-row">
                <td>KWOTA KOREKTY (ROZNICA)</td>
                <td class="amount">{money(amount)}</td>
            </tr>
            <tr class="total-row">
                <td>RAZEM PO KOREKCIE</td>
                <td class="amount">{money(corr.get('amount_after'))}</td>
            </tr>"""

        html_template = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Faktura</title>
    <style>
        @page {{ size: A4; margin: 20mm; }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Liberation Sans', Arial, Helvetica, sans-serif; font-size: 11px; line-height: 1.4; color: #000; background: white; }}
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
    <div class="faktura-title">{title}</div>

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
                <strong>{number_label}</strong>
            </td>
        </tr>
    </table>
{correction_block}

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
            {line_rows}
            {total_rows}
        </tbody>
    </table>
    {ksef_block}
</body>
</html>
"""
        return html_template

    def generate_pdf_bytes(self, invoice_data: dict, client_data: dict) -> bytes:
        """Generate PDF as bytes (for in-memory use)"""
        if not WEASYPRINT_AVAILABLE:
            raise RuntimeError("WeasyPrint not available — cannot generate PDF")

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
