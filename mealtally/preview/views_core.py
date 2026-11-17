"""Preview views: today, orders, kitchen, delivery, driver, holds, tiffin boxes (D03). No database writes anywhere."""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta

from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from mealtally.accounts.models import Role
from mealtally.reports import services as reports

from . import data
from . import util
from .access import preview_view
from .nav import module_url
from .registry import REGISTRY


def _page(request, template, **ctx):
    return render(request, template, ctx)


def _cta(slug, key):
    from django.urls import reverse  # noqa: PLC0415

    name = {
        "slots": "preview:menu",
        "plan": "web:admin-plans",
        "branch": "preview:branches",
        "route": "preview:delivery",
        "profile": "web:admin-settings",
    }[key]
    return reverse(name, args=[slug])


def _passes_30d(D) -> int:
    from datetime import datetime as _dt  # noqa: PLC0415

    from django.db.models import Sum  # noqa: PLC0415
    from django.utils import timezone  # noqa: PLC0415

    from mealtally.billing.models import Payment  # noqa: PLC0415

    since = timezone.now() - timedelta(days=30)
    got = Payment.objects.filter(received_at__gte=since).exclude(status="VOIDED").aggregate(t=Sum("amount_paise"))["t"]
    del _dt
    return int(got or 0)


def _console_dashboard(request, D, real):
    """D03.4 owner dashboard: KPI tiles, alerts, 12-month chart, delivery donut, portal / low wallets / shortcuts."""
    import base64  # noqa: PLC0415

    from django.db.models import Count  # noqa: PLC0415
    from django.urls import reverse  # noqa: PLC0415

    from mealtally.customers import qr as qrmod  # noqa: PLC0415
    from mealtally.ledger.models import MealLedgerEntry  # noqa: PLC0415

    from . import console  # noqa: PLC0415

    slug = request.tenant.slug
    months, last, _exp, _rec = util.money_series(D, _passes_30d(D))
    since = timezone.now() - timedelta(days=30)
    kinds = dict(
        MealLedgerEntry.objects.filter(occurred_at__gte=since, entry_type__in=["REDEEM", "REVERSAL"])
        .values_list("entry_type")
        .annotate(n=Count("id"))
    )
    pass_meals = max(0, kinds.get("REDEEM", 0) - kinds.get("REVERSAL", 0))
    delivered30 = len([o for o in D["orders"] if -30 < o["off"] <= 0 and o["status"] in ("DELIVERED", "PICKED_UP")])
    # QA-01 P1-2: "Active customers" = real customers with an active pass OR an active wallet, each counted once
    from mealtally.common.utils import format_phone  # noqa: PLC0415
    from mealtally.passes.models import Pass  # noqa: PLC0415

    pass_phones = {
        format_phone(p) for p in Pass.objects.filter(status="ACTIVE").values_list("customer__phone_e164", flat=True)
    }
    wallet_phones = {s["phone"] for s in D["subscribers"] if s["status"] == "ACTIVE"}
    active_customers = len(pass_phones | wallet_phones)
    todays = [o for o in data.day_orders(D, D["today"]) if o["status"] in util.LIVE]

    def done(rows):
        return len([o for o in rows if o["status"] in ("DELIVERED", "PICKED_UP")])

    home = [o for o in todays if o["method"] == "DELIVERY"]
    pick = [o for o in todays if o["method"] == "PICKUP"]
    low = sorted(
        [s for s in D["subscribers"] if s["status"] == "ACTIVE" and s["days_left"] <= 3],
        key=lambda s: s["balance_paise"],
    )
    portal = request.build_absolute_uri(reverse("web:tenant-home", args=[slug]))
    ratio = round(100 * last["expense_paise"] / last["revenue_paise"])
    tiles = [
        {
            "key": "customers",
            "label": "Active customers",
            "value": active_customers,
            "money": False,
            "url": reverse("web:admin-customers", args=[slug]),
            "icon": "customers",
            "hint": "passes + wallets",
        },
        {
            "key": "meals",
            "label": "Meals · 30 days",
            "value": pass_meals + delivered30,
            "money": False,
            "url": reverse("preview:orders", args=[slug]),
            "icon": "meals",
            "hint": "counter + delivered",
        },
        {
            "key": "revenue",
            "label": "Revenue · 30 days",
            "value": last["revenue_paise"],
            "money": True,
            "url": reverse("web:report-monthly", args=[slug]),
            "icon": "wallet",
            "hint": "passes + wallet meals",
        },
        {
            "key": "expenses",
            "label": "Expenses · 30 days",
            "value": last["expense_paise"],
            "money": True,
            "url": reverse("preview:expenses", args=[slug]),
            "icon": "expense",
            "hint": f"{ratio}% of revenue",
        },
    ]
    kitchen = reverse("preview:kitchen", args=[slug])
    shortcuts = [
        ("Redeem meal", reverse("web:staff-console", args=[slug]), "qr"),
        ("New customer", reverse("web:staff-customer-new", args=[slug]), "customers"),
        ("Sell pass", reverse("web:staff-sell", args=[slug]), "sell"),
        ("Record top-up", reverse("preview:wallets", args=[slug]), "wallet"),
        ("Kitchen sheet", kitchen, "kitchen"),
        ("Packing list", kitchen + "#pack", "orders"),
    ]
    return _page(
        request,
        "preview/today_console.html",
        D=D,
        tiles=tiles,
        fee=real["platform_fee_month_paise"],
        alerts=console.alerts(request, D),
        months=months,
        last=last,
        delivered=done(todays),
        pending=len(todays) - done(todays),
        home=(done(home), len(home)),
        pickup=(done(pick), len(pick)),
        dine_in=real["meals_today"],
        low=low[:5],
        portal=portal,
        portal_qr="data:image/svg+xml;base64," + base64.b64encode(qrmod.render_svg(portal)).decode(),
        shortcuts=shortcuts,
    )


