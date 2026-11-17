# SPDX-License-Identifier: AGPL-3.0-only
"""Receipt data + PDF (WeasyPrint). Same data feeds the HTML print view and the PDF."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from mealtally.common import country
from mealtally.common import money
from mealtally.common.country import format_phone
from mealtally.tenancy.models import Tenant
from mealtally.tenancy.models import TenantSettings

from .models import Payment

# what a person reads, not the internal code ("Upi Manual")
METHOD_LABELS = {
    "CASH": "Cash",
    "UPI_MANUAL": "UPI",
    "CARD_MANUAL": "Card",
    "BANK_TRANSFER": "Bank transfer",
    "GATEWAY": "Online payment",
}


def method_label(method: str) -> str:
    return METHOD_LABELS.get(method, method.replace("_", " ").title())


def _readable(phone: str) -> str:
    return format_phone(phone) if (phone or "").startswith("+") else phone


def real_licence(value: str) -> str:
    """'' for a blank or placeholder licence number (all zeros), so the receipt never prints 'FSSAI 00000000000000'."""
    value = (value or "").strip()
    return "" if not value or set(value) <= {"0", " ", "-"} else value


def receipt_context(payment: Payment) -> dict:
    tenant = Tenant.objects.get(pk=payment.tenant_id)
    settings_row = TenantSettings.objects.get(tenant_id=payment.tenant_id)
    pass_ = getattr(payment, "pass_record", None)
    zone = tenant.zone
    return {
        "tenant": tenant,
        "cfg": settings_row,
        "business_name": settings_row.display_name or tenant.name,
        "payment": payment,
        "customer": payment.customer,
        "pass_": pass_,
        "received_at": payment.received_at.astimezone(zone),
        "starts_at": pass_.starts_at.astimezone(zone) if pass_ else None,
        "ends_at": pass_.ends_at.astimezone(zone) if pass_ else None,
        "voided": payment.status == Payment.Status.VOIDED,
        "method_label": method_label(payment.method),
        "licence": real_licence(settings_row.food_licence_no),
        "licence_label": country.food_licence_label(tenant.country),
        "tax_label": country.tax_id_label(tenant.country),
        "currency": tenant.currency,
        "customer_phone": format_phone(payment.customer.phone_e164),
        "contact_phone": _readable(settings_row.contact_phone),
    }


def render_receipt_html(payment: Payment, *, print_view: bool = False, inline_css: str | None = None) -> str:
    ctx = receipt_context(payment)
    ctx["print_view"] = print_view
    ctx["inline_css"] = inline_css
    token = money.use(ctx["tenant"].currency, ctx["tenant"].country)  # works outside a request too (emails, PDFs)
    try:
        with timezone.override(ctx["tenant"].zone):  # the receipt shows tenant-local date/time
            return render_to_string("web/receipt.html", ctx)
    finally:
        money.reset(token)


def render_receipt_pdf(payment: Payment) -> bytes:
    from weasyprint import HTML  # noqa: PLC0415 (heavy import, only when a PDF is requested)

    css = (Path(settings.BASE_DIR) / "mealtally" / "static" / "css" / "receipt.css").read_text()
    return HTML(string=render_receipt_html(payment, inline_css=css), base_url=None).write_pdf()
