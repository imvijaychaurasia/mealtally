# SPDX-License-Identifier: AGPL-3.0-only
"""Deterministic demo dataset for the preview modules. Pure Python, no database.

``build(today, roster)`` is seeded: same inputs -> same data, and every date is relative to ``today`` so the demo always
looks current. Nothing here ever touches a real ledger.

The ``roster`` is the tenant's REAL data -- its customers (name, phone, address, wallet flag), its
meal slots and its drivers' routes -- so every name, address and route the preview pages show exists in that tenant.
Only customers flagged ``has_wallet`` are wallet subscribers. Without a roster (unit tests, the platform plans page) the
built-in demo names are used. Cached per (day, persona, roster).
"""

from __future__ import annotations

import hashlib
import random
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from functools import lru_cache

SEED = 20261114
_LIVE_STATUSES = ("RECEIVED", "CONFIRMED", "PREPARING", "READY", "OUT_FOR_DELIVERY", "DELIVERED", "PICKED_UP")
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DELIVERY_DAYS = [0, 1, 2, 3, 4, 5]  # Mon-Sat

SLOTS = [
    {"key": "BREAKFAST", "name": "Breakfast", "start": time(7, 30), "end": time(9, 30), "cutoff_min": 45},
    {"key": "LUNCH", "name": "Lunch", "start": time(12, 0), "end": time(14, 30), "cutoff_min": 60},
    {"key": "DINNER", "name": "Dinner", "start": time(19, 30), "end": time(21, 30), "cutoff_min": 60},
]

# key, name, diet (VEG/NONVEG/VEGAN/JAIN), allergens, category
DISHES = [
    ("dal-tadka", "Dal tadka", "VEG", [], "Main"),
    ("jeera-rice", "Jeera rice", "VEG", [], "Rice"),
    ("chapati", "Chapati", "VEG", ["gluten"], "Bread"),
    ("paneer-butter-masala", "Paneer butter masala", "VEG", ["dairy", "nuts"], "Main"),
    ("aloo-matar", "Aloo matar", "VEG", [], "Main"),
    ("mix-veg", "Mix veg", "VEG", [], "Main"),
    ("poha", "Poha", "VEG", ["nuts"], "Breakfast"),
    ("upma", "Upma", "VEG", ["gluten"], "Breakfast"),
    ("idli-sambar", "Idli sambar", "VEG", [], "Breakfast"),
    ("curd", "Curd", "VEG", ["dairy"], "Side"),
    ("salad", "Green salad", "VEGAN", [], "Side"),
    ("gulab-jamun", "Gulab jamun", "VEG", ["dairy", "gluten"], "Sweet"),
    ("egg-curry", "Egg curry", "NONVEG", ["egg"], "Main"),
    ("chicken-curry", "Chicken curry", "NONVEG", [], "Main"),
    ("millet-khichdi", "Millet khichdi", "VEGAN", [], "Main"),
    ("bhindi-masala", "Bhindi masala", "VEG", [], "Main"),
    ("rajma", "Rajma", "VEG", [], "Main"),
    ("chole", "Chole", "VEG", [], "Main"),
    ("palak-paneer", "Palak paneer", "VEG", ["dairy"], "Main"),
    ("lauki-sabzi", "Lauki sabzi (no onion-garlic)", "JAIN", [], "Main"),
    ("jain-dal", "Jain dal", "JAIN", [], "Main"),
]
DISH = {d[0]: d for d in DISHES}
# realistic a-la-carte prices (rupees; chapati is per piece)
DISH_PRICE = {
    "dal-tadka": 70,
    "jeera-rice": 50,
    "chapati": 10,
    "paneer-butter-masala": 140,
    "aloo-matar": 80,
    "mix-veg": 90,
    "poha": 40,
    "upma": 40,
    "idli-sambar": 60,
    "curd": 30,
    "salad": 30,
    "gulab-jamun": 40,
    "egg-curry": 100,
    "chicken-curry": 160,
    "millet-khichdi": 90,
    "bhindi-masala": 90,
    "rajma": 80,
    "chole": 85,
    "palak-paneer": 130,
    "lauki-sabzi": 80,
    "jain-dal": 70,
}

# Names: the first 8 subscribers are also real pass customers on demo-tiffin (consistent where they overlap).
PASS_NAMES = [
    "Anita Deshpande",
    "Rahul Kulkarni",
    "Sneha Patil",
    "Vikram Joshi",
    "Pooja Bhosale",
    "Amit Jadhav",
    "Kavita Shinde",
    "Sandeep More",
    "Neha Gokhale",
    "Rohan Pawar",
    "Priya Kale",
    "Manish Gaikwad",
    "Swati Chavan",
    "Nikhil Sawant",
    "Shruti Phadke",
    "Ajay Naik",
    "Madhuri Joshi",
    "Tejas Kamble",
    "Ritu Agarwal",
    "Harsh Mehta",
    "Divya Nair",
    "Omkar Salunkhe",
    "Meghna Bapat",
    "Yash Thakur",
    "Aarti Rane",
]
EXTRA_SUB_NAMES = [
    "Jyoti Iyer",
    "Kiran Dixit",
    "Lalita Menon",
    "Mohan Reddy",
    "Nandini Rao",
    "Prakash Hegde",
    "Radhika Sen",
    "Suresh Bhat",
    "Tanvi Kapoor",
    "Uday Mirajkar",
    "Varsha Tambe",
    "Waman Kelkar",
    "Yogesh Date",
    "Zoya Khan",
    "Arjun Menon",
    "Bhavna Shah",
    "Chetan Oak",
    "Deepa Hardikar",
    "Esha Gupta",
    "Farhan Sheikh",
    "Gauri Apte",
    "Hemant Limaye",
]
PASS_PHONE = "+91 90000 1{:04d}"  # pass customers: 10001..10025
SUB_PHONE = "+91 90000 1{:04d}"  # subscribers: first 8 reuse pass customers' numbers, the rest 10108..
LOCALITIES = ["Kothrud", "Karve Nagar", "Erandwane", "Warje", "Baner", "Aundh", "Bavdhan", "Paud Road"]
STREETS = ["Lane 3", "Shivaji Society", "Gandhi Nagar", "Om Residency", "Sai Park", "Ganesh Apartments", "Rutu Heights"]

