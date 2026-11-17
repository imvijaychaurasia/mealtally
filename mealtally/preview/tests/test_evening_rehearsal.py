# SPDX-License-Identifier: AGPL-3.0-only
"""Evening rehearsal of the demo script with the clock frozen. Read-only for the demo tenants: it runs on a test
database seeded exactly like demo-tiffin / e2e-tiffin, and patches ``django.utils.timezone.now`` (not the server clock).

    pytest mealtally/preview/tests/test_evening_rehearsal.py -s -k rehearsal      # prints one JSON line per (time, step)
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from mealtally.preview.tests.test_preview import SLUG
from mealtally.preview.tests.test_preview import clients  # noqa: F401
from mealtally.preview.tests.test_preview import demo  # noqa: F401

pytestmark = pytest.mark.django_db
IST = ZoneInfo("Asia/Kolkata")
TIMES = [dtime(10, 30), dtime(18, 30), dtime(19, 30), dtime(20, 30)]  # 10:30 is the morning baseline


def freeze(monkeypatch, t):
    real_now = timezone.now()
    local = real_now.astimezone(IST)
    frozen = datetime.combine(local.date(), t, tzinfo=IST)
    monkeypatch.setattr(timezone, "now", lambda: frozen)
    return frozen


def text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def facts(clients, monkeypatch, t):  # noqa: F811
    out = {}
    base = f"/t/{SLUG}"
    freeze(monkeypatch, t)

    def get(role, path):
        r = clients[role].get(base + path)
        return r.status_code, r.content.decode() if r.status_code == 200 else ""

    # 1 dashboard
    code, h = get("OWNER", "/admin/today")
    out["1 dashboard"] = {
        "status": code,
        "deliveries_total": (re.search(r"Today total\s*(\d+)", text(h)) or [None, None])[1],
        "alerts": h.count("data-alert="),
    }
    # 2 menu planner
    out["2 menu planner"] = {"status": get("OWNER", "/admin/menu")[0]}
    # 3 counter: search, card, redeem (no closed-slot guard exists for pass redemption)
    code, h = get("STAFF", "/staff/")
    out["3a counter page"] = {"status": code}
    r = clients["STAFF"].get(base + "/staff/search", {"q": "C0010"})
    out["3b search"] = {
        "status": r.status_code,
        "found": "Rohan" in r.content.decode() or "C0010" in r.content.decode(),
    }
    import re as _re

    cid = _re.search(r"/staff/card/([0-9a-f-]{36})", r.content.decode())
    if cid:
        card = clients["STAFF"].get(base + f"/staff/card/{cid[1]}")
        body = card.content.decode()
        key = _re.search(r'name="idempotency_key" value="([^"]+)"', body)
        state = _re.search(r'data-state="(\w+)"', body)
        res = clients["STAFF"].post(
            base + "/staff/redeem", {"customer": cid[1], "idempotency_key": key[1] if key else "x"}
        )
        rb = res.content.decode()
        out["3c redeem"] = {
            "status": res.status_code,
            "card_state": state[1] if state else None,
            "redeemed": "Meal redeemed" in rb or "left" in text(rb),
            "blocked_text": "closed" in rb.lower() or "not open" in rb.lower(),
        }
    else:
        out["3c redeem"] = {"status": "no card"}
    # 4 customer home
    code, h = get("CUSTOMER", "/me/")
    tx = text(h)
    today_card = re.search(r'data-testid="home-today".*?<p class="text-sm font-semibold text-muted">(.*?)</p>', h, re.S)
    chip = re.search(r'data-countdown="([^"]+)"', h)
    coming = re.search(r'data-testid="home-coming-up">(.*?)</div>', h, re.S)
    out["4 customer home"] = {
        "status": code,
        "today_card": text(today_card[1]) if today_card else None,
        "cutoff_iso": chip[1] if chip else None,
        "coming_up_first": text(coming[1])[:60] if coming else None,
        "show_qr": 'data-testid="show-qr"' in h,
    }
    # 5 meals, wallet, order
    code, h = get("CUSTOMER", "/me/meals")
    head = re.search(r'id="choose".*?<h2 class="font-semibold">(.*?)</h2>', h, re.S)
    out["5a meals"] = {"status": code, "choose_card": text(head[1]) if head else None}
    out["5b wallet"] = {"status": get("CUSTOMER", "/me/wallet")[0]}
    code, h = get("CUSTOMER", "/me/order")
    out["5c order"] = {"status": code, "date_chips": h.count("data-day-chip")}
    # 6 top-ups
    out["6 top-ups"] = {"status": get("OWNER", "/admin/wallets")[0]}
    # 7 orders board
    code, h = get("OWNER", "/admin/orders")
    tx = text(h)
    chip = re.search(r'data-testid="cutoff"[^>]*data-countdown="([^"]+)"[^>]*data-locked-text="([^"]*)"', h)
    day = re.search(r'name="date" value="([\d-]+)"', h)
    out["7 orders board"] = {
        "status": code,
        "day": day[1] if day else None,
        "cutoff_chip": (chip[1], chip[2]) if chip else None,
        "empty": "No orders" in tx,
        "tabs": [text(x) for x in re.findall(r'data-testid="slot-tab"[^>]*>(.*?)</a>', h, re.S)][:3],
    }
    # 7b new order: closed slot guard (page only renders the guard; check it exists)
    code, h = get("OWNER", "/admin/orders/new")
    out["7b new order"] = {"status": code, "closed_guard": "data-closed" in h}
    # 8 kitchen
    code, h = get("CHEF", "/admin/kitchen")
    out["8 kitchen"] = {
        "status": code,
        "tabs": [text(x) for x in re.findall(r'data-testid="slot-tab"[^>]*>(.*?)</a>', h, re.S)],
    }
    # 9 driver
    code, h = get("DRIVER", "/driver/")
    summ = re.search(r'data-testid="day-summary">(.*?)</span>', h, re.S)
    out["9 driver"] = {
        "status": code,
        "summary": text(summ[1]) if summ else None,
        "stops_listed": h.count('data-testid="stop"'),
        "delivered_group": "delivered-group" in h,
    }
    # 10-15 the rest
    for step, role, path in (
        ("10 invoices", "OWNER", "/admin/invoices"),
        ("11 expenses", "OWNER", "/admin/expenses"),
        ("12 holds", "OWNER", "/admin/holds"),
        ("13 website", "OWNER", "/admin/website"),
        ("14 fee statement", "OWNER", "/admin/reports/fees"),
    ):
        out[step] = {"status": get(role, path)[0]}
    code, h = get("OWNER", "/admin/holds")
    out["12 holds"]["options"] = len(re.findall(r"data-hold-day|<option", h))
    return out


@pytest.mark.parametrize("t", TIMES, ids=lambda t: t.strftime("%H:%M"))
def test_rehearsal_demo_script_at_frozen_times(demo, clients, monkeypatch, t):  # noqa: F811
    result = facts(clients, monkeypatch, t)
    print("REHEARSAL " + json.dumps({"time": t.strftime("%H:%M"), "facts": result}, default=str))
    for step, f in result.items():
        assert f["status"] in (200, "no card"), (step, f)


@pytest.mark.parametrize("t", TIMES, ids=lambda t: t.strftime("%H:%M"))
def test_rehearsal_counter_redeem_at_frozen_times(demo, clients, monkeypatch, t):  # noqa: F811
    from mealtally.customers.models import Customer
    from mealtally.ledger.models import MealLedgerEntry
    from mealtally.preview.tests.test_preview import tid
    from mealtally.tenancy.context import tenant_context

    frozen = freeze(monkeypatch, t)
    with tenant_context(tid()):
        cust = Customer.objects.get(full_name="Rohan Pawar")
        before = MealLedgerEntry.objects.filter(customer=cust, entry_type="REDEEM").count()
    base = f"/t/{SLUG}"
    s = clients["STAFF"]
    found = "Rohan" in s.get(base + "/staff/search", {"q": "Rohan"}).content.decode()
    card = s.get(base + f"/staff/card/{cust.public_id}").content.decode()
    state = re.search(r'data-state="(\w+)"', card)
    key = re.search(r'name="idempotency_key" value="([^"]+)"', card)
    res = s.post(base + "/staff/redeem", {"customer": str(cust.public_id), "idempotency_key": key[1] if key else "k"})
    body = res.content.decode()
    with tenant_context(tid()):
        after = MealLedgerEntry.objects.filter(customer=cust, entry_type="REDEEM").count()
        last = MealLedgerEntry.objects.filter(customer=cust, entry_type="REDEEM").order_by("-occurred_at").first()
    print(
        "REDEEM "
        + json.dumps(
            {
                "time": t.strftime("%H:%M"),
                "found": found,
                "card_state": state[1] if state else None,
                "status": res.status_code,
                "ledger_rows_added": after - before,
                "error_text": re.findall(r'data-testid="card-error"[^>]*>(.*?)<', body)[:1],
                "meal_date": str(last.meal_date) if last else None,
                "frozen": frozen.isoformat(),
            }
        )
    )
    assert res.status_code == 200
