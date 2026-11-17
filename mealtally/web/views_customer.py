from __future__ import annotations

import base64
import time
from itertools import groupby

from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from mealtally.billing import receipts
from mealtally.billing import services as billing
from mealtally.common.errors import DomainError
from mealtally.common.utils import local_date
from mealtally.customers import qr
from mealtally.customers import services as customers
from mealtally.ledger import services as ledger
from mealtally.ledger.models import MealLedgerEntry
from mealtally.passes import services as passes
from mealtally.plans import meal_rules

from .access import htmx
from .access import require_customer
from .access import tenant_view
from .copy import friendly

PAGE = 20
PIN_LOGIN_GRACE_SECONDS = 600
LABELS = {
    "ISSUE": _("Credits issued"),
    "REDEEM": _("Meal redeemed"),
    "REVERSAL": _("Meal undone"),
    "ADJUST": _("Adjusted by restaurant"),
    "EXPIRE": _("Expired"),
}


def _pass_card(p, tz, now):
    if p is None:
        return None
    days_left = max((p.ends_at.astimezone(tz).date() - now.astimezone(tz).date()).days, 0)
    active = p.status == "ACTIVE"
    expiring = active and days_left <= 3 and p.meals_remaining > 0  # noqa: PLR2004 -- the risk is forfeiture, not a low wallet
    low = active and not expiring and p.meals_remaining <= 3  # noqa: PLR2004
    ring = round(100 * p.meals_remaining / p.meals_total) if p.meals_total else 0
    return {
        "obj": p,
        "days_left": days_left,
        "ends": p.ends_at.astimezone(tz),
        "starts": p.starts_at.astimezone(tz),
        "expiring": expiring,
        "low": low,
        "warn": expiring or low,
        "ring": ring,
        "ring_offset": 100 - ring,
    }


def _active_card(request, customer):
    return _pass_card(passes.active_pass_for(customer.id), request.tenant.zone, timezone.now())


@tenant_view()
@require_GET
def me_home(request):
    customer = require_customer(request)
    tz, now = request.tenant.zone, timezone.now()
    active = (
        passes.active_pass_for(customer.id)
        or passes.passes_for_customer(customer.id).filter(status="SUSPENDED").first()
    )
    today = local_date(now, request.tenant.timezone)
    todays = MealLedgerEntry.objects.filter(customer=customer, meal_date=today)
    meals_today = todays.filter(entry_type="REDEEM").count() - todays.filter(entry_type="REVERSAL").count()
    queued = [_pass_card(q, tz, now) for q in passes.queued_passes_for(customer.id)]
    extra = {}
    if request.tenant.has_demo_dataset:  # wallet, today's meal and coming up come from the preview dataset
        from mealtally.preview import customer_home  # noqa: PLC0415

        extra = customer_home.summary(request)
    return render(
        request,
        "web/me_home.html",
        {
            **extra,
            "customer": customer,
            "card": _pass_card(active, tz, now),
            "queued": queued,
            "meals_today": meals_today,
            "consumed": ledger.consumed_count(active) if active else 0,
            "rule_line": meal_rules.customer_rule_line(active, now, tz) if active else "",
        },
    )


def _qr_ctx(request, customer):
    """One fresh 90 s code per render: the QR image and the typed-in fallback below it are the SAME code (D03.3)."""
    code = qr.issue_code(customer=customer, tenant=request.tenant)
    svg = base64.b64encode(qr.render_svg(code)).decode()
    return {
        "customer": customer,
        "stamp": int(time.time()),
        "card": _active_card(request, customer),
        "qr_code": " ".join(code[i : i + 4] for i in range(0, len(code), 4)),
        "qr_data_uri": f"data:image/svg+xml;base64,{svg}",
    }


@tenant_view()
@require_GET
def me_qr(request):
    customer = require_customer(request)
    return render(request, "web/me_qr.html", _qr_ctx(request, customer))


@tenant_view()
@require_GET
def me_qr_fragment(request):
    """Polled every 30 s by HTMX: a fresh QR image (new 90 s token each time)."""
    customer = require_customer(request)
    return render(request, "web/_qr_fragment.html", _qr_ctx(request, customer))


@tenant_view()
@require_GET
def me_history(request):
    customer = require_customer(request)
    page = max(int(request.GET.get("page", "1") or 1), 1)
    qs = ledger.entries_for_customer(customer.id)
    rows = list(qs[(page - 1) * PAGE : (page - 1) * PAGE + PAGE + 1])
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    tz = request.tenant.zone
    items = [
        {"e": e, "label": LABELS.get(e.entry_type, e.entry_type), "at": e.occurred_at.astimezone(tz)} for e in rows
    ]
    groups = [(day, list(g)) for day, g in groupby(items, key=lambda i: i["at"].date())]
    ctx = {"groups": groups, "next_page": page + 1 if more else None, "customer": customer}
    return render(request, "web/_history_rows.html" if htmx(request) else "web/me_history.html", ctx)


