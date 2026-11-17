"""Owner / manager admin UI: dashboard, customers, plans, staff, settings, reports, audit."""

from __future__ import annotations

import json
import uuid
from datetime import date
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from mealtally.accounts import services as accounts
from mealtally.accounts.models import Role
from mealtally.billing import services as billing
from mealtally.common.errors import DomainError
from mealtally.common.utils import format_inr
from mealtally.common.utils import local_date
from mealtally.customers import services as customers
from mealtally.ledger import services as ledger
from mealtally.passes import services as passes
from mealtally.plans import services as plans
from mealtally.plans.models import MealSlot
from mealtally.plans.models import Plan
from mealtally.reports import services as reports
from mealtally.tenancy import services as tenancy
from mealtally.tenancy.models import Tenant

from .access import home_url
from .access import tenant_view
from .copy import friendly
from .labels import ENTRY_LABELS
from .labels import SOURCE_LABELS
from .labels import actor_label

ADMIN = {"roles": (Role.OWNER, Role.MANAGER)}
OWNER = {"roles": (Role.OWNER,)}


rupees = format_inr  # one formatter for screens, CSV and PDF (ADR 0015)


# --- staff password (forced first-login change, also voluntary) --------------------------------------
@tenant_view(allow_forced=True, roles=(Role.OWNER, Role.MANAGER, Role.STAFF, Role.CHEF, Role.DRIVER))
@require_http_methods(["GET", "POST"])
def staff_password(request):
    ctx = {"forced": request.user.must_change_password}
    if request.method == "POST":
        new, confirm = request.POST.get("new_password", ""), request.POST.get("confirm_password", "")
        try:
            if new != confirm:
                raise DomainError(_("The two passwords do not match."))
            accounts.change_password(
                user=request.user, old_password=request.POST.get("old_password", ""), new_password=new
            )
        except DomainError as exc:
            return render(request, "web/staff_password.html", {**ctx, "err": friendly(exc)}, status=400)
        update_session_auth_hash(request, request.user)
        return redirect(home_url(request.tenant.slug, request.role, demo=request.tenant.has_demo_dataset))
    return render(request, "web/staff_password.html", ctx)


@tenant_view(**ADMIN)
@require_GET
def more(request):
    """Mobile 'More' tab: the secondary admin pages."""
    return render(request, "web/admin_more.html")


# --- dashboard ----------------------------------------------------------------------------------------
@tenant_view(**ADMIN)
@require_GET
def dashboard(request):
    d = reports.dashboard(actor=request.actor)
    return render(
        request,
        "web/admin_dashboard.html",
        {"d": d, "revenue": rupees(d["revenue_month_paise"]), "fee": rupees(d["platform_fee_month_paise"])},
    )


# --- customers ------------------------------------------------------------------------------------------
@tenant_view(**ADMIN)
@require_GET
def customer_list(request):
    rows = customers.list_customers(query=request.GET.get("q", ""), status=request.GET.get("status", ""))
    filters = [
        ("", _("All")),
        ("active_pass", _("With active pass")),
        ("no_pass", _("No active pass")),
        ("expiring", _("Expiring in 3 days")),
        ("blocked", _("Blocked")),
    ]
    ctx = {"rows": rows, "q": request.GET.get("q", ""), "status": request.GET.get("status", ""), "filters": filters}
    return render(
        request, "web/_customer_rows.html" if request.headers.get("HX-Request") else "web/admin_customers.html", ctx
    )