@preview_view("today")
@require_GET
def today(request, D):
    real = reports.dashboard(actor=request.actor)
    if request.tenant.ui_shell == "console":
        return _console_dashboard(request, D, real)
    todays = data.day_orders(D, D["today"])
    by_slot = []
    for s in D["slots"]:
        rows = [o for o in todays if o["slot"] == s["key"]]
        by_slot.append(
            {
                "name": s["name"],
                "total": len([o for o in rows if o["status"] in util.LIVE]),
                "delivered": len([o for o in rows if o["status"] in ("DELIVERED", "PICKED_UP")]),
            }
        )
    live = [o for o in todays if o["status"] in util.LIVE]
    delivered = [o for o in live if o["status"] in ("DELIVERED", "PICKED_UP")]
    pickup = len([o for o in live if o["method"] == "PICKUP"])
    delivery = len([o for o in live if o["method"] == "DELIVERY"])
    months, last, _exp, _rec = util.money_series(D, _passes_30d(D))
    low = sorted(
        [s for s in D["subscribers"] if s["status"] == "ACTIVE" and s["days_left"] <= 3],
        key=lambda s: s["balance_paise"],
    )
    return _page(
        request,
        "preview/today.html",
        D=D,
        d=real,
        by_slot=by_slot,
        live=len(live),
        delivered=len(delivered),
        pending=len(live) - len(delivered),
        pickup=pickup,
        delivery=delivery,
        dine_in=real["meals_today"],
        low=low[:8],
        low_total=len(low),
        months=months,
        checklist=[{**c, "url": _cta(request.tenant.slug, c["key"])} for c in D["checklist"]],
        pct=D["checklist_pct"],
        tenant_slug=request.tenant.slug,
        last=last,
    )


@preview_view("today", roles=(Role.OWNER, Role.MANAGER, Role.STAFF, Role.CHEF, Role.DRIVER))
@require_GET
def more(request, D):
    slug = request.tenant.slug
    groups = {"top": [], "money": [], "more": []}
    for m in REGISTRY:
        if m.nav_group in groups and request.role in m.roles:
            groups[m.nav_group].append(
                {"title": m.title, "blurb": m.blurb, "url": module_url(m, slug), "preview": m.status == "preview"}
            )
    return _page(
        request,
        "preview/more.html",
        groups=groups,
        titles={"top": "Daily work", "money": "Money", "more": "Setup & settings"},
    )