WALLET_PLANS = [
    {"id": "HT-L", "name": "Home tiffin, lunch only", "daily_minor": 8000, "slots": ["LUNCH"], "jain": False},
    {
        "id": "HT-LD",
        "name": "Home tiffin, lunch and dinner",
        "daily_minor": 15000,
        "slots": ["LUNCH", "DINNER"],
        "jain": False,
    },
    {"id": "JAIN", "name": "Jain thali", "daily_minor": 9500, "slots": ["LUNCH"], "jain": True},
]
PLAN = {p["id"]: p for p in WALLET_PLANS}

LUNCH_COMBOS = [
    ["dal-tadka", "jeera-rice", "chapati", "salad"],
    ["paneer-butter-masala", "chapati", "jeera-rice", "curd"],
    ["aloo-matar", "dal-tadka", "chapati", "salad"],
    ["rajma", "jeera-rice", "chapati", "curd"],
    ["mix-veg", "dal-tadka", "chapati", "salad"],
    ["chole", "jeera-rice", "chapati", "salad"],
    ["palak-paneer", "chapati", "jeera-rice", "curd"],
    ["bhindi-masala", "dal-tadka", "chapati", "salad"],
]
ALT_COMBOS = [
    ["egg-curry", "jeera-rice", "chapati", "salad"],
    ["millet-khichdi", "curd", "salad"],
    ["chicken-curry", "jeera-rice", "chapati"],
    ["millet-khichdi", "mix-veg", "salad"],
]
DINNER_COMBOS = [
    ["mix-veg", "dal-tadka", "chapati", "curd"],
    ["paneer-butter-masala", "chapati", "salad"],
    ["aloo-matar", "jeera-rice", "chapati", "salad"],
    ["rajma", "chapati", "curd"],
    ["millet-khichdi", "curd", "gulab-jamun"],
    ["bhindi-masala", "dal-tadka", "chapati"],
]
JAIN_COMBOS = [["lauki-sabzi", "jain-dal", "chapati", "salad"], ["jain-dal", "jeera-rice", "chapati", "curd"]]
BREAKFAST_COMBOS = [["poha", "curd"], ["upma", "salad"], ["idli-sambar"], ["poha", "gulab-jamun"]]


def qty_label(item):
    k, q = item
    return f"{DISH[k][1]} ×{q}" if q > 1 else DISH[k][1]


def _combo_items(keys):
    return [(k, 4 if k == "chapati" else 1) for k in keys]


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def _fmt_item(k, q):
    return {"key": k, "name": DISH[k][1], "qty": q, "diet": DISH[k][2], "allergens": DISH[k][3]}