def _detail_ctx(request, customer, **extra):
    tz = request.tenant.zone
    all_passes = list(passes.passes_for_customer(customer.id))
    order = {"ACTIVE": 0, "SUSPENDED": 1, "QUEUED": 2}
    ordered = sorted(all_passes, key=lambda p: (order.get(p.status, 3), -p.starts_at.timestamp()))
    by_payment = {p.payment_id: p for p in all_passes}
    pays = list(billing.payments_for_customer(customer.id))
    for pay in pays:
        pass_ = by_payment.get(pay.id)
        pay.can_void, pay.void_reason_text = False, ""
        if pay.status == "RECORDED" and pass_ is not None:
            if ledger.pass_has_redemptions(pass_):
                pay.void_reason_text = _("Meals already redeemed — use Adjust credits")
            elif pass_.status not in ("ACTIVE", "QUEUED", "SUSPENDED"):
                pay.void_reason_text = _("This pass has already ended")
            else:
                pay.can_void = True
    entries = list(ledger.entries_for_customer(customer.id).select_related("operator")[:40])
    multi = len(all_passes) > 1
    ledger_rows = [
        {
            "e": e,
            "label": ENTRY_LABELS.get(e.entry_type, e.entry_type),
            "source": SOURCE_LABELS.get(e.source, e.source),
            "by": actor_label(e.operator) if e.operator_id else _("System"),
            "pass": f"{e.pass_ref.plan_name} · {e.pass_ref.starts_at.astimezone(tz):%-d %b}" if multi else "",
        }
        for e in entries
    ]
    return {
        "customer": customer,
        "tz": tz,
        "passes": ordered,
        "payments": pays,
        "ledger": ledger_rows,
        "multi_pass": multi,
        "idem": str(uuid.uuid4()),
        "pass_actions": [("suspend", _("Suspend")), ("resume", _("Resume")), ("cancel", _("Cancel pass"))],
        "is_owner": request.role == Role.OWNER,
        **extra,
    }


@tenant_view(**ADMIN)
@require_GET
def customer_detail(request, customer_id):
    try:
        customer = customers.get_customer(customer_id)
    except DomainError as exc:
        raise Http404 from exc
    return render(request, "web/admin_customer.html", _detail_ctx(request, customer))


@tenant_view(**ADMIN)
@require_POST
def customer_action(request, customer_id, action):
    """One endpoint for every per-customer action; each one asks for a reason where the service needs one."""
    d = request.POST
    try:
        customer = customers.get_customer(customer_id)
        reason = d.get("reason", "")
        notice, secret = None, None
        with transaction.atomic():
            if action == "edit":
                customers.update_customer(
                    actor=request.actor,
                    customer=customer,
                    full_name=d.get("full_name", ""),
                    notes=d.get("notes", ""),
                    address=d.get("address", ""),
                )
                notice = _("Saved.")
            elif action in ("block", "unblock"):
                customers.set_status(
                    actor=request.actor,
                    customer=customer,
                    status="BLOCKED" if action == "block" else "ACTIVE",
                    reason=reason,
                )
                notice = _("Customer blocked.") if action == "block" else _("Customer unblocked.")
            elif action == "reset-pin":
                secret = customers.reset_pin(
                    actor=request.actor, customer=customer, pin=d.get("pin") if d.get("pin_choice") == "own" else None
                )
                notice = _("New PIN set. The customer must change it at next login.")
            elif action == "adjust":
                ledger.adjust(
                    actor=request.actor,
                    pass_public_id=d.get("pass", ""),
                    quantity=int(d.get("quantity", "0") or 0),
                    reason=reason,
                    idempotency_key=d.get("idempotency_key", ""),
                )
                notice = _("Credits adjusted.")
            elif action in ("suspend", "resume", "cancel"):
                fn = {"suspend": passes.suspend_pass, "resume": passes.resume_pass, "cancel": passes.cancel_pass}[
                    action
                ]
                fn(actor=request.actor, pass_public_id=d.get("pass", ""), reason=reason)
                notice = _("Pass updated.")
            elif action == "void":
                billing.void_payment(actor=request.actor, payment_public_id=d.get("payment", ""), reason=reason)
                notice = _("Payment voided.")
            else:
                raise Http404
    except DomainError as exc:
        return render(
            request,
            "web/admin_customer.html",
            _detail_ctx(request, customers.get_customer(customer_id), error=friendly(exc)),
            status=400,
        )
    except ValueError:
        return render(
            request,
            "web/admin_customer.html",
            _detail_ctx(request, customers.get_customer(customer_id), error=_("Enter a whole number.")),
            status=400,
        )
    customer = customers.get_customer(customer_id)
    return render(request, "web/admin_customer.html", _detail_ctx(request, customer, notice=notice, secret_pin=secret))


# --- plans ------------------------------------------------------------------------------------------------
def _plan_data(d) -> dict:
    cap = d.get("max_meals_per_day", "").strip()
    try:
        slot_ids = [int(x) for x in d.getlist("allowed_slots")]
        return {
            "allowed_slots": slot_ids,
            "max_meals_per_slot": int(d.get("max_meals_per_slot", "1") or 1),
            "name": d.get("name", ""),
            "price_paise": int(Decimal(d.get("price_rupees", "0") or 0) * 100),
            "meals_per_cycle": int(d.get("meals_per_cycle", "0") or 0),
            "validity_mode": d.get("validity_mode", "ROLLING_DAYS"),
            "validity_days": int(d.get("validity_days", "30") or 30),
            "max_meals_per_day": int(cap) if cap else None,
            "is_active": d.get("is_active") == "on",
        }
    except (ValueError, ArithmeticError) as exc:
        raise DomainError(_("Check the numbers: whole numbers only (price may have paise).")) from exc