# --- orders -----------------------------------------------------------------------------------------------------------------
@preview_view("orders")
@require_GET
def orders(request, D):
    default = D["today"]
    if timezone.localtime().time() >= D["slots"][2]["start"].replace(hour=D["slots"][2]["start"].hour - 1, minute=30):
        default = D["today"] + timedelta(days=1)  # after the last cutoff, the board that is still open is tomorrow's
    day = util.parse_date(request.GET.get("date"), default)
    rows = data.day_orders(D, day)
    slot_key = request.GET.get("slot") or ""
    summary = util.slot_summary(D, day, rows)
    active_slot = next((s for s in summary if s["key"] == slot_key), None) or next(
        (s for s in summary if s["key"] == "LUNCH"), summary[0]
    )
    shown = sorted(active_slot["orders"], key=lambda o: (o["status"] in ("DELIVERED", "PICKED_UP"), o["no"]))
    for s in summary:
        cutoff = util.iso(datetime.combine(day, s["start"]) - timedelta(minutes=s["cutoff_min"]))
        s["cutoff_iso"] = cutoff
    chips = {}
    for o in active_slot["orders"]:
        chips[o["status"]] = chips.get(o["status"], 0) + 1
    return _page(
        request,
        "preview/orders.html",
        D=D,
        day=day,
        days=util.day_links(D["today"], day),
        slots=summary,
        active=active_slot,
        rows=shown[:80],
        more_rows=max(0, len(shown) - 80),
        chips=sorted(chips.items(), key=lambda kv: -kv[1]),
        can_create=request.role in (Role.OWNER, Role.MANAGER, Role.STAFF),
        new_order_url=reverse("preview:orders-new", args=[request.tenant.slug]),
    )


@preview_view("orders", roles=(Role.OWNER, Role.MANAGER, Role.STAFF))
@require_GET
def order_new(request, D):
    customers = [
        {"name": s["name"], "phone": s["phone"], "bal": s["balance_paise"], "trust": s["trust_limit_paise"]}
        for s in D["subscribers"]
    ]
    return _page(
        request,
        "preview/order_new.html",
        D=D,
        customers=customers,
        dishes=D["dishes"][:12],
        today=D["today"].isoformat(),
        tomorrow=(D["today"] + timedelta(days=1)).isoformat(),
    )


@preview_view("orders")
@require_GET
def order_detail(request, D, no):
    o = D["order_by_no"].get(no)
    if o is None:
        raise Http404
    steps = ["Received", "Confirmed", "Dispatched", "Delivered"]
    pos = {
        "RECEIVED": 0,
        "CONFIRMED": 1,
        "PREPARING": 1,
        "READY": 2,
        "OUT_FOR_DELIVERY": 2,
        "DELIVERED": 3,
        "PICKED_UP": 3,
    }.get(o["status"], 0)
    nxt = {0: "Confirm order", 1: "Dispatch", 2: "Mark delivered"}.get(pos)
    if o["method"] == "PICKUP":
        steps = ["Received", "Confirmed", "Ready", "Picked up"]
        nxt = {0: "Confirm order", 1: "Mark ready", 2: "Hand over"}.get(pos)
    sub = D["sub"].get(o["sub_id"])
    return _page(
        request,
        "preview/order_detail.html",
        D=D,
        o=o,
        steps=list(enumerate(steps)),
        pos=pos,
        nxt=nxt,
        sub=sub,
        drivers=D["routes"],
        total=sum(it["qty"] * 0 for it in o["items"]) + o["amount_paise"],
    )


# --- kitchen ----------------------------------------------------------------------------------------------------------------
def _kitchen_ctx(D, request):
    day = util.parse_date(request.GET.get("date"), D["today"])
    rows = data.day_orders(D, day)
    summary = util.slot_summary(D, day, rows)
    slot_key = request.GET.get("slot") or "LUNCH"
    active = next((s for s in summary if s["key"] == slot_key), summary[1])
    return day, summary, active


@preview_view("kitchen")
@require_GET
def kitchen(request, D):
    day, summary, active = _kitchen_ctx(D, request)
    orders_ = [o for o in active["orders"] if o["status"] in util.LIVE]
    plan = util.cooking_plan(orders_)
    packing = sorted([o for o in orders_ if o["method"] == "DELIVERY"], key=lambda o: ((o["route"] or ""), o["stop"]))
    pickup = [o for o in orders_ if o["method"] == "PICKUP"]
    return _page(
        request,
        "preview/kitchen.html",
        D=D,
        day=day,
        slots=summary,
        active=active,
        plan=plan,
        options=util.split_by_option(orders_),
        packing=packing,
        pickup=pickup,
        total_meals=sum(r["qty"] for r in plan),
        allergen_orders=[o for o in orders_ if o["allergy"] or any(i["allergens"] for i in o["items"])],
    )


