# SPDX-License-Identifier: AGPL-3.0-only
"""D02 section 1 rule changes: inclusive rolling validity, promote-next, purchase preview, redeem status."""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from mealtally.audit.models import AuditEvent
from mealtally.billing import services as billing
from mealtally.ledger import services as ledger
from mealtally.ledger.models import MealLedgerEntry
from mealtally.passes import services as passes
from mealtally.passes.models import Pass
from mealtally.testing import World
from mealtally.testing import buy
from mealtally.testing import make_plan

pytestmark = pytest.mark.django_db
IST = ZoneInfo("Asia/Kolkata")


def ist(*a):
    return datetime(*a, tzinfo=IST)


def fresh(p):
    return Pass.objects.get(pk=p.pk)


def test_rolling_validity_counts_the_purchase_day_as_day_one():
    w = World(buy_pass=False)
    p = buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 11, 12, 10, 0)).pass_  # 30 days
    assert p.ends_at.astimezone(IST) == datetime(2026, 12, 11, 23, 59, 59, 999999, tzinfo=IST)
    one = make_plan(w.tenant, name="Day pass", validity_days=1, price_minor=5000)
    other = World(buy_pass=False)
    d = buy(
        other.tenant,
        other.owner,
        other.customer,
        make_plan(other.tenant, name="Day", validity_days=1, price_minor=5000),
        now=ist(2026, 11, 12, 23, 30),
    ).pass_
    assert d.ends_at.astimezone(IST).date().isoformat() == "2026-11-12"  # a 1-day pass ends the same local day
    assert one.validity_days == 1


def test_promote_next_on_cancel_starts_the_queued_pass_immediately():
    w = World(buy_pass=False)
    a = buy(w.tenant, w.owner, w.customer, w.plan).pass_
    b = buy(w.tenant, w.owner, w.customer, w.plan).pass_
    assert b.status == "QUEUED"
    now = timezone.now() + timedelta(days=2)
    with w.ctx():
        passes.cancel_pass(actor=w.owner, pass_public_id=a.public_id, reason="requested", now=now)
        nb = fresh(b)
        assert nb.status == "ACTIVE" and nb.starts_at == now and nb.meals_remaining == 30
        assert (
            nb.ends_at.astimezone(IST).date() == (now.astimezone(IST) + timedelta(days=29)).date()
        )  # inclusive 30 days
        assert MealLedgerEntry.objects.filter(pass_ref=nb, entry_type="ISSUE").count() == 1
        assert AuditEvent.objects.filter(action="pass.activate", object_public_id=nb.public_id).exists()
        assert ledger.find_mismatches() == []


def test_promote_next_on_void_and_rechains_remaining_queue_and_calendar_mode():
    w = World(buy_pass=False, tenant_settings={"max_queued_passes": 2})
    cal = make_plan(w.tenant, name="Cal", validity_mode="CALENDAR_MONTH")
    first = buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 3, 5, 10, 0))
    second = buy(w.tenant, w.owner, w.customer, cal, now=ist(2026, 3, 6, 10, 0))
    third = buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 3, 7, 10, 0))
    assert (second.pass_.status, third.pass_.status) == ("QUEUED", "QUEUED")
    now = ist(2026, 3, 8, 9, 0)
    with w.ctx():
        billing.void_payment(actor=w.owner, payment_public_id=first.payment.public_id, reason="dup", now=now)
        s, t = fresh(second.pass_), fresh(third.pass_)
        assert s.status == "ACTIVE" and s.starts_at == now
        assert s.ends_at.astimezone(IST) == datetime(
            2026, 3, 31, 23, 59, 59, 999999, tzinfo=IST
        )  # calendar: end of month
        assert t.status == "QUEUED" and t.starts_at == s.ends_at + timedelta(microseconds=1)  # re-chained behind it
        assert ledger.find_mismatches() == []