@tenant_view(**ADMIN)
@require_GET
def plan_list(request):
    rows = [
        {"p": p, "rule": plans.rule_summary(p)}
        for p in plans.list_plans(active_only=False).prefetch_related("allowed_slots")
    ]
    return render(request, "web/admin_plans.html", {"rows": rows})


@tenant_view(**ADMIN)
@require_http_methods(["GET", "POST"])
def plan_form(request, plan_id=None):
    plan = plans.get_plan(plan_id) if plan_id else None
    if plan:
        v = {
            "name": plan.name,
            "price_rupees": f"{plan.price_paise / 100:.2f}",
            "meals_per_cycle": plan.meals_per_cycle,
            "validity_mode": plan.validity_mode,
            "validity_days": plan.validity_days,
            "max_meals_per_day": plan.max_meals_per_day if plan.max_meals_per_day is not None else "",
            "max_meals_per_slot": plan.max_meals_per_slot,
            "allowed_slots": set(plan.allowed_slots.values_list("id", flat=True)),
            "is_active": plan.is_active,
        }
    else:
        v = {
            "name": "",
            "price_rupees": "1500",
            "meals_per_cycle": 30,
            "validity_mode": "ROLLING_DAYS",
            "validity_days": 30,
            "max_meals_per_day": "",
            "max_meals_per_slot": 1,
            "allowed_slots": set(),
            "is_active": True,
        }
    ctx = {
        "plan": plan,
        "modes": Plan.ValidityMode.choices,
        "v": v,
        "slots": list(MealSlot.objects.filter(is_active=True)),
        "summary": plans.rule_summary(plan) if plan else "",
    }
    if request.method == "POST":
        d = request.POST
        v = {
            **v,
            "name": d.get("name", ""),
            "price_rupees": d.get("price_rupees", ""),
            "meals_per_cycle": d.get("meals_per_cycle", ""),
            "validity_mode": d.get("validity_mode", ""),
            "validity_days": d.get("validity_days", ""),
            "max_meals_per_day": d.get("max_meals_per_day", ""),
            "max_meals_per_slot": d.get("max_meals_per_slot", "1"),
            "allowed_slots": {int(x) for x in d.getlist("allowed_slots") if x.isdigit()},
            "is_active": d.get("is_active") == "on",
        }
        try:
            plans.save_plan(actor=request.actor, plan=plan, **_plan_data(d))
        except DomainError as exc:
            return render(request, "web/admin_plan_form.html", {**ctx, "v": v, "error": friendly(exc)}, status=400)
        return redirect("web:admin-plans", slug=request.tenant.slug)
    return render(request, "web/admin_plan_form.html", ctx)


# --- D03.9: meal times (OWNER) ---------------------------------------------------------------------------------
def _parse_hhmm(raw: str):
    from datetime import datetime as _dt  # noqa: PLC0415

    try:
        return _dt.strptime((raw or "").strip(), "%H:%M").time()  # noqa: DTZ007
    except ValueError as exc:
        raise DomainError(_("Enter times as HH:MM, for example 12:30.")) from exc


@tenant_view(**OWNER)
@require_http_methods(["GET", "POST"])
def meal_times(request):
    """Business profile -> Meal times: the windows the plans' meal-time rules use (tenant-local)."""
    ctx = {}
    if request.method == "POST":
        d = request.POST
        slot = MealSlot.objects.filter(public_id=d.get("slot")).first() if d.get("slot") else None
        try:
            with transaction.atomic():
                plans.save_meal_slot(
                    actor=request.actor,
                    slot=slot,
                    name=d.get("name", ""),
                    name_hi=d.get("name_hi", "").strip()[:60],
                    start_time=_parse_hhmm(d.get("start_time", "")),
                    end_time=_parse_hhmm(d.get("end_time", "")),
                    grace_minutes=int(d.get("grace_minutes") or 0),
                    is_active=d.get("is_active") == "on",
                    **({} if slot else {"sort_order": MealSlot.objects.count() + 1}),
                )
            ctx["notice"] = _("Meal time saved.")
        except (DomainError, ValueError) as exc:
            ctx["error"] = friendly(exc) if isinstance(exc, DomainError) else _("Enter whole minutes for grace.")
            ctx["form"] = d
    ctx["slots"] = list(MealSlot.objects.all())
    return render(request, "web/admin_meal_times.html", ctx)


