"""Platform admin screens (platform administrators only): dashboard, tenant detail, onboarding, status changes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from decimal import InvalidOperation
from functools import wraps
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from mealtally.accounts.models import Membership
from mealtally.accounts.models import Role
from mealtally.billing import fees
from mealtally.billing import services as billing
from mealtally.billing.models import FeePolicy
from mealtally.common.errors import DomainError
from mealtally.common.utils import format_inr
from mealtally.customers.models import Customer
from mealtally.passes.models import Pass
from mealtally.reports import services as reports
from mealtally.tenancy import services as tenancy
from mealtally.tenancy.context import TenancyState
from mealtally.tenancy.context import begin
from mealtally.tenancy.context import end
from mealtally.tenancy.models import Tenant
from mealtally.tenancy.models import TenantSettings

from . import features
from .copy import friendly

TIMEZONES = ["Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Europe/London", "America/New_York", "UTC"]
STATUS_ACTIONS = {
    "suspend": Tenant.Status.SUSPENDED,
    "activate": Tenant.Status.ACTIVE,
    "deactivate": Tenant.Status.DEACTIVATED,
}


def platform_view(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect(f"{reverse('web:global-login')}?next={request.path}")
        if not (user.is_active and user.is_platform_admin):
            return render(
                request,
                "web/error.html",
                {
                    "status": 404,
                    "title": _("We couldn't find that page"),
                    "message": _("Check the link, or head back to the start."),
                },
                status=404,
            )
        token = begin(TenancyState(platform=True))
        try:
            return view(request, *args, **kwargs)
        finally:
            end(token)

    return wrapper


@platform_view
@require_GET
def dashboard(request):
    show_test = request.GET.get("show_test") == "1"
    rows = reports.platform_dashboard(include_test=show_test)
    for r in rows:
        r["fees"] = format_inr(r["fees_month_paise"])
    totals = reports.platform_totals(rows)
    totals["fees"] = format_inr(totals["fees_month_paise"])
    return render(request, "web/platform_dashboard.html", {"rows": rows, "totals": totals, "show_test": show_test})


def _tenant_or_404(slug) -> Tenant:
    tenant = Tenant.objects.filter(slug=slug).first()
    if tenant is None:
        raise Http404
    return tenant


def _month_arg(request, tenant):
    raw = request.GET.get("month", "")
    try:
        y, m = raw.split("-")
        return int(y), int(m)
    except ValueError:
        return fees.local_month(tenant)


@platform_view
@require_GET
def tenant_detail(request, slug):
    tenant = _tenant_or_404(slug)
    cfg = TenantSettings.objects.filter(tenant=tenant).first()
    owner = Membership.objects.filter(tenant=tenant, role=Role.OWNER).select_related("user").first()
    year, month = _month_arg(request, tenant)
    statement = fees.fee_month(tenant, year, month)
    ctx = {
        "t": tenant,
        "name": (cfg.display_name if cfg and cfg.display_name else tenant.name),
        "owner": owner.user if owner else None,
        "customers": Customer.objects.filter(tenant=tenant).count(),
        "active_passes": Pass.objects.filter(tenant=tenant, status=Pass.Status.ACTIVE).count(),
        "policies": FeePolicy.objects.filter(tenant=tenant).order_by("-effective_from", "-id")[:10],
        "statement": statement,
        "month": statement["month"],
        "total": format_inr(statement["total_paise"]),
        "platform_fee": format_inr(statement["platform_fee_paise"]),
        "gateway_fee": format_inr(statement["gateway_fee_paise"]),
        "gross": format_inr(statement["gross_paise"]),
        "lines": [
            {
                **ln,
                "base": format_inr(ln["base_paise"]),
                "fee": format_inr(ln["fee_paise"]),
                "reversed": format_inr(ln["reversed_paise"]),
                "net": format_inr(ln["net_paise"]),
                "date_short": ln["date"][:10],
            }
            for ln in statement["lines"]
        ],
        "notice": request.GET.get("notice", ""),
    }
    return render(request, "web/platform_tenant.html", ctx)


@platform_view
@require_GET
@features.requires(features.fees)
def tenant_fees_export(request, slug):
    """Per-tenant monthly fee statement for the platform invoice (CSV or PDF). Contains NO customer data."""
    tenant = _tenant_or_404(slug)
    year, month = _month_arg(request, tenant)
    m = fees.fee_month(tenant, year, month)
    header = [_("Receipt"), _("Date"), _("Status"), _("Base"), _("%"), _("Fee"), _("Reversed (void)"), _("Net")]
    rows = [
        [
            ln["receipt_number"],
            ln["date"][:10],
            ln["status"],
            format_inr(ln["base_paise"]),
            f"{ln['platform_pct']}%",
            format_inr(ln["fee_paise"]),
            format_inr(ln["reversed_paise"]),
            format_inr(ln["net_paise"]),
        ]
        for ln in m["lines"]
    ]
    rows.append([_("TOTAL"), "", "", "", "", "", "", format_inr(m["total_paise"])])
    fmt = request.GET.get("format", "csv")
    name = f"fee-statement-{tenant.slug}-{m['month']}"
    if fmt == "pdf":
        from weasyprint import HTML  # noqa: PLC0415

        extra = [
            (_("Gross payments"), format_inr(m["gross_paise"])),
            (_("Platform fee"), format_inr(m["platform_fee_paise"])),
            (_("Gateway fee"), format_inr(m["gateway_fee_paise"])),
            (_("Net payable to platform"), format_inr(m["total_paise"])),
        ]
        html = render_to_string(
            "web/report_pdf.html",
            {
                "title": f"{_('Platform fee statement')} {m['month']}",
                "header": header,
                "rows": rows,
                "extra": extra,
                "tenant": tenant,
            },
        )
        resp = HttpResponse(HTML(string=html).write_pdf(), content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{name}.pdf"'
        return resp
    resp = HttpResponse(reports.to_csv(header, rows), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{name}.csv"'
    return resp


@platform_view
@require_POST
@features.requires(features.fees)
def tenant_fee_policy(request, slug):
    tenant = _tenant_or_404(slug)
    d = request.POST
    try:
        effective = (
            datetime.fromisoformat(d["effective_from"]).replace(tzinfo=tenant.zone) if d.get("effective_from") else None
        )
        billing.set_fee_policy(
            tenant=tenant,
            platform_pct=Decimal(d.get("platform_pct", "")),
            gateway_pct=Decimal(d.get("gateway_pct", "")),
            effective_from=effective,
            actor=request.user,
        )
        notice = _("Fee policy saved.")
    except (DomainError, InvalidOperation, ValueError, ValidationError) as exc:
        notice = friendly(exc) if isinstance(exc, DomainError) else _("Check the percentages (0-100) and the date.")
    return redirect(f"{reverse('web:platform-tenant', args=[slug])}?notice={quote(str(notice))}")


@platform_view
@require_POST
def tenant_flags(request, slug):
    """D03: platform-admin-only toggles for the preview modules (badge visibility, demo dataset)."""
    from mealtally.audit import services as audit  # noqa: PLC0415
    from mealtally.tenancy.context import platform_context  # noqa: PLC0415

    tenant = _tenant_or_404(slug)
    badges, dataset = request.POST.get("show_preview_badges") == "on", request.POST.get("has_demo_dataset") == "on"
    with platform_context(), transaction.atomic():
        before = {"show_preview_badges": tenant.show_preview_badges, "has_demo_dataset": tenant.has_demo_dataset}
        Tenant.objects.filter(pk=tenant.pk).update(show_preview_badges=badges, has_demo_dataset=dataset)
        audit.record(
            action="tenant.preview_flags",
            tenant_id=tenant.id,
            actor=request.user,
            object_type="tenant",
            object_public_id=tenant.public_id,
            before=before,
            after={"show_preview_badges": badges, "has_demo_dataset": dataset},
        )
    return redirect(f"{reverse('web:platform-tenant', args=[slug])}?notice={quote(str(_('Preview settings saved.')))}")


@platform_view
@require_http_methods(["GET", "POST"])
def tenant_status(request, slug, action):
    """Suspend / activate / deactivate: always a confirm step with a mandatory reason, written to the audit log."""
    new_status = STATUS_ACTIONS.get(action)
    if new_status is None:
        raise Http404
    tenant = _tenant_or_404(slug)
    ctx = {"t": tenant, "action": action, "new_status": new_status}
    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        if not reason:
            return render(
                request, "web/platform_confirm.html", {**ctx, "error": _("A reason is required.")}, status=400
            )
        tenancy.set_status(tenant=tenant, status=new_status, actor=request.user, reason=reason)
        return redirect("web:platform-dashboard")
    return render(request, "web/platform_confirm.html", ctx)


@platform_view
@require_http_methods(["GET", "POST"])
@features.requires(features.multi)
def onboard(request):
    ctx = {"timezones": TIMEZONES}
    if request.method == "POST":
        d = request.POST
        try:
            with transaction.atomic():
                tenant, owner, password = tenancy.onboard_tenant(
                    actor_user=request.user,
                    name=d.get("name", "").strip(),
                    slug=d.get("slug", "").strip().lower(),
                    timezone_name=d.get("timezone", "Asia/Kolkata"),
                    owner_name=d.get("owner_name", ""),
                    owner_email=d.get("owner_email", "").strip() or None,
                    owner_phone=d.get("owner_phone", "").strip() or None,
                    is_test=d.get("is_test") == "on",
                )
            return render(
                request, "web/platform_onboarded.html", {"tenant": tenant, "owner": owner, "password": password}
            )
        except DomainError as exc:
            ctx.update(error=friendly(exc), form=d)
        except ValidationError as exc:
            ctx.update(error=" ".join(exc.messages), form=d)
    return render(request, "web/platform_onboard.html", ctx)
