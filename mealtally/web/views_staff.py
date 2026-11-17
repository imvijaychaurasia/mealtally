# SPDX-License-Identifier: AGPL-3.0-only
"""Redeem console, sell-pass flow and customer creation (STAFF, MANAGER, OWNER)."""

from __future__ import annotations

import uuid

from django.db import transaction
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from mealtally.accounts.models import STAFF_ROLES
from mealtally.billing import services as billing
from mealtally.common import country
from mealtally.common.country import mask_phone
from mealtally.common.errors import DomainError
from mealtally.common.utils import local_date
from mealtally.customers import qr
from mealtally.customers import services as customers
from mealtally.ledger import services as ledger
from mealtally.ledger.models import MealLedgerEntry
from mealtally.passes import services as passes
from mealtally.passes.models import Pass
from mealtally.plans import services as plans

from .access import tenant_view
from .copy import friendly
from .labels import actor_label

STAFF = {"roles": STAFF_ROLES}


def _card_ctx(request, customer, **extra):
    status = ledger.redeem_status(customer=customer)
    pass_ = status["pass"]
    tz = request.tenant.zone
    return {
        "customer": customer,
        "status": status,
        "pass": pass_,
        "phone_masked": mask_phone(customer.phone_e164),
        "ends": pass_.ends_at.astimezone(tz) if pass_ else None,
        "key": str(uuid.uuid4()),
        "error_text": status.get("message") or (friendly(DomainError(code=status["code"])) if status["code"] else ""),
        "rule_block": bool(status.get("rule")),
        "can_override": request.actor.role in ledger.OVERRIDE_ROLES,
        **extra,
    }


def _today_ctx(request):
    tenant = request.tenant
    today = local_date(timezone.now(), tenant.timezone)
    rows = list(ledger.daily_redemptions(actor=request.actor, day=today))
    tz = tenant.zone
    from mealtally.billing.models import Payment  # noqa: PLC0415

    show_undone = request.GET.get("undone") == "1"
    all_rows = [
        {"e": r, "at": r.occurred_at.astimezone(tz), "reversed": hasattr(r, "reversal"), "who": actor_label(r.operator)}
        for r in rows
    ]
    undone = sum(1 for r in all_rows if r["reversed"])
    from datetime import datetime  # noqa: PLC0415
    from datetime import time as dtime  # noqa: PLC0415
    from datetime import timedelta  # noqa: PLC0415

    start = datetime.combine(today, dtime.min, tzinfo=tz)
    paid = list(
        Payment.objects.filter(
            status=Payment.Status.RECORDED, received_at__gte=start, received_at__lt=start + timedelta(days=1)
        )
    )
    return {
        "rows": all_rows if show_undone else [r for r in all_rows if not r["reversed"]],
        "today": today,
        "net": len(all_rows) - undone,
        "undone": undone,
        "show_undone": show_undone,
        "passes_sold": len(paid),
        "cash_minor": sum(p.amount_minor for p in paid if p.method == Payment.Method.CASH),
    }


@tenant_view(**STAFF)
@require_GET
def console(request):
    return render(request, "web/staff_console.html", _today_ctx(request))


@tenant_view(**STAFF)
@require_GET
def search(request):
    q = request.GET.get("q", "").strip()
    found = list(customers.search(q, limit=8)) if q else []
    ids = [c.id for c in found]
    active = {p.customer_id: p for p in Pass.objects.filter(customer_id__in=ids, status=Pass.Status.ACTIVE)}
    queued = set(
        Pass.objects.filter(customer_id__in=ids, status=Pass.Status.QUEUED).values_list("customer_id", flat=True)
    )
    results = [
        {"c": c, "phone": mask_phone(c.phone_e164), "pass": active.get(c.id), "queued": c.id in queued} for c in found
    ]
    return render(request, "web/_search_results.html", {"results": results, "q": q})


@tenant_view(**STAFF)
@require_GET
def card(request, customer_id):
    try:
        customer = customers.get_customer(customer_id)
    except DomainError:
        return render(request, "web/_card_empty.html", {"error": _("Customer not found.")})
    return render(request, "web/_card.html", _card_ctx(request, customer))


@tenant_view(**STAFF)
@require_GET
def card_reset(request):
    return render(request, "web/_card_empty.html")


@tenant_view(**STAFF)
@require_GET
def today(request):
    return render(request, "web/_today.html", _today_ctx(request))


def _duration(seconds: int) -> str:
    if seconds < 60:  # noqa: PLR2004
        return ngettext("%(n)d second", "%(n)d seconds", seconds) % {"n": seconds}
    minutes = round(seconds / 60)
    return ngettext("%(n)d minute", "%(n)d minutes", minutes) % {"n": minutes}


