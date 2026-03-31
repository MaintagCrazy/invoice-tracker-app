"""
KSeF 2.0 Service — Submit invoices to Poland's National e-Invoice System.

Maps invoice-tracker-app data to FA(3) schema and submits via ksef2 SDK.
Token and company details come from config.py.
"""
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from config import config

logger = logging.getLogger(__name__)

# Lazy imports — ksef2 is optional, don't crash the app if missing
_ksef2_available = False
try:
    from ksef2 import Client as KsefClient, Environment, FormSchema
    from ksef2.infra.schema.fa3.models.schemat import (
        Faktura, FakturaFa, FakturaFaAdnotacje, FakturaFaAdnotacjeZwolnienie,
        FakturaFaAdnotacjeNoweSrodkiTransportu, FakturaFaAdnotacjePmarzy,
        FakturaFaFaWiersz, FakturaFaPlatnosc, FakturaFaPlatnoscTerminPlatnosci,
        FakturaPodmiot1, FakturaPodmiot2,
        Tnaglowek, TnaglowekKodFormularza, TnaglowekWariantFormularza,
        Tpodmiot1, Tpodmiot2, Tadres,
        TkodWaluty, TrodzajFaktury, TstawkaPodatku, TformaPlatnosci,
        TrachunekBankowy, FakturaPodmiot2Jst, FakturaPodmiot2Gv,
    )
    from ksef2.infra.schema.fa3.models.elementarne_typy_danych_v10_0_e import Twybor12
    from ksef2.infra.schema.fa3.models.kody_krajow_v10_0_e import TkodKraju
    from xsdata.models.datatype import XmlDate, XmlDateTime
    _ksef2_available = True
except ImportError:
    logger.warning("ksef2 SDK not installed — KSeF integration disabled")


# ── Currency mapping ─────────────────────────────────────────
CURRENCY_MAP = {
    "PLN": "PLN", "EUR": "EUR", "USD": "USD", "GBP": "GBP",
    "CHF": "CHF", "CZK": "CZK", "VND": "VND",
}

# ── Country detection from VAT ID prefix ─────────────────────
COUNTRY_FROM_VAT = {
    "DE": "DE", "AT": "AT", "FR": "FR", "NL": "NL", "BE": "BE",
    "IT": "IT", "ES": "ES", "CZ": "CZ", "SK": "SK", "HU": "HU",
    "RO": "RO", "BG": "BG", "HR": "HR", "SI": "SI", "LT": "LT",
    "LV": "LV", "EE": "EE", "FI": "FI", "SE": "SE", "DK": "DK",
    "IE": "IE", "PT": "PT", "EL": "GR", "GR": "GR", "LU": "LU",
    "MT": "MT", "CY": "CY", "PL": "PL", "CHE": "CH",
}

EU_COUNTRIES = {
    "DE", "AT", "FR", "NL", "BE", "IT", "ES", "CZ", "SK", "HU",
    "RO", "BG", "HR", "SI", "LT", "LV", "EE", "FI", "SE", "DK",
    "IE", "PT", "GR", "LU", "MT", "CY", "PL",
}