@tenant_view(**OWNER)
@require_POST
def meal_rules_banner(request):
    """Dismiss the one-time 'Set meal times and daily limits' banner (audited like any settings change)."""
    tenancy.update_settings(actor=request.actor, meal_rules_banner_dismissed=True)
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith(f"/t/{request.tenant.slug}/") else home_url(request.tenant.slug, "OWNER"))


@tenant_view(**ADMIN)
@require_POST
def driver_assign(request):
    """QA-01 P1-4: assign a delivery route to a driver (real data: the driver's console shows that route).

    Routes are the drivers' own ``Membership.route_name``; assigning a route that another driver has swaps the two.
    """
    from mealtally.accounts.models import Membership  # noqa: PLC0415
    from mealtally.audit import services as audit  # noqa: PLC0415

    route = request.POST.get("route", "").strip()[:60]
    member = Membership.objects.filter(pk=request.POST.get("driver") or 0, role=Role.DRIVER, is_active=True).first()
    if not route or member is None:
        raise Http404
    with transaction.atomic():
        previous = Membership.objects.filter(role=Role.DRIVER, route_name=route).exclude(pk=member.pk).first()
        if previous is not None:  # swap routes (and vehicles) with the driver who had it
            previous.route_name, previous.vehicle, member.vehicle = member.route_name, member.vehicle, previous.vehicle
            previous.save(update_fields=["route_name", "vehicle", "updated_at"])
        before = member.route_name
        member.route_name = route
        member.save(update_fields=["route_name", "vehicle", "updated_at"])
        audit.record(
            action="driver.route_assign",
            tenant_id=request.tenant.id,
            actor=request.user,
            object_type="membership",
            object_public_id=member.public_id,
            before={"route": before},
            after={"route": route, "driver": member.user.name or member.user.get_username()},
        )
    from django.urls import reverse  # noqa: PLC0415

    return redirect(reverse("preview:delivery", args=[request.tenant.slug]) + "?saved=1")


# --- staff (OWNER) -----------------------------------------------------------------------------------------
@tenant_view(**OWNER)
@require_http_methods(["GET", "POST"])
def staff_list(request):
    ctx = {}
    if request.method == "POST":
        d = request.POST
        try:
            with transaction.atomic():
                user, password = accounts.add_staff_member(
                    actor=request.actor,
                    name=d.get("name", ""),
                    email=d.get("email", "").strip() or None,
                    phone=d.get("phone", "").strip() or None,
                    role=d.get("role", ""),
                )
            ctx.update(new_login=user.get_username(), new_password=password)
        except DomainError as exc:
            ctx.update(error=friendly(exc), form=d)
    return render(request, "web/admin_staff.html", {**ctx, "members": accounts.list_staff(request.tenant.id)})


@tenant_view(**OWNER)
@require_POST
def staff_action(request, user_id, action):
    ctx = {}
    try:
        with transaction.atomic():
            if action in ("deactivate", "activate"):
                accounts.set_staff_active(actor=request.actor, user_id=user_id, active=action == "activate")
            elif action == "reset-password":
                user, password = accounts.reset_staff_password(actor=request.actor, user_id=user_id)
                ctx.update(new_login=user.get_username(), new_password=password)
            else:
                raise Http404
    except DomainError as exc:
        ctx.update(error=friendly(exc))
    return render(request, "web/admin_staff.html", {**ctx, "members": accounts.list_staff(request.tenant.id)})