def test_no_promotion_when_there_is_nothing_queued_or_a_queued_pass_is_cancelled():
    w = World()
    q = buy(w.tenant, w.owner, w.customer, w.plan).pass_
    with w.ctx():
        passes.cancel_pass(actor=w.owner, pass_public_id=q.public_id, reason="x")
        assert fresh(w.pass_).status == "ACTIVE"
        passes.cancel_pass(actor=w.owner, pass_public_id=w.pass_.public_id, reason="x")
        assert not Pass.objects.filter(status="ACTIVE").exists()


def test_preview_purchase_scenarios():
    w = World(buy_pass=False)
    cal = make_plan(w.tenant, name="Cal", validity_mode="CALENDAR_MONTH")
    settings_row = w.tenant.settings
    pv = passes.preview_purchase(
        customer_id=None, plan=w.plan, tenant=w.tenant, settings_row=settings_row, now=ist(2026, 11, 12, 10, 0)
    )
    assert pv["status"] == "ACTIVE" and pv["gap"] is None and pv["ends_at"].date().isoformat() == "2026-12-11"
    buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 11, 12, 10, 0))
    with w.ctx():
        pv = passes.preview_purchase(
            customer_id=w.customer.id,
            plan=w.plan,
            tenant=w.tenant,
            settings_row=settings_row,
            now=ist(2026, 11, 13, 10, 0),
        )
        assert pv["status"] == "QUEUED" and pv["gap"] is None and pv["starts_at"].date().isoformat() == "2026-12-12"
        pv = passes.preview_purchase(
            customer_id=w.customer.id,
            plan=cal,
            tenant=w.tenant,
            settings_row=settings_row,
            now=ist(2026, 11, 13, 10, 0),
        )
        assert pv["no_proration"] is True
        assert (pv["gap"]["from"].isoformat(), pv["gap"]["to"].isoformat()) == (
            "2026-12-12",
            "2026-12-31",
        )  # "No active pass from 12 Dec to 31 Dec"
        buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 11, 13, 10, 0))
        assert passes.preview_purchase(
            customer_id=w.customer.id,
            plan=w.plan,
            tenant=w.tenant,
            settings_row=settings_row,
            now=ist(2026, 11, 13, 10, 0),
        )["queue_full"]


def test_redeem_status_states():
    w = World(plan_kwargs={"max_meals_per_day": 1})
    w2 = World()
    w4 = World(plan_kwargs={"meals_per_cycle": 1})
    t0 = timezone.now() + timedelta(seconds=2)
    with w.ctx():
        assert ledger.redeem_status(customer=w.customer, now=t0)["state"] == "ok"
        ledger.redeem(actor=w.staff, customer=w.customer, idempotency_key="rs1", source="STAFF_SEARCH", now=t0)
        st = ledger.redeem_status(customer=w.customer, now=t0 + timedelta(seconds=5))
        assert st["code"] == "DAILY_CAP_REACHED" and st["state"] == "blocked" and st["meals_today"] == 1
    with w2.ctx():
        ledger.redeem(actor=w2.staff, customer=w2.customer, idempotency_key="rs2", source="STAFF_SEARCH", now=t0)
        assert ledger.redeem_status(customer=w2.customer, now=t0 + timedelta(seconds=5))["state"] == "cooldown"
        assert ledger.redeem_status(customer=w2.customer, now=t0 + timedelta(minutes=10))["state"] == "ok"
        assert (
            ledger.redeem_status(customer=w2.customer, now=w2.pass_.ends_at + timedelta(seconds=1))["code"]
            == "PASS_NOT_VALID_NOW"
        )
        passes.suspend_pass(actor=w2.owner, pass_public_id=w2.pass_.public_id, reason="r")
        assert ledger.redeem_status(customer=w2.customer)["code"] == "NO_ACTIVE_PASS"
    w3 = World(buy_pass=False)
    with w3.ctx():
        assert ledger.redeem_status(customer=w3.customer)["code"] == "NO_ACTIVE_PASS"
    with w4.ctx():
        ledger.redeem(actor=w4.staff, customer=w4.customer, idempotency_key="rs4", source="STAFF_SEARCH", now=t0)
        assert ledger.redeem_status(customer=w4.customer, now=t0 + timedelta(minutes=10))["code"] == "NO_CREDITS"