@preview_view("kitchen")
@require_GET
def kitchen_labels(request, D):
    day, summary, active = _kitchen_ctx(D, request)
    orders_ = sorted(
        [o for o in active["orders"] if o["status"] in util.LIVE], key=lambda o: ((o["route"] or "~"), o["stop"])
    )
    return _page(
        request, "preview/kitchen_labels.html", D=D, day=day, active=active, orders=orders_[:40], address_of=D["sub"]
    )


# --- delivery / driver --------------------------------------------------------------------------------------------------------
@preview_view("delivery")
@require_GET
def delivery(request, D):
    routes = []
    for r in D["routes"]:
        stops = [s for s in D["subscribers"] if s["route"] == r["name"] and s["status"] == "ACTIVE"]
        stops.sort(key=lambda s: s["stop"])
        routes.append({**r, "stops": stops})
    unassigned = [s for s in D["subscribers"] if s["method"] == "DELIVERY" and s["route"] is None]
    return _page(
        request,
        "preview/delivery.html",
        D=D,
        routes=routes,
        unassigned=unassigned,
        pickup_subs=[s for s in D["subscribers"] if s["method"] == "PICKUP"][:6],
        drivers=_driver_memberships(),
        notice=request.GET.get("saved") == "1",
    )


def _driver_memberships():
    from mealtally.accounts.models import Membership  # noqa: PLC0415
    from mealtally.accounts.models import Role  # noqa: PLC0415

    return list(Membership.objects.filter(role=Role.DRIVER, is_active=True).select_related("user").order_by("id"))


@preview_view("driver")
@require_GET
def driver(request, D):
    # QA-01 P1-4: each driver sees THEIR route (the owner previewing the console sees the first one)
    mine = None
    if request.role == "DRIVER":
        from mealtally.accounts.models import Membership  # noqa: PLC0415

        member = Membership.objects.filter(user=request.user, role="DRIVER", is_active=True).first()
        mine = member.route_name if member else None
    route = next((r for r in D["routes"] if r["name"] == mine), D["routes"][0])
    day = D["today"]
    todays = [o for o in data.day_orders(D, day) if o["slot"] == "LUNCH" and o["route"] == route["name"]]
    stops = sorted((o for o in todays if o["status"] in util.LIVE), key=lambda o: o["stop"])
    skipped = sorted((o for o in todays if o["status"] not in util.LIVE), key=lambda o: o["stop"])
    for o in stops + skipped:
        o["address"] = D["sub"][o["sub_id"]]["address"]
        o["tel"] = o["phone"].replace(" ", "")
        o["boxes"] = D["sub"][o["sub_id"]]["tiffin_boxes"]
    delivered = [o for o in stops if o["status"] == "DELIVERED"]
    pending = [o for o in stops if o["status"] != "DELIVERED"]  # the next stop is always first
    done = len(delivered)
    return _page(
        request,
        "preview/driver.html",
        D=D,
        route=route,
        stops=stops,
        pending=pending,
        delivered=delivered,
        skipped=skipped,
        done=done,
        total=len(stops),
        left=len(stops) - done,
        day=day,
    )


# --- holds / tiffin boxes --------------------------------------------------------------------------------------------------------
@preview_view("holds")
@require_GET
def holds(request, D):
    options = []
    for k in range(1, 8):
        day = D["today"] + timedelta(days=k)
        if day.weekday() == 6:
            continue
        rows = [o for o in data.day_orders(D, day) if o["status"] in ("RECEIVED", "CONFIRMED")]
        slots = sorted({o["slot"] for o in rows})
        options.append(
            {
                "date": day,
                "iso": day.isoformat(),
                "orders": len(rows),
                "slots": len(slots),
                "customers": len({o["sub_id"] for o in rows}),
            }
        )
    return _page(
        request,
        "preview/holds.html",
        D=D,
        holds=D["holds"],
        closures=D["closures"],
        options=options,
        subs=D["subscribers"][:10],
    )


@preview_view("tiffin-boxes")
@require_GET
def tiffin_boxes(request, D):
    return _page(
        request,
        "preview/tiffin_boxes.html",
        D=D,
        boxes=D["boxes"],
        over=[b for b in D["boxes"] if b["held"] > b["limit"]],
    )