# --- settings (OWNER) ----------------------------------------------------------------------------------------
@tenant_view(**OWNER)
@require_http_methods(["GET", "POST"])
def settings_view(request):
    ctx = {"timezones": ["Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Europe/London", "America/New_York", "UTC"]}
    if request.method == "POST":
        d = request.POST
        try:
            tenancy.update_settings(
                actor=request.actor,
                timezone_name=d.get("timezone") or None,
                display_name=d.get("display_name", ""),
                address=d.get("address", ""),
                contact_phone=d.get("contact_phone", ""),
                brand_color=d.get("brand_color", ""),
                receipt_footer=d.get("receipt_footer", ""),
                gstin=d.get("gstin", "").strip(),
                fssai_no=d.get("fssai_no", "").strip(),
                tagline=d.get("tagline", "").strip()[:120],
                redeem_cooldown_seconds=int(d.get("redeem_cooldown_seconds") or 0),
                staff_reversal_window_hours=int(d.get("staff_reversal_window_hours") or 0),
                counter_can_reverse_others=d.get("counter_can_reverse_others") == "on",
                topup_min_paise=int(d.get("topup_min_rupees") or 100) * 100,
                topup_max_paise=int(d.get("topup_max_rupees") or 50000) * 100,
                max_queued_passes=int(d.get("max_queued_passes") or 0),
                allow_self_signup=d.get("allow_self_signup") == "on",
            )
            request.cfg = tenancy.get_settings(request.tenant.id)
            request.tenant = Tenant.objects.get(pk=request.tenant.id)
            ctx["notice"] = _("Settings saved.")
        except (DomainError, ValueError) as exc:
            ctx["error"] = friendly(exc) if isinstance(exc, DomainError) else _("Enter whole numbers.")
    from . import themes  # noqa: PLC0415

    choices = [(key, label, desc) for key, (label, desc) in themes.THEMES.items()]
    return render(
        request,
        "web/admin_settings.html",
        {
            **ctx,
            "cfg": request.cfg,
            "theme_choices": choices,
            "topup_min_rupees": request.cfg.topup_min_paise // 100,
            "topup_max_rupees": request.cfg.topup_max_paise // 100,
        },
    )


@tenant_view(**OWNER)
@require_http_methods(["POST"])
def theme_set_view(request):
    """Theme cards: saves at once (owner only, audited); HX-Trigger tells the page to swap the theme in place."""
    from . import themes  # noqa: PLC0415

    new = request.POST.get("theme", "")
    try:
        before = request.tenant.theme
        tenancy.set_theme(actor=request.actor, tenant=request.tenant, theme=new)
    except DomainError:
        return HttpResponse(status=400)
    resp = HttpResponse(status=204)
    resp["HX-Trigger"] = json.dumps(
        {
            "themeSaved": {
                "theme": new,
                "previous": before,
                "label": str(themes.THEMES[new][0]),
                "previousLabel": str(themes.THEMES[before][0]) if before in themes.THEMES else before,
                "color": themes.tokens(new)["primary"],
                "message": str(_("Theme changed to %(name)s")) % {"name": themes.THEMES[new][0]},
            }
        }
    )
    return resp


# --- reports -------------------------------------------------------------------------------------------------
def _parse_date(raw, default):
    try:
        return date.fromisoformat(raw) if raw else default
    except ValueError:
        return default


