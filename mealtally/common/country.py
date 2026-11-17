# SPDX-License-Identifier: AGPL-3.0-only
"""What the restaurant's country (ISO 3166-1 alpha-2) changes: phone parsing and display, the tax-ID and
food-licence labels, and which payment methods the counter offers."""

from __future__ import annotations

import phonenumbers
from django.utils.translation import gettext_lazy as _

from .errors import ValidationFailed
from .money import current_country

EU = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
    "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
})  # fmt: skip


# --- phones: stored as E.164, shown in the restaurant country's national format ------------------------------------
def normalize_phone(raw: str, region: str | None = None) -> str:
    """Any reasonable input (``98765 43210``, ``+44 7911 123456``, ``0044 ...``) -> E.164 (``+919876543210``).

    Numbers without a country code are read as numbers of ``region`` (default: the current restaurant's country).
    """
    text = (raw or "").strip()
    if text.startswith("00"):
        text = "+" + text[2:]
    try:
        number = phonenumbers.parse(text, (region or current_country()).upper())
    except phonenumbers.NumberParseException as exc:
        raise ValidationFailed("Enter a valid phone number.", details={"field": "phone"}) from exc
    if not phonenumbers.is_possible_number(number):
        raise ValidationFailed("Enter a valid phone number.", details={"field": "phone"})
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def format_phone(e164: str, region: str | None = None) -> str:
    """National format for the restaurant's own country (``090000 30002`` in India, ``(202) 555-0123`` in the US),
    international format (``+44 7911 123456``) for everyone else. Unparseable values come back unchanged."""
    text = (e164 or "").strip()
    if not text:
        return ""
    try:
        number = phonenumbers.parse(text, (region or current_country()).upper())
    except phonenumbers.NumberParseException:
        return text
    # compare calling codes, not regions: +44 7911 belongs to Jersey/Guernsey ranges as well as the UK
    home = number.country_code == phonenumbers.country_code_for_region((region or current_country()).upper())
    style = phonenumbers.PhoneNumberFormat.NATIONAL if home else phonenumbers.PhoneNumberFormat.INTERNATIONAL
    return phonenumbers.format_number(number, style)


def mask_phone(phone: str) -> str:
    """Staff match customers on the LAST four digits, so those stay visible: ``••••• 0002``."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return f"••••• {digits[-4:]}" if len(digits) > 4 else (phone or "")  # noqa: PLR2004


# --- labels -----------------------------------------------------------------------------------------------------------
def tax_id_label(country: str | None = None):
    country = (country or current_country()).upper()
    if country == "IN":
        return _("GSTIN")
    if country in EU or country == "GB":
        return _("VAT number")
    return _("Tax ID")


def food_licence_label(country: str | None = None):
    return _("FSSAI licence number") if (country or current_country()).upper() == "IN" else _("Food business licence")


# --- payments ---------------------------------------------------------------------------------------------------------
def payment_methods(country: str | None = None) -> list[tuple[str, object]]:
    """What the counter can record: cash and bank transfer everywhere; UPI (with its QR code) only in India.
    Card and online gateways come later behind the payment adapter."""
    methods = [("CASH", _("Cash"))]
    if (country or current_country()).upper() == "IN":
        methods.append(("UPI_MANUAL", _("UPI")))
    methods.append(("BANK_TRANSFER", _("Bank transfer")))
    return methods


def upi_enabled(country: str | None = None) -> bool:
    return (country or current_country()).upper() == "IN"