@tenant_view()
@require_GET
def me_payments(request):
    customer = require_customer(request)
    return render(
        request,
        "web/me_payments.html",
        {"payments": billing.payments_for_customer(customer.id)[:100], "tz": request.tenant.zone},
    )


@tenant_view()
@require_http_methods(["GET", "POST"])
def me_profile(request):
    customer = require_customer(request)
    msg = err = None
    if request.method == "POST":
        try:
            customers.update_own_name(
                customer=customer,
                full_name=request.POST.get("full_name", ""),
                address=request.POST.get("address", customer.address),
            )
            msg = _("Saved.")
        except DomainError as exc:
            err = friendly(exc)
    return render(request, "web/me_profile.html", {"customer": customer, "msg": msg, "err": err})


@tenant_view(allow_forced=True)
@require_http_methods(["GET", "POST"])
def me_pin(request):
    customer = require_customer(request)
    # D02.1 #19: a forced first-login change right after a successful PIN login (same session, < 10 min) does not
    # ask for the current PIN again. Voluntary changes always do.
    fresh = time.time() - request.session.get("pin_login_at", 0) < PIN_LOGIN_GRACE_SECONDS
    skip_old = customer.must_change_pin and fresh
    ctx = {"customer": customer, "forced": customer.must_change_pin, "skip_old": skip_old}
    if request.method == "POST":
        new, confirm = request.POST.get("new_pin", ""), request.POST.get("confirm_pin", "")
        try:
            if new != confirm:
                raise DomainError(_("The two PINs do not match."))
            customers.change_pin(
                customer=customer, old_pin=request.POST.get("old_pin", ""), new_pin=new, verified=skip_old
            )
        except DomainError as exc:
            return render(request, "web/me_pin.html", {**ctx, "err": friendly(exc)}, status=400)
        return redirect("web:me-home", slug=request.tenant.slug)
    return render(request, "web/me_pin.html", ctx)


def _receipt_payment(request, payment_id):
    try:
        payment = billing.get_payment(payment_id)
    except DomainError as exc:
        raise Http404 from exc
    if request.role == "CUSTOMER" and payment.customer.user_id != request.user.id:
        raise Http404
    return payment


@tenant_view()
@require_GET
def receipt_html(request, payment_id):
    payment = _receipt_payment(request, payment_id)
    return HttpResponse(receipts.render_receipt_html(payment, print_view=True))