def _out(request, title, header, rows, *, extra=None, filename="report"):
    fmt = request.GET.get("format", "")
    if fmt == "csv":
        resp = HttpResponse(reports.to_csv(header, rows), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        return resp
    ctx = {
        "title": title,
        "header": header,
        "rows": rows,
        "extra": extra or [],
        "tenant": request.tenant,
        "query": request.GET.urlencode(),
        "filename": filename,
    }
    if fmt == "pdf":
        from weasyprint import HTML  # noqa: PLC0415

        resp = HttpResponse(
            HTML(string=render_to_string("web/report_pdf.html", ctx)).write_pdf(), content_type="application/pdf"
        )
        resp["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
        return resp
    return None, ctx


def safe_report(view):
    """Domain errors (bad period...) become a friendly message on the reports index, not a 500."""
    from functools import wraps  # noqa: PLC0415

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except DomainError as exc:
            return render(request, "web/admin_reports.html", {"error": friendly(exc)}, status=400)

    return wrapper


def _render_report(request, result, template_extra):
    if isinstance(result, HttpResponse):
        return result
    _none, ctx = result
    return render(request, "web/report.html", {**ctx, **template_extra})


@tenant_view(**ADMIN)
@require_GET
def reports_index(request):
    return render(request, "web/admin_reports.html")


def _period(request):
    today = local_date(timezone.now(), request.tenant.timezone)
    start = _parse_date(request.GET.get("start"), today - timedelta(days=29))
    end = _parse_date(request.GET.get("end"), today)
    return start, end


@tenant_view(**ADMIN)
@require_GET
@safe_report
def report_daily(request):
    start, end = _period(request)
    r = reports.daily_consumption(actor=request.actor, start=start, end=end)
    rows = (
        [[x["date"], x["meals"]] for x in r["days"]]
        + [["", ""]]
        + [[f"{c['code']} {c['name']}", c["meals"]] for c in r["customers"]]
    )
    return _render_report(
        request,
        _out(
            request,
            _("Daily consumption"),
            [_("Date / customer"), _("Meals")],
            rows,
            extra=[(_("Total meals"), r["total"])],
            filename="daily-consumption",
        ),
        {"period": (start, end), "kind": "period"},
    )


REFUSAL_LABELS = {
    "MEAL_SLOT_CLOSED": gettext_lazy("Outside meal time"),
    "MEAL_SLOT_CAP_REACHED": gettext_lazy("Already had this meal"),
    "DAILY_CAP_REACHED": gettext_lazy("Daily limit reached"),
    "NO_ACTIVE_PASS": gettext_lazy("No active pass"),
    "PASS_NOT_VALID_NOW": gettext_lazy("Pass not valid now"),
    "NO_CREDITS": gettext_lazy("No meals left"),
    "CUSTOMER_BLOCKED": gettext_lazy("Customer blocked"),
    "TENANT_PAUSED": gettext_lazy("Restaurant paused"),
}


@tenant_view(**OWNER)
@require_GET
@safe_report
def report_refused(request):
    """D03.9 §B5: refused redemptions (``redeem.denied``) for spotting fraud: who tried, when, why, which channel."""
    from datetime import datetime as _dt  # noqa: PLC0415
    from datetime import time as _time  # noqa: PLC0415

    from mealtally.audit.models import AuditEvent  # noqa: PLC0415
    from mealtally.customers.models import Customer  # noqa: PLC0415

    start, end = _period(request)
    tz = request.tenant.zone
    events = list(
        AuditEvent.objects.filter(
            action="redeem.denied",
            created_at__gte=_dt.combine(start, _time.min, tzinfo=tz),
            created_at__lt=_dt.combine(end + timedelta(days=1), _time.min, tzinfo=tz),
        )
        .select_related("actor")
        .order_by("-created_at")[:2000]
    )
    names = dict(
        Customer.objects.filter(public_id__in={e.object_public_id for e in events}).values_list(
            "public_id", "full_name"
        )
    )
    rows = [
        [
            e.created_at.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
            names.get(e.object_public_id, "—"),
            str(REFUSAL_LABELS.get((e.after or {}).get("code"), (e.after or {}).get("code", ""))),
            (e.after or {}).get("message", ""),
            actor_label(e.actor),
            str(SOURCE_LABELS.get((e.after or {}).get("channel"), (e.after or {}).get("channel", ""))),
        ]
        for e in events
    ]
    by_reason: dict[str, int] = {}
    for row in rows:
        by_reason[row[2]] = by_reason.get(row[2], 0) + 1
    return _render_report(
        request,
        _out(
            request,
            _("Refused redemptions"),
            [_("When"), _("Customer"), _("Reason"), _("Message"), _("Staff"), _("Channel")],
            rows,
            extra=[(_("Refused"), len(rows))] + sorted(by_reason.items(), key=lambda kv: -kv[1]),
            filename="refused-redemptions",
        ),
        {"period": (start, end), "kind": "period"},
    )


@tenant_view(**ADMIN)
@require_GET
@safe_report
def report_monthly(request):
    today = local_date(timezone.now(), request.tenant.timezone)
    year, month = _parse_month(request.GET.get("month"), today)
    r = reports.monthly_subscriptions(actor=request.actor, year=year, month=month)
    rows = [[p["plan"], p["passes"], rupees(p["revenue_paise"])] for p in r["by_plan"]]
    extra = [
        (_("Passes sold"), r["passes_sold"]),
        (_("Revenue"), rupees(r["revenue_paise"])),
        (_("Voids"), f"{r['voids']} ({rupees(r['void_amount_paise'])})"),
    ]
    return _render_report(
        request,
        _out(
            request,
            _("Monthly subscriptions"),
            [_("Plan"), _("Passes"), _("Revenue")],
            rows,
            extra=extra,
            filename=f"subscriptions-{r['month']}",
        ),
        {"month": r["month"], "kind": "month"},
    )


def _parse_month(raw, today):
    try:
        y, m = (raw or "").split("-")
        return int(y), int(m)
    except ValueError:
        return today.year, today.month


@tenant_view(**ADMIN)
@require_GET
@safe_report
def report_expired(request):
    start, end = _period(request)
    r = reports.expired_unused(actor=request.actor, start=start, end=end)
    rows = [
        [x["customer_code"], x["customer"], x["plan"], x["ended"], x["meals_total"], x["unused"]] for x in r["passes"]
    ]
    return _render_report(
        request,
        _out(
            request,
            _("Expired & unused"),
            [_("Code"), _("Customer"), _("Plan"), _("Ended"), _("Meals"), _("Unused")],
            rows,
            extra=[(_("Total meals forfeited"), r["total_forfeited"])],
            filename="expired-unused",
        ),
        {"period": (start, end), "kind": "period"},
    )


@tenant_view(**ADMIN)
@require_GET
@safe_report
def report_statement(request, customer_id):
    start, end = _period(request)
    try:
        customer = customers.get_customer(customer_id)
    except DomainError as exc:
        raise Http404 from exc
    r = reports.customer_statement(actor=request.actor, customer=customer, start=start, end=end)
    rows = (
        [
            ["PASS", p["plan"], p["status"], p["starts"], p["ends"], f"{p['remaining']}/{p['meals_total']}"]
            for p in r["passes"]
        ]
        + [
            ["PAYMENT", p["receipt"], p["status"], p["date"], p["method"], rupees(p["amount_paise"])]
            for p in r["payments"]
        ]
        + [["LEDGER", e["type"], "", e["at"], e["quantity"], e["balance"]] for e in r["ledger"]]
    )
    return _render_report(
        request,
        _out(
            request,
            f"{_('Customer statement')}: {customer.customer_code} {customer.full_name}",
            [_("Kind"), _("Item"), _("Status"), _("Date"), _("Detail"), _("Amount / balance")],
            rows,
            filename=f"statement-{customer.customer_code}",
        ),
        {"period": (start, end), "kind": "period", "customer": customer},
    )


@tenant_view(**ADMIN)
@require_GET
@safe_report
def report_fees(request):
    if request.role != Role.OWNER:  # D03.8: owner only, for the page, the CSV and the PDF alike
        raise PermissionDenied
    today = local_date(timezone.now(), request.tenant.timezone)
    year, month = _parse_month(request.GET.get("month"), today)
    s = billing.fee_statement(actor=request.actor, year=year, month=month)
    rows = [
        [
            ln["receipt_number"],
            ln["date"][:10],
            ln["customer"],
            ln["status"],
            rupees(ln["base_paise"]),
            f"{ln['platform_pct']}%",
            rupees(ln["fee_paise"]),
            rupees(ln["reversed_paise"]),
            rupees(ln["net_paise"]),
        ]
        for ln in s["lines"]
    ]
    extra = [
        (_("Gross payments"), rupees(s["gross_paise"])),
        (_("Platform fee"), rupees(s["platform_fee_paise"])),
        (_("Gateway fee"), rupees(s["gateway_fee_paise"])),
        (_("Voids in month"), s["voided_count"]),
        (_("Net payable to platform"), rupees(s["total_fee_paise"])),
    ]
    return _render_report(
        request,
        _out(
            request,
            _("Platform fee statement"),
            [
                _("Receipt"),
                _("Date"),
                _("Customer"),
                _("Status"),
                _("Base"),
                _("%"),
                _("Fee"),
                _("Reversed (void)"),
                _("Net"),
            ],
            rows,
            extra=extra,
            filename=f"fee-statement-{s['month']}",
        ),
        {"month": s["month"], "kind": "month"},
    )


# --- audit ---------------------------------------------------------------------------------------------------
@tenant_view(**ADMIN)
@require_GET
def audit_view(request):
    g = request.GET
    events = reports.audit_log(
        actor=request.actor,
        actor_query=g.get("actor", ""),
        action=g.get("action", ""),
        start=_parse_date(g.get("start"), None),
        end=_parse_date(g.get("end"), None),
    )
    from . import audit_text  # noqa: PLC0415

    events = list(events)
    tz = request.tenant.zone
    lookups = audit_text.build_lookups(events)
    rows = [
        {
            "e": e,
            "who": actor_label(e.actor),
            "summary": audit_text.summarize(e, lookups, tz),
            "raw": audit_text.raw(e),
        }
        for e in events
    ]
    return render(request, "web/admin_audit.html", {"events": rows, "q": g, "tz": tz})