def cooldown_text(ago_seconds: int, limit_seconds: int) -> str:
    """'Already redeemed 1 minute ago (limit 2 minutes) — give another meal?' from the real setting."""
    ago = _("less than a minute") if ago_seconds < 60 else _duration((ago_seconds // 60) * 60)  # noqa: PLR2004
    return _("Already redeemed %(ago)s ago (limit %(limit)s) — give another meal?") % {
        "ago": ago,
        "limit": _duration(limit_seconds),
    }


def _redeem_response(request, customer, *, source, key, confirm, token="", override_reason=""):
    try:
        result = ledger.redeem(
            actor=request.actor,
            customer=customer,
            idempotency_key=key,
            source=source,
            confirm_additional=confirm,
            override_reason=override_reason,
        )
    except DomainError as exc:
        if exc.code == "COOLDOWN_CONFIRM_REQUIRED":
            last = exc.details.get("last_redeemed_at")
            seconds = (
                max(int((timezone.now() - timezone.datetime.fromisoformat(last)).total_seconds()), 0) if last else 0
            )
            return render(
                request,
                "web/_card.html",
                {
                    **_card_ctx(request, customer),
                    "modal": True,
                    "cooldown_text": cooldown_text(seconds, int(exc.details.get("cooldown_seconds") or 0)),
                    "key": key,
                    "scan_token": token,
                },
            )
        ctx = _card_ctx(request, customer)
        if exc.code in ledger.RULE_CODES:
            ctx["rule_block"] = True
        resp = render(request, "web/_card.html", {**ctx, "error": friendly(exc), "key": str(uuid.uuid4())})
        return resp
    resp = render(
        request,
        "web/_redeem_success.html",
        {
            "customer": customer,
            "result": result,
            "entry": result.entry,
            "left": result.meals_remaining,
            "total": result.pass_.meals_total,
        },
    )
    resp["HX-Trigger"] = '{"mealtally:redeemed": {}, "mealtally:refresh-today": {}}'
    return resp


@tenant_view(**STAFF)
@require_POST
def redeem(request):
    try:
        customer = customers.get_customer(request.POST.get("customer", ""))
    except DomainError:
        return render(request, "web/_card_empty.html", {"error": _("Customer not found.")})
    return _redeem_response(
        request,
        customer,
        source=MealLedgerEntry.Source.STAFF_SEARCH,
        key=request.POST.get("idempotency_key", ""),
        confirm=request.POST.get("confirm_additional") == "1",
        override_reason=request.POST.get("override_reason", ""),
    )


@tenant_view(**STAFF)
@require_POST
def scan(request):
    token = request.POST.get("token", "").strip()
    key = request.POST.get("idempotency_key") or str(uuid.uuid4())
    try:
        payload = qr.resolve(token, tenant=request.tenant)
        customer = customers.get_customer(payload["cid"])
        qr.claim_jti(payload["jti"], key)
    except DomainError as exc:
        return render(request, "web/_card_empty.html", {"error": friendly(exc), "scan_error": True})
    return _redeem_response(
        request,
        customer,
        source=MealLedgerEntry.Source.QR_SCAN,
        key=key,
        confirm=request.POST.get("confirm_additional") == "1",
        token=token,
    )


@tenant_view(**STAFF)
@require_POST
def undo(request):
    try:
        rev = ledger.reverse_redemption(
            actor=request.actor, entry_public_id=request.POST.get("entry", ""), reason=_("Undone at counter")
        )
    except DomainError as exc:
        return render(request, "web/_undo_done.html", {"error": friendly(exc)})
    resp = render(request, "web/_undo_done.html", {"left": rev.balance_after})
    resp["HX-Trigger"] = '{"mealtally:refresh-today": {}}'
    return resp


@tenant_view(**STAFF)
@require_POST
def reverse(request):
    try:
        ledger.reverse_redemption(
            actor=request.actor, entry_public_id=request.POST.get("entry", ""), reason=request.POST.get("reason", "")
        )
        err = None
    except DomainError as exc:
        err = friendly(exc)
    return render(request, "web/_today.html", {**_today_ctx(request), "error": err})


@tenant_view(**STAFF)
@require_GET
def customers_lookup(request):
    """STAFF 'Customers': lookup only (no detail page, no actions)."""
    rows = customers.list_customers(query=request.GET.get("q", ""), status=request.GET.get("status", ""))
    ctx = {"rows": rows, "q": request.GET.get("q", ""), "status": request.GET.get("status", "")}
    return render(
        request,
        "web/_staff_customer_rows.html" if request.headers.get("HX-Request") else "web/staff_customers.html",
        ctx,
    )


# --- sell pass ---------------------------------------------------------------------------------------
def _sell_ctx(request, **extra):
    return {
        "plans": plans.list_plans(),
        "methods": country.payment_methods(request.tenant.country),
        "pin_len": request.cfg.customer_pin_length,
        **extra,
    }


@tenant_view(**STAFF)
@require_GET
def sell(request):
    pre = request.GET.get("customer", "")
    customer = None
    if pre:
        try:
            customer = customers.get_customer(pre)
        except DomainError:
            customer = None
    recorded = request.GET.get("recorded", "")[:20]
    return render(request, "web/sell.html", _sell_ctx(request, customer=customer, recorded=recorded))


@tenant_view(**STAFF)
@require_GET
def sell_search(request):
    q = request.GET.get("sq", "").strip()
    results = list(customers.search(q, limit=6)) if q else []
    return render(request, "web/_sell_results.html", {"results": results, "q": q})


def _sell_get_redirect(request):
    """Back/refresh on a sell step (GET) goes to the sell form, noting a sale this person just made."""
    from datetime import timedelta  # noqa: PLC0415

    from django.shortcuts import redirect  # noqa: PLC0415
    from django.urls import reverse  # noqa: PLC0415

    from mealtally.billing.models import Payment  # noqa: PLC0415

    recent = (
        Payment.objects.filter(recorded_by=request.user, received_at__gte=timezone.now() - timedelta(minutes=30))
        .order_by("-id")
        .first()
    )
    url = reverse("web:staff-sell", args=[request.tenant.slug])
    return redirect(f"{url}?recorded={recent.receipt_number}" if recent and recent.receipt_number else url)


@tenant_view(**STAFF)
@require_http_methods(["GET", "POST"])
def sell_preview(request):
    if request.method == "GET":
        return _sell_get_redirect(request)
    data = request.POST
    try:
        plan = plans.get_plan(data.get("plan", ""))
        customer = customers.get_customer(data["customer"]) if data.get("customer") else None
        if customer is None and not (data.get("new_name") and data.get("new_phone")):
            raise DomainError(_("Pick a customer or enter the new customer's name and phone."))
        if data.get("method") != "CASH" and not data.get("reference", "").strip():
            raise DomainError(_("A reference (UTR / transaction ID) is required for non-cash payments."))
        preview = passes.preview_purchase(
            customer_id=customer.id if customer else None, plan=plan, tenant=request.tenant, settings_row=request.cfg
        )
        if preview["queue_full"]:
            raise DomainError(code="QUEUE_FULL")
    except DomainError as exc:
        return render(
            request, "web/sell.html", _sell_ctx(request, error=friendly(exc), form=data, customer=None), status=400
        )
    return render(
        request,
        "web/sell_preview.html",
        {
            "plan": plan,
            "customer": customer,
            "preview": preview,
            "form": data,
            "method_label": dict(_sell_ctx(request)["methods"]).get(data.get("method", ""), data.get("method", "")),
        },
    )


@tenant_view(**STAFF)
@require_http_methods(["GET", "POST"])
def sell_confirm(request):
    if request.method == "GET":
        return _sell_get_redirect(request)
    data = request.POST
    pin = None
    try:
        plan = plans.get_plan(data.get("plan", ""))
        existing = customers.get_customer(data["customer"]) if data.get("customer") else None
        preview = passes.preview_purchase(
            customer_id=existing.id if existing else None, plan=plan, tenant=request.tenant, settings_row=request.cfg
        )
        if preview["gap"] and data.get("ack_gap") != "1":
            raise DomainError(_("Please confirm the gap in coverage before selling."))
        with transaction.atomic():
            customer = existing
            if customer is None:
                chosen = data.get("pin_choice") == "own"
                customer, pin = customers.create_customer(
                    actor=request.actor,
                    full_name=data.get("new_name", ""),
                    phone=data.get("new_phone", ""),
                    pin=data.get("new_pin") if chosen else None,
                )
            recorded = billing.record_payment(
                actor=request.actor,
                customer_public_id=customer.public_id,
                plan_public_id=plan.public_id,
                amount_minor=plan.price_minor,
                method=data.get("method", ""),
                reference=data.get("reference", ""),
            )
    except DomainError as exc:
        return render(
            request, "web/sell.html", _sell_ctx(request, error=friendly(exc), form=data, customer=None), status=400
        )
    return render(
        request,
        "web/sell_done.html",
        {
            "payment": recorded.payment,
            "pass": recorded.pass_,
            "customer": customer,
            "pin": pin,
            "tz": request.tenant.zone,
            "plan": plan,
        },
    )


@tenant_view(**STAFF)
@require_http_methods(["GET", "POST"])
def customer_new(request):
    if request.method == "GET":
        return render(request, "web/customer_new.html", {"pin_len": request.cfg.customer_pin_length})
    d = request.POST
    try:
        customer, pin = customers.create_customer(
            actor=request.actor,
            full_name=d.get("full_name", ""),
            phone=d.get("phone", ""),
            pin=d.get("pin") if d.get("pin_choice") == "own" else None,
        )
    except DomainError as exc:
        return render(
            request,
            "web/customer_new.html",
            {"pin_len": request.cfg.customer_pin_length, "error": friendly(exc), "form": d},
            status=400,
        )
    return render(request, "web/customer_created.html", {"customer": customer, "pin": pin})
