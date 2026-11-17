"""Receipt data + PDF (WeasyPrint). Same data feeds the HTML print view and the PDF."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from mealtally.common.utils import format_phone
from mealtally.tenancy.models import Tenant
from mealtally.tenancy.models import TenantSettings

from .models import Payment

# D03.9 QA-01 P2-8: what a person reads, not the internal code ("Upi Manual")
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
        "fssai": real_licence(settings_row.fssai_no),
        "customer_phone": format_phone(payment.customer.phone_e164),
        "contact_phone": _readable(settings_row.contact_phone),
    }


def render_receipt_html(payment: Payment, *, print_view: bool = False, inline_css: str | None = None) -> str:
    ctx = receipt_context(payment)
    ctx["print_view"] = print_view
    ctx["inline_css"] = inline_css
    with timezone.override(ctx["tenant"].zone):  # the receipt shows tenant-local date/time
        return render_to_string("web/receipt.html", ctx)


def render_receipt_pdf(payment: Payment) -> bytes:
    from weasyprint import HTML  # noqa: PLC0415 (heavy import, only when a PDF is requested)

    css = (Path(settings.BASE_DIR) / "mealtally" / "static" / "css" / "receipt.css").read_text()
    return HTML(string=render_receipt_html(payment, inline_css=css), base_url=None).write_pdf()
