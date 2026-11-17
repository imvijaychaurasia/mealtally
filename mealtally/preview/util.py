# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

from collections import OrderedDict
from datetime import date
from datetime import datetime
from datetime import timedelta

IST = "+05:30"
LIVE = ("RECEIVED", "CONFIRMED", "PREPARING", "READY", "OUT_FOR_DELIVERY", "DELIVERED", "PICKED_UP")


def parse_date(raw: str | None, default: date) -> date:
    try:
        return datetime.strptime(raw or "", "%Y-%m-%d").date()
    except ValueError:
        return default


def iso(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + IST if dt else ""


def day_links(today: date, current: date):
    return [
        {"label": lab, "date": d, "active": d == current}
        for lab, d in (
            ("Yesterday", today - timedelta(days=1)),
            ("Today", today),
            ("Tomorrow", today + timedelta(days=1)),
        )
    ]


def slot_summary(D, day, orders):
    out = []
    for s in D["slots"]:
        rows = [o for o in orders if o["slot"] == s["key"]]
        live = [o for o in rows if o["status"] in LIVE]
        out.append({**s, "count": len(live), "total": len(rows), "orders": rows})
    return out


def cooking_plan(orders):
    """Dish x qty totals, plus how alternatives split (option A/B counts)."""
    totals: OrderedDict = OrderedDict()
    for o in orders:
        if o["status"] not in LIVE:
            continue
        for it in o["items"]:
            row = totals.setdefault(
                it["name"], {"name": it["name"], "diet": it["diet"], "qty": 0, "allergens": it["allergens"]}
            )
            row["qty"] += it["qty"] * o["qty"]
    return sorted(totals.values(), key=lambda r: -r["qty"])


def split_by_option(orders):
    groups: OrderedDict = OrderedDict()
    for o in orders:
        if o["status"] not in LIVE:
            continue
        key = " + ".join(i["name"] for i in o["items"][:2])
        groups[key] = groups.get(key, 0) + o["qty"]
    return [{"label": k, "qty": v} for k, v in groups.items()]


EXPENSE_RATIO = 0.66  # D03.1: a healthy tiffin business runs expenses at 62-70% of revenue (30-38% margin)


def money_series(D, passes_minor: int):
    """12 monthly points whose last point is the REAL last-30-days revenue (pass sales + wallet debits).

    Expenses are the demo expense entries scaled so the last 30 days land at ~66 % of revenue; history trends from ~70 % to
    ~65 %, so profit rises faster than revenue. Returns ``(months, last, expenses, recurring)``: the scaled expense rows and
    rules are what the Expenses page lists, so Today, Expenses & profit and the chart always agree.
    """
    cutoff = D["today"] - timedelta(days=30)
    wallet = sum(
        e["amount_minor"]
        for es in D["ledgers"].values()
        for e in es
        if e["type"] == "DEBIT" and e["dt"].date() > cutoff
    )
    rev = passes_minor + wallet
    raw = sum(e["amount_minor"] for e in D["expenses"] if e["date"] > cutoff) or 1
    factor = EXPENSE_RATIO * rev / raw
    expenses = [
        {**e, "amount_minor": max(1000, round(e["amount_minor"] * factor / 1000) * 1000)} for e in D["expenses"]
    ]
    recurring = [
        {**r, "amount_minor": max(1000, round(r["amount_minor"] * factor / 10000) * 10000)} for r in D["recurring"]
    ]
    expense = sum(e["amount_minor"] for e in expenses if e["date"] > cutoff)
    n = len(D["months"])
    months = []
    for i, m in enumerate(D["months"]):
        if i == n - 1:
            r, x = rev, expense
        else:
            f = 0.55 + 0.45 * i / 11 + ((int(m["label"][-2:]) * 7 + i) % 5 - 2) / 200
            ratio = 0.70 - 0.05 * i / 11 + ((i * 3) % 3 - 1) / 400
            r = int(rev * f) // 100 * 100
            x = int(r * ratio) // 100 * 100
        months.append({"label": m["label"], "revenue_minor": r, "expense_minor": x, "profit_minor": r - x})
    return months, {"passes": passes_minor, "wallet": wallet, **months[-1]}, expenses, recurring