@tenant_view()
@require_GET
def receipt_pdf(request, payment_id):
    payment = _receipt_payment(request, payment_id)
    response = HttpResponse(receipts.render_receipt_pdf(payment), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{payment.receipt_number or "receipt"}.pdf"'
    return response


ACTIVITY_FILTERS = ["all", "meals", "deliveries", "payments", "invoices"]


def _activity_items(request, customer, kind):
    """One timeline: real ledger and payments, plus (demo tenants) deliveries and invoices from the preview data."""
    tz = request.tenant.zone
    items = []
    if kind in ("all", "meals"):
        for e in ledger.entries_for_customer(customer.id)[:40]:
            at = e.occurred_at.astimezone(tz)
            items.append(
                {
                    "at": at,
                    "kind": "meals",
                    "icon": "meals",
                    "title": LABELS.get(e.entry_type, e.entry_type),
                    "detail": at.strftime("%-I:%M %p"),
                    "credits": e.quantity,
                    "chip": "void" if e.entry_type == "REVERSAL" else "",
                }
            )
    if kind in ("all", "payments"):
        for p in billing.payments_for_customer(customer.id)[:20]:
            at = p.received_at.astimezone(tz)
            items.append(
                {
                    "at": at,
                    "kind": "payments",
                    "icon": "payments",
                    "title": p.plan.name,
                    "detail": f"{p.receipt_number} · {at.strftime('%-I:%M %p')}",
                    "amount": p.amount_paise,
                    "chip": "void" if p.status == "VOIDED" else "",
                    "pdf": reverse("web:receipt-pdf", args=[request.tenant.slug, p.public_id]),
                }
            )
    if request.tenant.has_demo_dataset and kind in ("all", "deliveries", "invoices"):
        from datetime import datetime  # noqa: PLC0415

        from mealtally.preview import data as pvdata  # noqa: PLC0415
        from mealtally.preview.views_me import _me  # noqa: PLC0415

        dataset = pvdata.for_tenant(request.tenant)
        sub = _me(dataset, request)
        if sub is not None and kind in ("all", "deliveries"):
            for o in pvdata.sub_orders(dataset, sub["id"], limit=10):
                if o["status"] in ("DELIVERED", "PICKED_UP", "SKIPPED", "SKIPPED_HOLD", "CANCELLED"):
                    at = datetime.combine(o["date"], dataset["slot"][o["slot"]]["start"]).replace(tzinfo=tz)
                    items.append(
                        {
                            "at": at,
                            "kind": "deliveries",
                            "icon": "delivery",
                            "title": f"{dataset['slot'][o['slot']]['name']} · "
                            + ", ".join(i["name"] for i in o["items"][:2]),
                            "detail": f"{dataset['slot'][o['slot']]['start']:%-I:%M %p}",
                            "chip": "active" if o["status"] in ("DELIVERED", "PICKED_UP") else "void",
                            "chip_label": o["status"].replace("_", " ").capitalize(),
                        }
                    )
        if sub is not None and kind in ("all", "invoices"):
            for inv in [i for i in dataset["invoices"] if i["sub_id"] == sub["id"]][:6]:
                items.append(
                    {
                        "at": datetime.combine(inv.get("date") or dataset["today"], datetime.min.time()).replace(
                            tzinfo=tz
                        ),
                        "kind": "invoices",
                        "icon": "invoice",
                        "title": inv["month"],
                        "detail": inv["id"],
                        "amount": inv["total_paise"],
                        "chip": "",
                        "pdf": reverse("preview:me-invoices-pdf", args=[request.tenant.slug, inv["id"]]),
                    }
                )
    items.sort(key=lambda i: i["at"], reverse=True)
    return items


@tenant_view()
@require_GET
def me_activity(request):
    customer = require_customer(request)
    kind = request.GET.get("f", "all")
    kind = kind if kind in ACTIVITY_FILTERS else "all"
    items = _activity_items(request, customer, kind)
    groups = [(day, list(g)) for day, g in groupby(items, key=lambda i: i["at"].date())]
    labels = {
        "all": _("All"),
        "meals": _("Meals"),
        "deliveries": _("Deliveries"),
        "payments": _("Payments"),
        "invoices": _("Invoices"),
    }
    filters = [
        (k, labels[k]) for k in ACTIVITY_FILTERS if request.tenant.has_demo_dataset or k in ("all", "meals", "payments")
    ]
    return render(request, "web/me_activity.html", {"groups": groups, "filters": filters, "kind": kind})


@tenant_view()
@require_http_methods(["GET", "POST"])
def me_account(request):
    customer = require_customer(request)
    msg = err = None
    if request.method == "POST":
        try:
            customers.update_own_name(
                customer=customer,
                full_name=request.POST.get("full_name", ""),
                address=request.POST.get("address", customer.address),
            )
            msg = _("Saved.")
        except DomainError as exc:
            err = friendly(exc)
    tz, now = request.tenant.zone, timezone.now()
    active = passes.active_pass_for(customer.id)
    plans = [_pass_card(active, tz, now)] if active else []
    plans += [_pass_card(q, tz, now) for q in passes.queued_passes_for(customer.id)]
    return render(request, "web/me_account.html", {"customer": customer, "msg": msg, "err": err, "plans": plans})


@tenant_view()
@require_POST
def me_topup_check(request):
    """D03.9 QA-01 P1-6: server-side check of a wallet top-up request (UTR = exactly 12 digits; amount within the
    restaurant's bounds). The wallet itself is still a preview, so nothing is stored."""
    require_customer(request)
    cfg = request.cfg
    lo, hi = cfg.topup_min_paise // 100, cfg.topup_max_paise // 100
    errors = []
    raw_amount = (request.POST.get("amount") or "").strip()
    if not raw_amount.isdigit():
        errors.append(_("Enter the amount in whole rupees."))
    elif not lo <= int(raw_amount) <= hi:
        errors.append(_("The amount must be between ₹%(lo)s and ₹%(hi)s.") % {"lo": f"{lo:,}", "hi": f"{hi:,}"})
    utr = (request.POST.get("utr") or "").strip().replace(" ", "")
    if not (len(utr) == 12 and utr.isdigit()):  # noqa: PLR2004
        errors.append(_("The UTR is the 12-digit number in your UPI app's payment details."))
    return render(request, "web/_topup_result.html", {"errors": errors}, status=200)
