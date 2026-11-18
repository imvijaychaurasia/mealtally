# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import re
import uuid

import pytest
from django.utils import timezone

from mealtally.customers import qr
from mealtally.ledger import services as ledger
from mealtally.ledger.models import MealLedgerEntry
from mealtally.testing import World
from mealtally.testing import buy

pytestmark = pytest.mark.django_db


def key_of(html):
    return re.search(r'name="idempotency_key" value="([^"]+)"', html).group(1)


def test_console_search_and_card_states(w, staff_c, u):
    assert staff_c.get(u + "/staff/").status_code == 200
    res = staff_c.get(u + "/staff/search", {"q": w.customer.customer_code}).content.decode()
    assert w.customer.full_name in res
    assert "No customer found" in staff_c.get(u + "/staff/search", {"q": "zzzzzz"}).content.decode()
    assert staff_c.get(u + "/staff/search", {"q": ""}).content.strip() == b""
    card = staff_c.get(f"{u}/staff/card/{w.customer.public_id}").content.decode()
    assert 'data-state="ok"' in card and "Redeem 1 meal" in card and "••••" in card  # phone masked
    assert f"••••• {w.customer.phone_e164[-4:]}" in card  # the LAST four digits stay visible (staff match on them)
    assert w.customer.phone_e164[:-4] not in card
    assert "Customer not found" in staff_c.get(f"{u}/staff/card/{uuid.uuid4()}").content.decode()
    assert "Search for a customer" in staff_c.get(u + "/staff/card-reset").content.decode()


def test_redeem_success_replay_cooldown_and_undo(w, staff_c, u):
    card = staff_c.get(f"{u}/staff/card/{w.customer.public_id}").content.decode()
    key = key_of(card)
    ok = staff_c.post(u + "/staff/redeem", {"customer": w.customer.public_id, "idempotency_key": key})
    html = ok.content.decode()
    assert (
        "Meal redeemed. 29 left." in html
        and "HX-Trigger" in ok.headers
        and "mealtally:redeemed" in ok.headers["HX-Trigger"]
    )
    entry = re.search(r'name="entry" value="([^"]+)"', html).group(1)
    again = staff_c.post(
        u + "/staff/redeem", {"customer": w.customer.public_id, "idempotency_key": key}
    ).content.decode()
    assert "already recorded" in again and "29 left" in again  # idempotent replay
    cd = staff_c.post(
        u + "/staff/redeem", {"customer": w.customer.public_id, "idempotency_key": str(uuid.uuid4())}
    ).content.decode()
    assert 'data-testid="cooldown-modal"' in cd and "Give another meal" in cd and "less than a minute ago" in cd
    confirmed = staff_c.post(
        u + "/staff/redeem",
        {"customer": w.customer.public_id, "idempotency_key": str(uuid.uuid4()), "confirm_additional": "1"},
    ).content.decode()
    assert "28 left" in confirmed
    undo = staff_c.post(u + "/staff/undo", {"entry": entry}).content.decode()
    assert "Undone" in undo and "29 meals left" in undo
    assert (
        "Undone" in staff_c.post(u + "/staff/undo", {"entry": entry}).content.decode()
    )  # retry is idempotent: no second reversal
    with w.ctx():
        assert MealLedgerEntry.objects.filter(entry_type="REVERSAL").count() == 1
    today = staff_c.get(u + "/staff/today").content.decode()
    assert "undone" in today and "meal today" in today


@pytest.mark.parametrize(
    ("setup", "text"), [("nopass", "no active pass"), ("blocked", "blocked"), ("nocredit", "No meals left")]
)
def test_redeem_error_copy(setup, text, staff_c):
    w = World(
        slug=f"webred{setup}",
        buy_pass=setup != "nopass",
        plan_kwargs={"meals_per_cycle": 1} if setup == "nocredit" else None,
    )
    from .conftest import client_for

    c = client_for(w.staff.user)
    u = f"/t/{w.tenant.slug}"
    with w.ctx():
        if setup == "blocked":
            from mealtally.customers import services as cs

            cs.set_status(actor=w.owner, customer=w.customer, status="BLOCKED", reason="x")
        if setup == "nocredit":
            ledger.redeem(
                actor=w.staff,
                customer=w.customer,
                idempotency_key="nc",
                source="STAFF_SEARCH",
                now=timezone.now() + timezone.timedelta(seconds=1),
            )
    card = c.get(f"{u}/staff/card/{w.customer.public_id}").content.decode()
    assert 'data-state="blocked"' in card and text.lower() in card.lower() and "Redeem 1 meal" not in card
    forced = c.post(
        u + "/staff/redeem", {"customer": w.customer.public_id, "idempotency_key": str(uuid.uuid4())}
    ).content.decode()
    assert 'data-testid="card-error"' in forced


def test_scan_redeems_blocks_reuse_and_reports_bad_tokens(w, staff_c, u):
    token = qr.issue_token(customer=w.customer, tenant=w.tenant)
    key = str(uuid.uuid4())
    ok = staff_c.post(u + "/staff/scan", {"token": token, "idempotency_key": key}).content.decode()
    assert "29 left" in ok
    with w.ctx():
        assert MealLedgerEntry.objects.get(entry_type="REDEEM").source == "QR_SCAN"
    used = staff_c.post(u + "/staff/scan", {"token": token, "idempotency_key": str(uuid.uuid4())}).content.decode()
    assert "already used" in used
    assert "not valid" in staff_c.post(u + "/staff/scan", {"token": "garbage"}).content.decode()
    t2 = qr.issue_token(customer=w.customer, tenant=w.tenant)
    modal = staff_c.post(u + "/staff/scan", {"token": t2, "idempotency_key": "k-scan-2"}).content.decode()
    assert 'data-testid="cooldown-modal"' in modal and f'name="token" value="{t2}"' in modal  # confirm re-posts the QR
    assert (
        "28 left"
        in staff_c.post(
            u + "/staff/scan", {"token": t2, "idempotency_key": "k-scan-2", "confirm_additional": "1"}
        ).content.decode()
    )