def _dec(value) -> Decimal:
    """Convert to Decimal rounded to 2 places."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _detect_country(company_id: str) -> str:
    """Detect country code from VAT/tax ID."""
    cid = (company_id or "").strip().upper()
    if cid.startswith("CHE"):
        return "CH"
    for prefix, country in COUNTRY_FROM_VAT.items():
        if cid.startswith(prefix) and len(prefix) == 2:
            return country
    return "PL"  # default


def _parse_date(date_str: str) -> tuple:
    """Parse DD.MM.YYYY or YYYY-MM-DD to (year, month, day)."""
    if not date_str:
        now = datetime.now()
        return (now.year, now.month, now.day)
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return (dt.year, dt.month, dt.day)
        except ValueError:
            continue
    now = datetime.now()
    return (now.year, now.month, now.day)


def _get_ksef_currency(currency: str) -> "TkodWaluty":
    """Map currency string to KSeF enum."""
    code = CURRENCY_MAP.get(currency.upper(), "EUR")
    return TkodWaluty(code)


def _get_tax_rate(country: str):
    """
    Determine VAT treatment based on buyer country.
    - PL domestic: 23%
    - EU (non-PL): reverse charge (np I)
    - Non-EU: export (0 EX)
    """
    if country == "PL":
        return TstawkaPodatku.VALUE_23, Decimal("0.23")
    elif country in EU_COUNTRIES:
        return TstawkaPodatku.NP_I, Decimal("0")
    else:
        return TstawkaPodatku.VALUE_0_EX, Decimal("0")


def _get_country_enum(country_code: str) -> "TkodKraju":
    """Get TkodKraju enum from 2-letter code."""
    try:
        return TkodKraju(country_code)
    except (ValueError, KeyError):
        return TkodKraju.PL


def build_faktura(invoice: dict, client: dict) -> "Faktura":
    """
    Build a KSeF FA(3) Faktura object from invoice-tracker-app data.

    Args:
        invoice: dict with keys from sheets_database (invoice_number, amount,
                 currency, issue_date, due_date, description, work_dates)
        client:  dict with keys (name, address, company_id, email)

    Returns:
        Faktura object ready for XML serialization and KSeF submission.
    """
    if not _ksef2_available:
        raise RuntimeError("ksef2 SDK not installed")

    company = config.COMPANY
    buyer_country = _detect_country(client.get("company_id", ""))
    tax_rate_enum, tax_multiplier = _get_tax_rate(buyer_country)

    amount = _dec(invoice["amount"])
    currency = invoice.get("currency", "EUR")

    # For PL domestic: amount is gross, derive net + VAT
    # For EU/export: amount is net (no VAT)
    if buyer_country == "PL":
        gross = amount
        net = (gross / Decimal("1.23")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        vat = gross - net
    else:
        net = amount
        vat = Decimal("0.00")
        gross = net

    issue_y, issue_m, issue_d = _parse_date(invoice.get("issue_date", ""))
    due_y, due_m, due_d = _parse_date(invoice.get("due_date", ""))

    now = datetime.now()

    # ── Build buyer identifier ────────────────────────────────
    buyer_vat = (client.get("company_id") or "").strip()
    buyer_id_kwargs = {}
    if buyer_country == "PL" and buyer_vat:
        # Polish NIP — strip "PL" prefix if present
        nip = buyer_vat.replace("PL", "").replace(" ", "").replace("-", "")
        buyer_id_kwargs["nip"] = nip
    elif buyer_country in EU_COUNTRIES and buyer_vat:
        buyer_id_kwargs["nr_vat_ue"] = buyer_vat
    elif buyer_vat:
        buyer_id_kwargs["nr_id"] = buyer_vat

    buyer_id_kwargs["nazwa"] = client.get("name", "")

    # ── Build buyer address ───────────────────────────────────
    buyer_addr_kwargs = {
        "kod_kraju": _get_country_enum(buyer_country),
        "adres_l1": client.get("address", "").replace("\n", ", "),
    }

    # ── Tax summary fields ────────────────────────────────────
    tax_summary = {}
    if buyer_country == "PL":
        tax_summary["p_13_1"] = net   # net at 23%
        tax_summary["p_14_1"] = vat   # VAT at 23%
    elif buyer_country in EU_COUNTRIES:
        tax_summary["p_13_6_1"] = net  # reverse charge net
    else:
        tax_summary["p_13_6_2"] = net  # export net

    # ── Adnotacje (annotations) — all "no" for standard invoices ──
    is_reverse_charge = buyer_country in EU_COUNTRIES and buyer_country != "PL"
    adnotacje = FakturaFaAdnotacje(
        p_16=Twybor12.VALUE_2,  # no self-invoicing
        p_17=Twybor12.VALUE_1 if is_reverse_charge else Twybor12.VALUE_2,
        p_18=Twybor12.VALUE_2,  # no split payment
        p_18_a=Twybor12.VALUE_2,
        zwolnienie=FakturaFaAdnotacjeZwolnienie(),
        nowe_srodki_transportu=FakturaFaAdnotacjeNoweSrodkiTransportu(),
        p_23=Twybor12.VALUE_2,  # no margin scheme
        pmarzy=FakturaFaAdnotacjePmarzy(),
    )

    # ── Build the Faktura ─────────────────────────────────────
    faktura = Faktura(
        naglowek=Tnaglowek(
            kod_formularza=TnaglowekKodFormularza(value="FA"),
            wariant_formularza=TnaglowekWariantFormularza.VALUE_3,
            data_wytworzenia_fa=XmlDateTime(
                now.year, now.month, now.day,
                now.hour, now.minute, now.second
            ),
            system_info="InvoiceTrackerApp/2.0-KSeF",
        ),
        podmiot1=FakturaPodmiot1(
            dane_identyfikacyjne=Tpodmiot1(
                nip=company["nip"],
                nazwa=company["name"],
            ),
            adres=Tadres(
                kod_kraju=TkodKraju.PL,
                adres_l1=f"{company['address']}, {company['city']}",
            ),
        ),
        podmiot2=FakturaPodmiot2(
            dane_identyfikacyjne=Tpodmiot2(**buyer_id_kwargs),
            adres=Tadres(**buyer_addr_kwargs),
            jst=FakturaPodmiot2Jst.VALUE_2,
            gv=FakturaPodmiot2Gv.VALUE_2,
        ),
        fa=FakturaFa(
            kod_waluty=_get_ksef_currency(currency),
            p_1=XmlDate(issue_y, issue_m, issue_d),
            p_2=invoice["invoice_number"],
            p_6=XmlDate(issue_y, issue_m, issue_d),
            p_15=gross,
            rodzaj_faktury=TrodzajFaktury.VAT,
            adnotacje=adnotacje,
            fa_wiersz=[
                FakturaFaFaWiersz(
                    nr_wiersza_fa=1,
                    p_7=invoice.get("description", "Services"),
                    p_8_a="us\u0142.",
                    p_8_b=Decimal("1"),
                    p_9_a=net,
                    p_11=net,
                    p_11_vat=vat,
                    p_12=tax_rate_enum,
                ),
            ],
            platnosc=FakturaFaPlatnosc(
                forma_platnosci=TformaPlatnosci.VALUE_2,
                termin_platnosci=[
                    FakturaFaPlatnoscTerminPlatnosci(
                        termin=XmlDate(due_y, due_m, due_d)
                    )
                ],
                rachunek_bankowy=[
                    TrachunekBankowy(
                        nr_rb=company["iban"].replace(" ", ""),
                        swift=company["swift"],
                        nazwa_banku=company["bank"],
                    )
                ],
            ),
            **tax_summary,
        ),
    )

    return faktura


def submit_invoice_to_ksef(invoice: dict, client: dict) -> dict:
    """
    Build FA(3) and submit to KSeF production.

    Returns:
        dict with ksef_reference_number, ksef_status, etc.
    """
    if not _ksef2_available:
        raise RuntimeError("ksef2 SDK not installed — run: pip install ksef2")

    token = config.KSEF_TOKEN
    nip = config.COMPANY["nip"]

    if not token:
        raise RuntimeError("KSEF_TOKEN not configured")

    faktura = build_faktura(invoice, client)

    # Serialize to XML bytes
    from xsdata.formats.dataclass.serializer import XmlSerializer
    from xsdata.formats.dataclass.context import XmlContext
    import io

    context = XmlContext()
    serializer = XmlSerializer(context=context)
    xml_str = serializer.render(faktura)
    xml_bytes = xml_str.encode("utf-8")

    logger.info(f"Submitting invoice {invoice['invoice_number']} to KSeF (NIP: {nip})")

    env = Environment.PRODUCTION if config.KSEF_ENVIRONMENT == "production" else Environment.TEST
    ksef_client = KsefClient(env)
    auth = ksef_client.authentication.with_token(ksef_token=token, nip=nip)

    with auth.online_session(form_code=FormSchema.FA3) as session:
        result = session.send_invoice_and_wait(invoice_xml=xml_bytes)

    ksef_number = getattr(result, "ksef_reference_number", None) or getattr(result, "reference_number", None)
    status = getattr(result, "status", "submitted")

    logger.info(f"KSeF submission complete: {ksef_number} (status: {status})")

    return {
        "ksef_reference_number": str(ksef_number) if ksef_number else None,
        "ksef_status": str(status),
        "invoice_number": invoice["invoice_number"],
        "submitted_at": datetime.now().isoformat(),
    }


def check_ksef_health() -> dict:
    """Check KSeF API connectivity and token validity."""
    if not _ksef2_available:
        return {"available": False, "error": "ksef2 SDK not installed"}

    token = config.KSEF_TOKEN
    if not token:
        return {"available": False, "error": "KSEF_TOKEN not configured"}

    try:
        env = Environment.PRODUCTION if config.KSEF_ENVIRONMENT == "production" else Environment.TEST
        ksef_client = KsefClient(env)

        # Check public endpoint
        certs = ksef_client.encryption.get_public_key_certificates()

        return {
            "available": True,
            "environment": config.KSEF_ENVIRONMENT,
            "nip": config.COMPANY["nip"],
            "certificates": len(certs) if certs else 0,
            "token_configured": True,
        }
    except Exception as e:
        return {"available": False, "error": str(e)}