def _weekly_menu(plan, salt=0):
    """{weekday: {slot: [option, ...]}} where option = list of items. 1-2 alternatives per day."""
    menu = {}
    for wd in DELIVERY_DAYS:
        day = {}
        for slot in plan["slots"]:
            if plan["jain"]:
                opts = [JAIN_COMBOS[wd % 2]]
            elif slot == "LUNCH":
                opts = [LUNCH_COMBOS[(wd * 3 + len(plan["id"]) + salt) % 8]]
                if wd % 2 == 0:
                    opts.append(ALT_COMBOS[(wd // 2) % 4])
            else:
                opts = [DINNER_COMBOS[(wd + 2 + salt) % 6]]
                if wd % 3 == 0:
                    opts.append(ALT_COMBOS[(wd + 1) % 4])
            day[slot] = [[_fmt_item(k, q) for k, q in _combo_items(o)] for o in opts]
        menu[wd] = day
    return menu


class Real(str):
    """A string that came from the tenant's own records: persona localisation must leave it untouched."""

    __slots__ = ()


def _money_round(p, step=10000):
    return int(round(p / step)) * step


def build(today: date, roster=None) -> dict:  # noqa: C901, PLR0912, PLR0915
    """``roster`` = (customers, slots, drivers, salt): customers ((name, phone, address, has_wallet), ...), slots
    ((KEY, name, start, end), ...), drivers ((name, phone, route, vehicle), ...), salt (int, varies dish totals)."""
    rng = random.Random(SEED)
    D = {"today": today, "weekdays": WEEKDAYS}
    r_customers, r_slots, r_drivers, salt = roster or ((), (), (), 0)
    D["real"] = roster is not None

    D["branches"] = [
        {
            "id": 1,
            "name": "Kothrud kitchen",
            "main": True,
            "pickup": True,
            "lat": 18.5074,
            "lng": 73.8077,
            "radius_km": 6,
            "address": "Shop 4, Shivaji Society, Kothrud, Pune 411038",
            "phone": "+91 20 4000 1101",
        },
        {
            "id": 2,
            "name": "Baner pick-up point",
            "main": False,
            "pickup": True,
            "lat": 18.5590,
            "lng": 73.7868,
            "radius_km": 3,
            "address": "Near Baner Road, Pune 411045",
            "phone": "+91 20 4000 1102",
        },
    ]
    real_slots = {k: (name, start, end) for k, name, start, end in r_slots}
    slot_rows = [
        {**s, "name": real_slots[s["key"]][0], "start": real_slots[s["key"]][1], "end": real_slots[s["key"]][2]}
        if s["key"] in real_slots
        else dict(s)
        for s in SLOTS
    ]
    D["slots"] = [
        {
            **s,
            "start_s": s["start"].strftime("%H:%M"),
            "end_s": s["end"].strftime("%H:%M"),
            "cutoff_s": (datetime.combine(today, s["start"]) - timedelta(minutes=s["cutoff_min"])).strftime("%H:%M"),
        }
        for s in slot_rows
    ]
    D["slot"] = {s["key"]: s for s in D["slots"]}
    D["dishes"] = [
        {"key": k, "name": n, "diet": d, "allergens": a, "category": c, "price": DISH_PRICE.get(k, 60)}
        for k, n, d, a, c in DISHES
    ]
    D["wallet_plans"] = [
        {
            **p,
            "weekly_minor": p["daily_minor"] * 7,
            "monthly_minor": p["daily_minor"] * 30,
            "menu": _weekly_menu(p, salt),
            "delivery_days": DELIVERY_DAYS,
        }
        for p in WALLET_PLANS
    ]
    D["wplan"] = {p["id"]: p for p in D["wallet_plans"]}
    D["breakfast_options"] = BREAKFAST_COMBOS

    # ---- subscribers ------------------------------------------------------------------------------------
    if roster is not None:
        wallet_people = [c for c in r_customers if c[3]]
    else:
        wallet_people = [
            (nm, PASS_PHONE.format(n) if n <= 8 else SUB_PHONE.format(100 + n), "", True)  # noqa: PLR2004
            for n, nm in enumerate(PASS_NAMES[:8] + EXTRA_SUB_NAMES, 1)
        ]
    subs = []
    plan_cycle = ["HT-L", "HT-LD", "HT-L", "JAIN", "HT-LD", "HT-L"]
    plan_cycle = plan_cycle[salt % 6 :] + plan_cycle[: salt % 6]
    kinds = {}  # low / negative / paused / vacation / cancelled / expired
    for i in (3, 9, 14, 20, 26):
        kinds[i] = "low"
    for i in (6, 17):
        kinds[i] = "negative"
    for i in (4, 12):
        kinds[i] = "vacation"
    kinds[8] = "paused"
    kinds[29] = "cancelled"
    kinds[30] = "expired"
    route_names = [d[2] for d in r_drivers if d[2]] or ["Kothrud A", "Kothrud B"]
    for n, (person_name, phone, person_address, _w) in enumerate(wallet_people, 1):
        plan = PLAN[plan_cycle[(n - 1) % 6]]
        qty = dict.fromkeys(DELIVERY_DAYS, 1)
        if n % 5 == 0:
            qty = dict.fromkeys(DELIVERY_DAYS, 2)
        elif n % 7 == 0:
            qty = {wd: (2 if wd in (1, 3) else 1) for wd in DELIVERY_DAYS}
        method = "PICKUP" if n % 4 == 0 else "DELIVERY"
        route = None if method == "PICKUP" else route_names[(n - 1) % len(route_names)]
        kind = kinds.get(n, "active")
        subs.append(
            {
                "id": 200 + n,
                "n": n,
                "name": person_name,
                "phone": phone,
                "plan": plan["id"],
                "qty": qty,
                "method": method,
                "route": route,
                "kind": kind,
                "status": {"paused": "PAUSED", "cancelled": "CANCELLED", "expired": "EXPIRED"}.get(kind, "ACTIVE"),
                "paid": kind not in ("negative",) and n % 11 != 0,
                "billing": "MONTHLY" if n % 3 else "WEEKLY",
                "skip_limit": 5,
                "skips_used": (n * 2) % 5 if n % 3 else 5 if n == 7 else 1,
                "start": today - timedelta(days=rng.randint(40, 200)),
                "end": None,
                "trial": n in (13, 21),
                "address": person_address
                or f"{rng.randint(2, 48)}, {STREETS[n % len(STREETS)]}, {LOCALITIES[n % len(LOCALITIES)]}, Pune",
                "notes": {
                    2: "Less spicy",
                    5: "No onion-garlic",
                    10: "Extra salad, no curd",
                    15: "Ring bell twice",
                    18: "Leave with security",
                    23: "Allergic to nuts. Please check.",
                }.get(n, ""),
                "allergy": "nuts" if n == 23 else "",
                "stop": 0,
                "tiffin_boxes": 2 if n % 6 == 0 else 1 if method == "DELIVERY" else 0,
                "trust_limit_minor": 20000,
                "trust_limit": True,
                "hold": None,
            }
        )
    for s in subs:
        if s["kind"] == "vacation":
            s["hold"] = {
                "start": today + timedelta(days=-1 if s["n"] == 4 else 2),
                "end": today + timedelta(days=5 if s["n"] == 4 else 9),
                "reason": "Out of town",
            }
    # stop order on routes
    for route in route_names:
        k = 1
        for s in subs:
            if s["route"] == route:
                s["stop"] = k
                k += 1
    D["subscribers"] = subs
    D["sub"] = {s["id"]: s for s in subs}
    D["featured_sub_id"] = subs[0]["id"] if subs else None
    D["sub_by_phone"] = {s["phone"]: s["id"] for s in subs}

    # ---- orders + wallet ledgers ---------------------------------------------------------------------------
    default_routes = [
        {
            "id": "A",
            "name": "Kothrud A",
            "driver": "Ramesh Gawade",
            "driver_phone": "+91 90000 12001",
            "vehicle": "MH12 AB 4021",
        },
        {
            "id": "B",
            "name": "Kothrud B",
            "driver": "Sunil Bhor",
            "driver_phone": "+91 90000 12002",
            "vehicle": "MH12 CD 7718",
        },
    ]
    if r_drivers and any(d[2] for d in r_drivers):
        D["routes"] = [
            {"id": chr(65 + i), "name": route, "driver": name, "driver_phone": phone, "vehicle": vehicle}
            for i, (name, phone, route, vehicle) in enumerate(d for d in r_drivers if d[2])
        ]
    else:
        D["routes"] = default_routes
    D["drivers"] = [{"name": d[0], "phone": d[1], "route": d[2], "vehicle": d[3]} for d in r_drivers]
    route_driver = {r["name"]: r for r in D["routes"]}
    now_dt = datetime.combine(today, time(11, 0))
    orders = []
    order_no = 5200
    ledger_by_sub = {s["id"]: [] for s in subs}
    first_day = today - timedelta(days=74)
    for s in subs:
        plan = PLAN[s["plan"]]
        per_slot_minor = plan["daily_minor"] // len(plan["slots"])
        debits = []
        for off in range(-74, 7):
            d = today + timedelta(days=off)
            wd = d.weekday()
            if wd not in DELIVERY_DAYS:
                continue
            if s["kind"] == "expired" and off > -30:
                continue
            if s["kind"] == "cancelled" and off > -12:
                continue
            if s["kind"] == "paused" and off > -6:
                continue
            on_hold = bool(s["hold"] and s["hold"]["start"] <= d <= s["hold"]["end"])
            for slot in plan["slots"]:
                menu_opts = D["wplan"][s["plan"]]["menu"][wd][slot]
                pick = 1 if (len(menu_opts) > 1 and _h(s["id"], d, slot) % 4 == 0) else 0
                items = menu_opts[pick]
                qty = s["qty"][wd]
                order_no += 1
                amount = per_slot_minor * qty
                slot_info = D["slot"][slot]
                start_dt = datetime.combine(d, D["slot"][slot]["start"])
                cutoff_dt = start_dt - timedelta(minutes=slot_info["cutoff_min"])
                end_dt = datetime.combine(d, D["slot"][slot]["end"])
                status = "DELIVERED" if s["method"] == "DELIVERY" else "PICKED_UP"
                if on_hold:
                    status = "SKIPPED_HOLD"
                elif off < 0 and _h(s["id"], d, slot, "x") % 40 == 0:
                    status = "CANCELLED"
                elif off < 0 and _h(s["id"], d, slot, "y") % 31 == 0:
                    status = "SKIPPED"  # customer used one of their skips
                elif off == 0:
                    if now_dt < cutoff_dt:
                        status = "RECEIVED"
                    elif now_dt < start_dt:
                        status = "CONFIRMED"
                    elif now_dt < start_dt + timedelta(minutes=40):
                        status = "PREPARING"
                    elif now_dt < end_dt:
                        status = "OUT_FOR_DELIVERY" if s["method"] == "DELIVERY" else "READY"
                    else:
                        status = "DELIVERED" if s["method"] == "DELIVERY" else "PICKED_UP"
                elif off > 0:
                    status = "RECEIVED"
                # the demo is read at any hour: pin today's lunch/dinner to a lively spread
                if off == 0:
                    status = ["CONFIRMED", "PREPARING", "READY", "OUT_FOR_DELIVERY", "DELIVERED", "RECEIVED"][
                        _h(s["id"], slot, "today") % 6
                    ]
                    if s["method"] == "PICKUP" and status == "OUT_FOR_DELIVERY":
                        status = "READY"
                    if s["method"] == "DELIVERY" and status == "PICKED_UP":
                        status = "DELIVERED"
                    if on_hold:
                        status = "SKIPPED_HOLD"
                charged = (
                    status in ("DELIVERED", "PICKED_UP", "OUT_FOR_DELIVERY", "READY", "PREPARING", "CONFIRMED")
                    and off <= 0
                )
                order = {
                    "no": order_no,
                    "date": d,
                    "off": off,
                    "slot": slot,
                    "sub_id": s["id"],
                    "customer": s["name"],
                    "phone": s["phone"],
                    "type": "Subscription",
                    "plan": plan["name"],
                    "items": items,
                    "qty": qty,
                    "status": status,
                    "method": s["method"],
                    "route": s["route"],
                    "stop": s["stop"],
                    "driver": route_driver[s["route"]]["driver"] if s["route"] in route_driver else None,
                    "amount_minor": amount,
                    "paid": True,
                    "notes": s["notes"],
                    "allergy": s["allergy"],
                    "pod": status == "DELIVERED" and off <= 0 and s["method"] == "DELIVERY",
                    "created_by": "System (cutoff)",
                    "created_dt": cutoff_dt,
                    "cutoff_dt": cutoff_dt,
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                }
                orders.append(order)
                if charged:
                    debits.append((d, slot, order))
        # ---- wallet simulation ------------------------------------------------------------------------------
        rate = plan["daily_minor"]
        entries = []
        bal = 0
        kind = s["kind"]
        total_after = sum(o["amount_minor"] for d, sl, o in debits if d >= today - timedelta(days=11))
        target = {"low": 6000 + (s["n"] % 4) * 2500, "negative": -(4000 + (s["n"] % 3) * 2500)}.get(kind)
        events = []
        for d, slot, o in debits:
            events.append(
                (
                    datetime.combine(d, D["slot"][slot]["start"]) + timedelta(minutes=5),
                    "DEBIT",
                    o,
                )
            )
        events.sort(key=lambda e: e[0])
        credit_plan = {}
        if target is not None:
            before = sum(o["amount_minor"] for d, sl, o in debits if d < today - timedelta(days=11))
            first_amt = max(_money_round(before * 0.9, 50000), 50000)
            credit_plan[first_day] = first_amt
            last_amt = max(0, total_after + target - (first_amt - before))
            credit_plan[today - timedelta(days=11)] = _money_round(last_amt, 5000) or 0
        timeline = list(events)
        for d, amt in credit_plan.items():
            if amt > 0:
                timeline.append((datetime.combine(d, time(9, 30)), "CREDIT", amt))
        if target is None:
            timeline.append((datetime.combine(first_day, time(9, 30)), "CREDIT", 40 * rate))
        timeline.sort(key=lambda e: (e[0], 0 if e[1] == "CREDIT" else 1))
        for dt, typ, payload in timeline:
            if typ == "CREDIT":
                bal += payload
                entries.append(
                    {
                        "dt": dt,
                        "type": "CREDIT",
                        "amount_minor": payload,
                        "desc": f"UPI top-up · UTR {_h(s['id'], dt, 'utr') % 10**12:012d}",
                        "source": "Top-up request",
                        "bal_minor": bal,
                    }
                )
            else:
                o = payload
                if target is None and bal < 3 * rate:
                    top = _money_round(25 * rate, 50000)
                    bal += top
                    entries.append(
                        {
                            "dt": dt - timedelta(minutes=30),
                            "type": "CREDIT",
                            "amount_minor": top,
                            "desc": f"UPI top-up · UTR {_h(s['id'], dt, 'utr2') % 10**12:012d}",
                            "source": "Top-up request",
                            "bal_minor": bal,
                        }
                    )
                bal -= o["amount_minor"]
                entries.append(
                    {
                        "dt": dt,
                        "type": "DEBIT",
                        "amount_minor": o["amount_minor"],
                        "desc": f"{o['plan'].split(', ')[0]} · {D['slot'][o['slot']]['name']}",
                        "source": f"Order #{o['no']}",
                        "order_no": o["no"],
                        "bal_minor": bal,
                    }
                )
        ledger_by_sub[s["id"]] = entries
        s["balance_minor"] = bal
        s["daily_minor"] = rate
        s["days_left"] = max(0, bal // rate) if rate else 0
    # a driver works down the route: of today's live lunch stops on each route the first N are the delivered ones
    # (N is however many the spread above produced), the rest keep their statuses in stop order
    for route_name in {o["route"] for o in orders if o["route"]}:
        todays = sorted(
            (
                o
                for o in orders
                if o["off"] == 0 and o["slot"] == "LUNCH" and o["route"] == route_name and o["status"] in _LIVE_STATUSES
            ),
            key=lambda o: o["stop"],
        )
        n_done = sum(1 for o in todays if o["status"] == "DELIVERED")
        rest = [o["status"] for o in todays if o["status"] != "DELIVERED"]
        for i, o in enumerate(todays):
            o["status"] = "DELIVERED" if i < n_done else rest[i - n_done]
            o["pod"] = o["status"] == "DELIVERED"
    D["orders"] = orders
    D["order_by_no"] = {o["no"]: o for o in orders}
    D["ledgers"] = ledger_by_sub
    for o in orders:  # low-wallet skipped orders (shown on the board)
        sub = D["sub"][o["sub_id"]]
        if o["off"] == 1 and sub["balance_minor"] < -sub["trust_limit_minor"] // 2 and sub["kind"] == "negative":
            o["status"] = "SKIPPED_LOW_WALLET"
    # a couple of manual counter / on-demand orders today
    thali = [_fmt_item(k, q) for k, q in (("dal-tadka", 1), ("jeera-rice", 1), ("chapati", 4), ("salad", 1))]
    pbm = [_fmt_item("paneer-butter-masala", 1), _fmt_item("chapati", 4)]
    od = [
        ("Walk-in", "", thali, 2, "PICKUP", 16000, "CONFIRMED"),
    ]
    if subs:
        od.append((subs[0]["name"], subs[0]["phone"], pbm, 1, "DELIVERY", 12000, "OUT_FOR_DELIVERY"))
    for who, ph, comps, oqty, meth, amt, st in od:
        order_no += 1
        orders.append(
            {
                "no": order_no,
                "date": today,
                "off": 0,
                "slot": "LUNCH",
                "sub_id": None,
                "customer": who,
                "phone": ph,
                "type": "On-demand",
                "plan": "—",
                "items": comps,  # components, so the kitchen's cooking plan rolls chapati into Chapati
                "qty": oqty,
                "status": st,
                "method": meth,
                "route": None,
                "stop": 0,
                "driver": None,
                "amount_minor": amt,
                "paid": meth == "PICKUP",
                "notes": "",
                "allergy": "",
                "pod": False,
                "created_by": "Counter staff: Seema Pawar",
                "created_dt": datetime.combine(today, time(10, 40)),
                "cutoff_dt": None,
                "start_dt": None,
                "end_dt": None,
            }
        )
    D["order_by_no"] = {o["no"]: o for o in orders}

    # ---- top-up requests ------------------------------------------------------------------------------------
    tops = []
    spec = [
        (3, 50000, "PENDING", 0),
        (9, 100000, "PENDING", 0),
        (6, 30000, "PENDING", 0),
        (14, 100000, "APPROVED", -1),
        (20, 50000, "APPROVED", -2),
        (17, 20000, "REJECTED", -3),
    ]
    spec = [row for row in spec if row[0] <= len(subs)]
    for i, (n, amt, st, off) in enumerate(spec, 1):
        tops.append(
            {
                "id": 900 + i,
                "sub_id": 200 + n,
                "customer": subs[n - 1]["name"],
                "amount_minor": amt,
                "status": st,
                "utr": f"{_h('utr', i) % 10**12:012d}",
                "method": "UPI",
                "created": datetime.combine(today + timedelta(days=off), time(9 + i, 12)),
                "reason": "UTR not found in bank statement" if st == "REJECTED" else "",
            }
        )
    D["topups"] = tops

    # ---- invoices (previous calendar month) -------------------------------------------------------------------
    first_this = today.replace(day=1)
    prev_last = first_this - timedelta(days=1)
    prev_first = prev_last.replace(day=1)
    invoices = []
    for s in subs:
        lines = {}
        for o in orders:
            if (
                o["sub_id"] == s["id"]
                and prev_first <= o["date"] <= prev_last
                and o["status"] in ("DELIVERED", "PICKED_UP")
            ):
                lines.setdefault(o["date"], []).append(o)
        if not lines:
            continue
        rows = []
        for d in sorted(lines):
            for o in lines[d]:
                rows.append(
                    {
                        "date": d,
                        "desc": f"{D['slot'][o['slot']]['name']}: " + ", ".join(i["name"] for i in o["items"][:3]),
                        "qty": o["qty"],
                        "amount_minor": o["amount_minor"],
                    }
                )
        extras = []
        if s["n"] % 4 == 1:
            extras.append(
                {
                    "date": prev_first + timedelta(days=9),
                    "desc": "Extra: Gulab jamun ×2",
                    "qty": 2,
                    "amount_minor": 4000,
                }
            )
        topup_total = sum(
            e["amount_minor"]
            for e in D["ledgers"][s["id"]]
            if e["type"] == "CREDIT" and prev_first <= e["dt"].date() <= prev_last
        )
        meals_total = sum(r["amount_minor"] for r in rows)
        extras_total = sum(e["amount_minor"] for e in extras)
        closing = [e for e in D["ledgers"][s["id"]] if e["dt"].date() <= prev_last]
        closing_bal = closing[-1]["bal_minor"] if closing else 0
        invoices.append(
            {
                "id": f"INV-{prev_first:%y%m}-{s['n']:04d}",
                "sub_id": s["id"],
                "customer": s["name"],
                "phone": s["phone"],
                "period": f"{prev_first:%d %b} – {prev_last:%d %b %Y}",
                "month": f"{prev_first:%B %Y}",
                "rows": rows,
                "extras": extras,
                "lines": sorted([*rows, *extras], key=lambda r: r["date"]),  # extras sit under the day they happened
                "meals_total_minor": meals_total,
                "extras_total_minor": extras_total,
                "topups_minor": topup_total,
                "opening_minor": closing_bal + meals_total + extras_total - topup_total,
                "closing_minor": closing_bal,
                "total_minor": meals_total + extras_total,
                "status": "PAID" if s["paid"] else "DUE",
                "issued": prev_last + timedelta(days=1),
                "address": s["address"],
            }
        )
    D["invoices"] = invoices
    D["invoice"] = {i["id"]: i for i in invoices}

    # ---- holds & closures -------------------------------------------------------------------------------------
    D["holds"] = [
        {"sub_id": s["id"], "customer": s["name"], **s["hold"], "plan": PLAN[s["plan"]]["name"]}
        for s in subs
        if s["hold"]
    ]
    D["closures"] = [{"date": today - timedelta(days=19), "reason": "Diwali", "orders": 41, "notified": True}]

    # ---- tiffin boxes -------------------------------------------------------------------------------------------
    boxes = []
    for s in subs:
        if s["method"] == "DELIVERY":
            issued = 1 + (s["n"] % 3 == 0) + (s["n"] == 6)
            returned = max(0, issued - (1 if s["n"] % 2 else 0))
            boxes.append(
                {
                    "sub_id": s["id"],
                    "customer": s["name"],
                    "held": issued - returned + (1 if s["n"] % 2 else 0),
                    "limit": 2,
                    "entries": [
                        {
                            "date": today - timedelta(days=30 - k),
                            "kind": "ISSUED" if k % 2 == 0 else "RETURNED",
                            "qty": 1,
                            "by": "Ramesh Gawade",
                        }
                        for k in range(4)
                    ],
                }
            )
    for b in boxes:
        b["held"] = (D["sub"][b["sub_id"]]["tiffin_boxes"]) + (
            1 if b["sub_id"] == 206 else 0
        )  # sub 6 is over the limit
    D["boxes"] = boxes

    # ---- expenses & profit ----------------------------------------------------------------------------------------
    cats = [
        ("Vegetables & groceries", 1200, 4500),
        ("Gas cylinders", 1800, 2600),
        ("Milk & curd", 900, 1300),
        ("Packaging", 400, 1500),
        ("Fuel (delivery)", 500, 1400),
        ("Salaries", 12000, 16000),
        ("Rent", 28000, 28000),
        ("Utilities", 2200, 3400),
        ("Maintenance", 300, 4000),
    ]
    expenses = []
    for i in range(40):
        cat, lo, hi = cats[i % len(cats)]
        amt = rng.randint(lo, hi) * 100
        expenses.append(
            {
                "id": 3000 + i,
                "date": today - timedelta(days=(i * 3 + rng.randint(0, 2)) % 60),
                "category": cat,
                "amount_minor": amt,
                "note": {
                    "Rent": "Kothrud kitchen rent",
                    "Gas cylinders": "Commercial LPG ×2",
                    "Salaries": "Kitchen staff + drivers",
                    "Milk & curd": "Daily milk vendor",
                }.get(cat, "Weekly purchase"),
                "paid_via": ["Cash", "UPI", "Bank"][i % 3],
                "receipt": i % 3 != 2,
                "branch": "Kothrud kitchen",
            }
        )
    expenses.sort(key=lambda e: e["date"], reverse=True)
    D["expenses"] = expenses
    D["recurring"] = [
        {"name": "Kitchen rent", "category": "Rent", "amount_minor": 2800000, "every": "Monthly · 1st"},
        {"name": "Salaries", "category": "Salaries", "amount_minor": 1450000, "every": "Monthly · 5th"},
        {"name": "Commercial LPG", "category": "Gas cylinders", "amount_minor": 220000, "every": "Weekly · Mon"},
        {"name": "Milk vendor", "category": "Milk & curd", "amount_minor": 110000, "every": "Daily"},
    ]
    months = []
    m = today.replace(day=1)
    seq = []
    for k in range(11, -1, -1):
        y, mo = m.year, m.month - k
        while mo <= 0:
            mo += 12
            y -= 1
        seq.append((y, mo))
    for idx, (y, mo) in enumerate(seq):
        growth = 1 + idx * 0.07
        rev = int((95000 + (_h("rev", y, mo) % 12000)) * growth) * 100
        exp = int(rev * (0.62 + (_h("exp", y, mo) % 9) / 100))
        months.append(
            {
                "label": date(y, mo, 1).strftime("%b %y"),
                "revenue_minor": rev,
                "expense_minor": exp,
                "profit_minor": rev - exp,
            }
        )
    D["months"] = months

    # ---- notifications ------------------------------------------------------------------------------------------------
    D["events"] = [
        {
            "key": "order_confirmed",
            "name": "Order confirmed",
            "text": "Hi {customer_name}, your {slot} order for {date} is confirmed. Balance: {wallet_balance}.",
            "ch": {"in_app": 1, "push": 1, "email": 0, "whatsapp": 1, "sms": 0},
        },
        {
            "key": "out_for_delivery",
            "name": "Out for delivery",
            "text": "{driver_name} is on the way with your {slot}. Track: {tracking_link}",
            "ch": {"in_app": 1, "push": 1, "email": 0, "whatsapp": 1, "sms": 1},
        },
        {
            "key": "delivered",
            "name": "Delivered",
            "text": "Your {slot} was delivered at {time}. Photo proof: {pod_link}",
            "ch": {"in_app": 1, "push": 0, "email": 0, "whatsapp": 1, "sms": 0},
        },
        {
            "key": "low_balance",
            "name": "Low wallet balance",
            "text": "Your wallet has {wallet_balance} (about {days_left} days). Top up on {topup_link} to avoid skipped meals.",
            "ch": {"in_app": 1, "push": 1, "email": 1, "whatsapp": 1, "sms": 1},
        },
        {
            "key": "topup_approved",
            "name": "Top-up approved",
            "text": "We received {amount}. New balance: {wallet_balance}.",
            "ch": {"in_app": 1, "push": 1, "email": 1, "whatsapp": 1, "sms": 0},
        },
        {
            "key": "topup_rejected",
            "name": "Top-up rejected",
            "text": "We could not match your payment (UTR {utr}). Reason: {reason}.",
            "ch": {"in_app": 1, "push": 1, "email": 0, "whatsapp": 1, "sms": 0},
        },
        {
            "key": "hold_started",
            "name": "Hold scheduled",
            "text": "Your meals are on hold from {hold_start} to {hold_end}.",
            "ch": {"in_app": 1, "push": 0, "email": 0, "whatsapp": 0, "sms": 0},
        },
        {
            "key": "pass_expiring",
            "name": "Pass expiring",
            "text": "{meals_left} meals on your pass expire on {expiry_date}. Renew at the counter.",
            "ch": {"in_app": 1, "push": 1, "email": 0, "whatsapp": 1, "sms": 0},
        },
        {
            "key": "closure",
            "name": "Restaurant closure",
            "text": "We will be closed on {date} ({reason}). Orders are skipped without charge.",
            "ch": {"in_app": 1, "push": 1, "email": 1, "whatsapp": 1, "sms": 1},
        },
        {
            "key": "menu_published",
            "name": "Weekly menu published",
            "text": "Next week's menu is ready: {menu_link}",
            "ch": {"in_app": 1, "push": 1, "email": 0, "whatsapp": 0, "sms": 0},
        },
    ]
    D["placeholders"] = [
        "customer_name",
        "slot",
        "date",
        "wallet_balance",
        "days_left",
        "driver_name",
        "tracking_link",
        "amount",
        "utr",
        "reason",
        "meals_left",
        "expiry_date",
        "hold_start",
        "hold_end",
        "topup_link",
        "time",
        "pod_link",
        "menu_link",
    ]

    def who(i):  # bell entries name real subscribers, never invented names
        return subs[i % len(subs)]["name"] if subs else "a customer"

    lead_driver = D["routes"][0]["driver"].split(" ")[0] if D["routes"] else "The driver"
    bell = [
        (f"Top-up request ₹1,000 from {who(8)}", 12),
        ("Order #5%d delivered. Photo proof attached." % (order_no % 100), 25),
        (f"Low wallet: {who(2)} (₹60 left)", 48),
        (f"Top-up ₹500 approved for {who(10)}", 90),
        (f"Hold started: {who(3)}", 130),
        (f"Pass expiring in 2 days: {who(6)}", 200),
        (f"New subscription: {who(11)}", 260),
        (f"Driver {lead_driver} marked 12 stops delivered", 300),
        ("Weekly menu published", 420),
        ("Order #5%d skipped: low wallet" % ((order_no - 7) % 100), 480),
        (f"5-star rating from {who(0)}", 600),
        ("Expense added: LPG ×2 ₹4,400", 700),
        ("New top-up request from Harsh Mehta", 820),
        ("Invoice INV-%s-0003 viewed" % prev_first.strftime("%y%m"), 900),
        ("Tiffin box limit reached: Kavita Shinde", 1000),
    ]
    D["bell"] = [{"text": t, "ago_min": m} for t, m in bell]

    # ---- cloud kitchen ------------------------------------------------------------------------------------------------------
    D["ck_items"] = [
        {
            "name": "Paneer butter masala + 4 chapati",
            "price_minor": 17000,
            "diet": "VEG",
            "hours": "12:00–22:00",
            "sold_out": False,
        },
        {
            "name": "Chicken curry rice bowl",
            "price_minor": 19000,
            "diet": "NONVEG",
            "hours": "12:00–22:00",
            "sold_out": False,
        },
        {"name": "Veg thali (mini)", "price_minor": 12000, "diet": "VEG", "hours": "12:00–15:00", "sold_out": False},
        {"name": "Egg bhurji pav", "price_minor": 9000, "diet": "NONVEG", "hours": "07:30–11:00", "sold_out": True},
        {"name": "Dal khichdi + papad", "price_minor": 11000, "diet": "VEG", "hours": "12:00–22:00", "sold_out": False},
        {"name": "Poha plate", "price_minor": 5000, "diet": "VEG", "hours": "07:30–11:00", "sold_out": False},
        {
            "name": "Millet khichdi bowl",
            "price_minor": 13000,
            "diet": "VEGAN",
            "hours": "12:00–22:00",
            "sold_out": True,
        },
        {"name": "Gulab jamun (2 pc)", "price_minor": 4000, "diet": "VEG", "hours": "All day", "sold_out": False},
        {"name": "Masala chaas", "price_minor": 3000, "diet": "VEG", "hours": "All day", "sold_out": False},
        {"name": "Rajma chawal", "price_minor": 12500, "diet": "VEG", "hours": "12:00–22:00", "sold_out": False},
    ]
    D["ck_rules"] = {
        "delivery_fee_minor": 3000,
        "free_above_minor": 40000,
        "min_cart_minor": 15000,
        "approval": "Manual approval",
        "advance_days": 6,
    }
    D["ck_orders"] = [
        {
            "no": 7001 + i,
            "customer": subs[i % len(subs)]["name"] if subs else "Walk-in",
            "items": D["ck_items"][i % 10]["name"],
            "total_minor": D["ck_items"][i % 10]["price_minor"] + 3000,
            "status": ["PENDING", "ACCEPTED", "REJECTED", "ACCEPTED", "PENDING", "ACCEPTED", "ACCEPTED", "PENDING"][i],
            "when": f"{today + timedelta(days=i % 3):%a %d %b}, {12 + i % 6}:30",
        }
        for i in range(8)
    ]

    # ---- staff / roles ----------------------------------------------------------------------------------------------------------
    modules = [
        "Today",
        "Redeem",
        "Sell passes",
        "Orders",
        "Customers",
        "Kitchen",
        "Delivery",
        "Wallets & top-ups",
        "Invoices",
        "Expenses & profit",
        "Menu",
        "Plans",
        "Staff & roles",
        "Settings",
        "Reports",
        "Audit log",
    ]
    acts = ["View", "Create", "Edit", "Delete/Void"]
    presets = {
        "Owner": {m: [1, 1, 1, 1] for m in modules},
        "Manager": {m: ([1, 1, 1, 1] if m not in ("Staff & roles", "Settings") else [1, 0, 0, 0]) for m in modules},
        "Counter staff": {
            m: (
                [1, 1, 1, 0]
                if m in ("Redeem", "Sell passes", "Customers")
                else [1, 0, 0, 0]
                if m in ("Orders", "Today")
                else [0, 0, 0, 0]
            )
            for m in modules
        },
        "Chef": {
            m: ([1, 0, 1, 0] if m == "Kitchen" else [1, 0, 0, 0] if m in ("Menu", "Orders") else [0, 0, 0, 0])
            for m in modules
        },
        "Driver": {m: ([1, 0, 1, 0] if m == "Delivery" else [0, 0, 0, 0]) for m in modules},
        "Accountant": {
            m: (
                [1, 1, 1, 0]
                if m in ("Expenses & profit", "Invoices", "Wallets & top-ups")
                else [1, 0, 0, 0]
                if m in ("Reports", "Customers")
                else [0, 0, 0, 0]
            )
            for m in modules
        },
    }
    D["perm_modules"], D["perm_acts"], D["perm_presets"] = modules, acts, presets

    # ---- website, platform, help --------------------------------------------------------------------------------------------------
    D["website"] = {
        "hero_title": "Ghar jaisa khana, roz.",
        "hero_sub": "Home-style tiffins from our Kothrud kitchen, delivered or ready for pick-up.",
        "about": "Saffron Tiffins has been cooking for students and working families in Pune since 2016.",
        "how": [
            ("Pick a plan", "Monthly passes or a home-delivery wallet."),
            ("Choose your meal", "Pick today's dish before the cutoff."),
            ("We cook & deliver", "Packed and delivered on time, with photo proof."),
        ],
        "themes": ["Saffron", "Teal"],
        "domain": "saffrontiffins.example.com",
        "seo_title": "Saffron Tiffins & Mess, Kothrud, Pune",
        "policies": [
            "No refunds on delivered meals; unused wallet balance is refundable on request.",
            "Meals can be skipped until the slot's cutoff.",
            "Holds of 3+ days need a day's notice.",
        ],
    }
    D["saas_plans"] = [
        {
            "name": "Starter",
            "price_minor": 99900,
            "customers": 150,
            "staff": 3,
            "branches": 1,
            "features": ["Pass plans", "QR redeem", "Receipts", "Email support"],
        },
        {
            "name": "Growth",
            "price_minor": 249900,
            "customers": 800,
            "staff": 10,
            "branches": 3,
            "features": ["Everything in Starter", "Wallet subscriptions", "Kitchen & delivery", "WhatsApp alerts"],
        },
        {
            "name": "Pro",
            "price_minor": 499900,
            "customers": 5000,
            "staff": 40,
            "branches": 10,
            "features": ["Everything in Growth", "Restaurant website", "Cloud kitchen", "Priority support"],
        },
    ]
    # setup checklist (weights from the competitor trial: 15/35/20/15/15)
    D["checklist"] = [
        {"key": "slots", "label": "Add meal slots", "weight": 15, "done": True, "href": "menu"},
        {"key": "plan", "label": "Create your first plan", "weight": 35, "done": True, "href": "plans"},
        {"key": "branch", "label": "Branch address and map location", "weight": 20, "done": True, "href": "branches"},
        {"key": "route", "label": "Create your first delivery route", "weight": 15, "done": False, "href": "delivery"},
        {
            "key": "profile",
            "label": "Restaurant details (FSSAI no., logo, WhatsApp)",
            "weight": 15,
            "done": False,
            "href": "settings",
        },
    ]
    D["checklist_pct"] = sum(c["weight"] for c in D["checklist"] if c["done"])
    return D


@lru_cache(maxsize=16)
def get(today: date, persona: str = "saffron", roster=None) -> dict:
    from mealtally.preview import personas  # noqa: PLC0415

    return personas.localize(build(today, roster), persona)


PERSONA_SALT = {"saffron": 0, "green": 3, "e2e": 0}


def roster_for(tenant, persona: str):
    """The tenant's real customers, meal slots and drivers, as a hashable tuple (the cache key)."""
    from mealtally.accounts.models import Membership  # noqa: PLC0415
    from mealtally.accounts.models import Role  # noqa: PLC0415
    from mealtally.common.country import format_phone  # noqa: PLC0415
    from mealtally.customers.models import Customer  # noqa: PLC0415
    from mealtally.plans.models import MealSlot  # noqa: PLC0415

    customers = tuple(
        (Real(name), Real(format_phone(phone)), Real(address or ""), bool(wallet))
        for name, phone, address, wallet in Customer.objects.filter(status=Customer.Status.ACTIVE)
        .order_by("customer_code")
        .values_list("full_name", "phone_e164", "address", "has_wallet")
    )
    slots = tuple(
        (name.upper(), Real(name), start, end)
        for name, start, end in MealSlot.objects.filter(is_active=True).values_list("name", "start_time", "end_time")
    )
    drivers = tuple(
        (
            Real(m.user.name or m.user.get_username()),
            Real(format_phone(m.user.phone_e164 or "")),
            Real(m.route_name),
            Real(m.vehicle),
        )
        for m in Membership.objects.filter(role=Role.DRIVER, is_active=True, tenant_id=tenant.id)
        .select_related("user")
        .order_by("id")
    )
    return (customers, slots, drivers, PERSONA_SALT.get(persona, 0))


def for_tenant(tenant, today: date | None = None) -> dict:
    """The preview dataset for a demo tenant, built from its real roster (see :func:`build`)."""
    from django.utils import timezone  # noqa: PLC0415

    from mealtally.preview import personas  # noqa: PLC0415

    persona = personas.persona_for(tenant.slug)
    return get(today or timezone.localdate(), persona, roster_for(tenant, persona))


def sub_orders(D, sub_id, *, limit=40, past_only=True):
    rows = [o for o in D["orders"] if o["sub_id"] == sub_id and (o["off"] <= 0 or not past_only)]
    rows.sort(key=lambda o: (o["date"], o["slot"]), reverse=True)
    return rows[:limit]


def day_orders(D, day: date):
    return [o for o in D["orders"] if o["date"] == day]