def test_reverse_from_todays_list_follows_role_rules(w, staff_c, owner_c, u):
    with w.ctx():
        e = ledger.redeem(actor=w.staff, customer=w.customer, idempotency_key="rv", source="STAFF_SEARCH").entry
    assert "Reason" in staff_c.get(u + "/staff/today").content.decode()
    r = staff_c.post(u + "/staff/reverse", {"entry": e.public_id, "reason": ""}).content.decode()
    assert "A reason is required" in r
    ok = owner_c.post(u + "/staff/reverse", {"entry": e.public_id, "reason": "wrong plate"}).content.decode()
    assert (
        "Show undone meals (1)" in ok and "0 meals today" in ok and "line-through" not in ok
    )  # reversed rows are hidden by default
    shown = owner_c.get(u + "/staff/today?undone=1").content.decode()
    assert "undone" in shown and "Hide undone meals" in shown


def test_sell_flow_new_customer_preview_confirm_receipt(w, staff_c, u):
    page = staff_c.get(u + "/staff/sell")
    assert page.status_code == 200 and b"Monthly meal pass" in page.content
    base = {
        "new_name": "Walk In",
        "new_phone": "9812345678",
        "plan": w.plan.public_id,
        "method": "UPI_MANUAL",
        "reference": "UTR12345",
        "pin_choice": "generate",
    }
    assert (
        b"reference" in staff_c.post(u + "/staff/sell/preview", {**base, "reference": ""}).content
    )  # non-cash needs a reference
    assert staff_c.post(u + "/staff/sell/preview", {**base, "new_name": ""}).status_code == 400
    pv = staff_c.post(u + "/staff/sell/preview", base).content.decode()
    assert "Active now" in pv and "Walk In" in pv and "1,500.00" in pv
    done = staff_c.post(u + "/staff/sell/confirm", base).content.decode()
    assert "Pass sold" in done and "R-00000" in done and re.search(r'data-testid="pin-value">(\d{6})<', done)
    # an inline new customer + failing sale leaves nothing behind
    from mealtally.customers.models import Customer

    with w.ctx():
        n = Customer.objects.count()
        bad = {**base, "new_phone": "9899999999", "method": "UPI_MANUAL", "reference": ""}
        assert staff_c.post(u + "/staff/sell/confirm", bad).status_code == 400
        assert Customer.objects.count() == n


def test_sell_existing_customer_queue_gap_requires_acknowledgement(w, staff_c, u):
    from mealtally.plans import services as plans

    with w.ctx():
        cal = plans.save_plan(
            actor=w.owner,
            name="Calendar",
            price_minor=100000,
            meals_per_cycle=30,
            validity_mode="CALENDAR_MONTH",
            validity_days=30,
            is_active=True,
        )
    data = {"customer": w.customer.public_id, "plan": cal.public_id, "method": "CASH"}
    pv = staff_c.post(u + "/staff/sell/preview", data).content.decode()
    assert 'data-testid="gap-warning"' in pv and "No active pass from" in pv and "end of month" in pv
    no_ack = staff_c.post(u + "/staff/sell/confirm", data)
    assert no_ack.status_code == 400 and b"confirm the gap" in no_ack.content
    ok = staff_c.post(u + "/staff/sell/confirm", {**data, "ack_gap": "1"}).content.decode()
    assert "Queued" in ok
    again = staff_c.post(u + "/staff/sell/preview", data)
    assert again.status_code == 400  # queue is now full
    found = staff_c.get(u + "/staff/sell/search", {"sq": w.customer.customer_code}).content.decode()
    assert w.customer.full_name in found
    assert staff_c.get(u + "/staff/sell", {"customer": w.customer.public_id}).status_code == 200


def test_customer_new_with_own_pin_and_errors(w, staff_c, u):
    assert staff_c.get(u + "/staff/customers/new").status_code == 200
    ok = staff_c.post(
        u + "/staff/customers/new",
        {"full_name": "Pin Own", "phone": "9811000011", "pin_choice": "own", "pin": "482916"},
    ).content.decode()
    assert "Customer created" in ok and ">482916<" in ok
    assert (
        staff_c.post(u + "/staff/customers/new", {"full_name": "Pin Own", "phone": "9811000011"}).status_code == 400
    )  # duplicate phone
    assert buy and w


def test_dates_render_in_the_tenant_timezone_not_utc(w, staff_c, owner_c, u):
    """A queued pass starts at 00:00 IST after the active one ends: 11 Dec 18:30 UTC must read '12 Dec'."""
    from datetime import timedelta

    with w.ctx():
        active_end = w.pass_.ends_at.astimezone(w.tenant.zone)
    expected_start = (active_end + timedelta(microseconds=1)).strftime("%-d %b %Y")
    pv = staff_c.post(
        u + "/staff/sell/preview", {"customer": w.customer.public_id, "plan": w.plan.public_id, "method": "CASH"}
    ).content.decode()
    assert "Queued" in pv and expected_start in pv
    receipt = owner_c.get(f"{u}/receipt/{w.recorded.payment.public_id}").content.decode()
    paid_local = w.recorded.payment.received_at.astimezone(w.tenant.zone)
    assert (
        paid_local.strftime("%-d %b %Y") in receipt
        and paid_local.strftime("%-I:%M %p").replace("AM", "a.m.").replace("PM", "p.m.") in receipt
    ) or paid_local.strftime("%-I:%M") in receipt
