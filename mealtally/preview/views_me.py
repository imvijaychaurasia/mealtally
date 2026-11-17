# SPDX-License-Identifier: AGPL-3.0-only
"""Preview: wallet-plan customer app. The logged-in customer sees THEIR OWN wallet, or none."""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta

from django.http import Http404
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from mealtally.common import money

from . import data
from . import util
from .access import preview_view


def _me(D, request=None):
    """The logged-in customer's wallet subscription, or None when they are not a wallet subscriber."""
    if not D.get("real") or request is None:
        return D["sub"].get(D["featured_sub_id"])
    from mealtally.common.country import format_phone  # noqa: PLC0415
    from mealtally.customers.models import Customer  # noqa: PLC0415

    customer = Customer.objects.filter(user=request.user).first()
    if customer is None or not customer.has_wallet:
        return None
    return D["sub"].get(D["sub_by_phone"].get(format_phone(customer.phone_e164)))


def _no_wallet(request, D):
    return render(request, "preview/no_wallet.html", {"D": D})


def _next_meal(D, s):
    """The next slot (today or tomorrow) whose cutoff is still ahead, with the day's menu options."""
    plan = D["wplan"][s["plan"]]
    now = timezone.localtime().replace(tzinfo=None)  # tenant-local wall clock (tenant_view overrides the zone)
    for off in (0, 1, 2):
        day = D["today"] + timedelta(days=off)
        if day.weekday() not in plan["delivery_days"]:
            continue
        for slot in D["slots"]:
            if slot["key"] not in plan["slots"]:
                continue
            start = datetime.combine(day, slot["start"])
            cutoff = start - timedelta(minutes=slot["cutoff_min"])
            if cutoff > now or off > 0:
                return {
                    "day": day,
                    "slot": slot,
                    "cutoff_iso": util.iso(cutoff),
                    "options": plan["menu"][day.weekday()][slot["key"]],
                    "label": "Today" if off == 0 else "Tomorrow" if off == 1 else day.strftime("%A"),
                }
    return None


@preview_view("me-meals")
@require_GET
def meals(request, D):
    s = _me(D, request)
    if s is None:
        return _no_wallet(request, D)
    nxt = _next_meal(D, s)
    upcoming = [o for o in D["orders"] if o["sub_id"] == s["id"] and 0 <= o["off"] <= 5][:6]
    return render(
        request,
        "preview/me_meals.html",
        {
            "D": D,
            "s": s,
            "plan": D["wplan"][s["plan"]],
            "nxt": nxt,
            "upcoming": upcoming,
            "skips_left": s["skip_limit"] - s["skips_used"],
            "today": D["today"].isoformat(),
            "weekday_qty": [(D["weekdays"][wd], s["qty"].get(wd, 0)) for wd in range(6)],
        },
    )


def _upi(request, D):
    """Real UPI intent QR codes (segno): the tenant's VPA, a few preset amounts and an 'other' one the payer completes."""
    import io  # noqa: PLC0415
    from base64 import b64encode  # noqa: PLC0415
    from urllib.parse import quote  # noqa: PLC0415

    import segno  # noqa: PLC0415

    vpa = D["website"]["domain"].split(".")[0] + "@upi"
    name = request.cfg.display_name or request.tenant.name

    def link(rupees):
        amt = f"&am={rupees}.00" if rupees else ""
        return f"upi://pay?pa={vpa}&pn={quote(name)}{amt}&cu=INR"

    def qr(uri):
        buf = io.BytesIO()
        segno.make(uri, error="m").save(buf, kind="svg", scale=5, border=2, xmldecl=False, dark="black", light="white")
        return "data:image/svg+xml;base64," + b64encode(buf.getvalue()).decode()

    amounts = [{"rupees": r, "label": f"₹{r:,}", "link": link(r), "qr": qr(link(r))} for r in (500, 1000, 2000)]
    return {
        "amounts": amounts,
        "default_qr": amounts[1]["qr"],
        "default_link": amounts[1]["link"],
        "other_qr": qr(link(0)),
        "other_link": link(0),
    }


@preview_view("me-wallet")
@require_GET
def wallet(request, D):
    s = _me(D, request)
    if s is None:  # no wallet: there is nothing to show here, and Home explains how to get one
        return redirect("web:me-home", request.tenant.slug)
    return render(
        request,
        "preview/me_wallet.html",
        {
            "D": D,
            "s": s,
            "ledger": list(reversed(D["ledgers"][s["id"]]))[:25],
            "vpa": D["website"]["domain"].split(".")[0] + "@upi",
            "upi": _upi(request, D),
            "topups": [t for t in D["topups"] if t["sub_id"] == s["id"]],
            "topup_min": int(money.to_major(request.cfg.topup_min_minor)),
            "topup_max": int(money.to_major(request.cfg.topup_max_minor)),
        },
    )


@preview_view("me-deliveries")
@require_GET
def deliveries(request, D):
    s = _me(D, request)
    if s is None:
        return _no_wallet(request, D)
    rows = [
        o
        for o in data.sub_orders(D, s["id"], limit=14)
        if o["status"] in ("DELIVERED", "PICKED_UP", "SKIPPED", "SKIPPED_HOLD", "CANCELLED")
    ]
    return render(request, "preview/me_deliveries.html", {"D": D, "s": s, "rows": rows})


@preview_view("me-invoices")
@require_GET
def invoices(request, D):
    s = _me(D, request)
    if s is None:
        return _no_wallet(request, D)
    return render(
        request,
        "preview/me_invoices.html",
        {"D": D, "s": s, "invoices": [i for i in D["invoices"] if i["sub_id"] == s["id"]]},
    )


@preview_view("me-invoices")
@require_GET
def invoice_pdf(request, D, inv):
    i = D["invoice"].get(inv)
    s = _me(D, request)
    if i is None or s is None or i["sub_id"] != s["id"]:
        raise Http404
    from .views_money import render_invoice_pdf  # noqa: PLC0415

    return render_invoice_pdf(request, D, i)


_CATS = (
    ("Breakfast", ("bhurji", "poha", "idli", "upma", "paratha", "pav", "omelette")),
    ("Sweets", ("gulab", "kheer", "jalebi", "halwa", "ladoo", "rasmalai", "payasam")),
    ("Snacks", ("chaas", "lassi", "samosa", "sandwich", "chai", "pakora", "juice", "buttermilk", "salad")),
    ("Dinner", ("biryani", "dinner")),
)


def _category(name: str) -> str:
    low = name.lower()
    for cat, words in _CATS:
        if any(w in low for w in words):
            return cat
    return "Lunch"


@preview_view("me-order")
@require_GET
def order_online(request, D):
    days = [D["today"] + timedelta(days=k) for k in range(7)]
    items = [{**it, "cat": _category(it["name"])} for it in D["ck_items"]]
    cats = [c for c in ("Breakfast", "Lunch", "Dinner", "Snacks", "Sweets") if any(i["cat"] == c for i in items)]
    from mealtally.customers.models import Customer  # noqa: PLC0415

    customer = Customer.objects.filter(user=request.user).first()
    return render(
        request,
        "preview/me_order.html",
        {
            "D": D,
            "items": items,
            "cats": cats,
            "rules": D["ck_rules"],
            "days": days,
            # the cart defaults to the CUSTOMER's address (never the restaurant's), wallet or not
            "delivery_address": customer.address if customer else "",
            "has_wallet": bool(customer and customer.has_wallet),
        },
    )
