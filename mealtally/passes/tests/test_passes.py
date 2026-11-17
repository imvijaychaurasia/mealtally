# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import uuid
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from mealtally.audit.models import AuditEvent
from mealtally.common.errors import NotAllowed
from mealtally.common.errors import QueueFull
from mealtally.common.errors import StateConflict
from mealtally.common.errors import ValidationFailed
from mealtally.ledger import services as ledger
from mealtally.ledger.models import MealLedgerEntry
from mealtally.passes import services as passes
from mealtally.passes.models import Pass
from mealtally.passes.tasks import expire_and_activate_passes
from mealtally.testing import World
from mealtally.testing import buy
from mealtally.testing import make_customer
from mealtally.testing import make_plan

pytestmark = pytest.mark.django_db
IST = ZoneInfo("Asia/Kolkata")


def ist(*args) -> datetime:
    return datetime(*args, tzinfo=IST)


def fresh(p) -> Pass:
    return Pass.objects.get(pk=p.pk)


# --- validity --------------------------------------------------------------------------------------
def test_rolling_days_ends_at_end_of_last_local_day():
    w = World(buy_pass=False)
    rec = buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 11, 12, 10, 0))
    p = rec.pass_
    assert p.status == "ACTIVE" and p.meals_remaining == 30 and p.starts_at == ist(2026, 11, 12, 10, 0)
    # purchase day is day 1: 12 Nov + 29 days = 11 Dec, to the last microsecond of that tenant-local day
    assert p.ends_at.astimezone(IST) == datetime(2026, 12, 11, 23, 59, 59, 999999, tzinfo=IST)
    with w.ctx():
        e = MealLedgerEntry.objects.get(pass_ref=p)
        assert (e.entry_type, e.quantity, e.balance_after, e.source) == ("ISSUE", 30, 30, "SYSTEM")


def test_calendar_month_runs_to_month_end_and_grants_full_credits_mid_month():
    w = World(buy_pass=False, plan_kwargs={"validity_mode": "CALENDAR_MONTH"})
    p = buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 11, 25, 12, 0)).pass_
    assert p.meals_remaining == 30  # no proration (product decision)
    assert p.ends_at.astimezone(IST) == datetime(2026, 11, 30, 23, 59, 59, 999999, tzinfo=IST)


def test_calendar_month_uses_tenant_local_month_not_utc():
    w = World(buy_pass=False, plan_kwargs={"validity_mode": "CALENDAR_MONTH"})
    # 2026-01-31 20:00 UTC == 2026-02-01 01:30 IST -> the pass belongs to FEBRUARY
    p = buy(w.tenant, w.owner, w.customer, w.plan, now=datetime(2026, 1, 31, 20, 0, tzinfo=UTC)).pass_
    assert p.ends_at.astimezone(IST).date().isoformat() == "2026-02-28"


# --- queueing -------------------------------------------------------------------------------------
def test_second_purchase_is_queued_without_credits_until_activation():
    w = World(buy_pass=False)
    first = buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 11, 1, 9, 0)).pass_
    second = buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 11, 2, 9, 0)).pass_
    assert second.status == "QUEUED" and second.meals_remaining == 0
    assert second.starts_at == first.ends_at + timedelta(microseconds=1)
    assert second.starts_at.astimezone(IST).time().isoformat() == "00:00:00"  # midnight, no gap/overlap
    with w.ctx():
        assert not MealLedgerEntry.objects.filter(pass_ref=second).exists()  # no ISSUE until activation


def test_queue_limit_is_enforced_and_configurable():
    w = World(buy_pass=False)
    buy(w.tenant, w.owner, w.customer, w.plan)
    buy(w.tenant, w.owner, w.customer, w.plan)
    with pytest.raises(QueueFull):
        buy(w.tenant, w.owner, w.customer, w.plan)
    w2 = World(buy_pass=False, tenant_settings={"max_queued_passes": 2})
    base = ist(2026, 11, 1, 9, 0)
    p1 = buy(w2.tenant, w2.owner, w2.customer, w2.plan, now=base).pass_
    p2 = buy(w2.tenant, w2.owner, w2.customer, w2.plan, now=base).pass_
    p3 = buy(w2.tenant, w2.owner, w2.customer, w2.plan, now=base).pass_
    assert p3.starts_at == p2.ends_at + timedelta(microseconds=1) and p2.starts_at == p1.ends_at + timedelta(
        microseconds=1
    )
    with pytest.raises(QueueFull):
        buy(w2.tenant, w2.owner, w2.customer, w2.plan, now=base)


def test_calendar_plan_queued_behind_rolling_pass_starts_on_the_next_first():
    w = World(buy_pass=False)
    cal = make_plan(w.tenant, name="Calendar", validity_mode="CALENDAR_MONTH")
    buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 11, 12, 10, 0))  # rolling, ends Dec 12
    q = buy(w.tenant, w.owner, w.customer, cal, now=ist(2026, 11, 13, 10, 0)).pass_
    assert q.starts_at == ist(2027, 1, 1, 0, 0)  # next 1st after the prior pass ends
    assert q.ends_at.astimezone(IST).date().isoformat() == "2027-01-31"


def test_calendar_pass_renewal_starts_exactly_at_midnight_of_the_1st():
    w = World(buy_pass=False, plan_kwargs={"validity_mode": "CALENDAR_MONTH"})
    buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 11, 5, 10, 0))
    q = buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 11, 6, 10, 0)).pass_
    assert q.starts_at == ist(2026, 12, 1, 0, 0) and q.ends_at.astimezone(IST).date().isoformat() == "2026-12-31"


# --- the expiry & activation job ------------------------------------------------------------------
def test_job_expires_zeroes_credits_and_activates_the_queued_pass_at_the_ist_month_boundary():
    w = World(buy_pass=False, plan_kwargs={"validity_mode": "CALENDAR_MONTH"})
    active = buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 3, 10, 12, 0)).pass_
    queued = buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 3, 11, 12, 0)).pass_
    boundary = ist(2026, 4, 1, 0, 0)  # == 2026-03-31 18:30:00 UTC
    assert queued.starts_at == boundary and active.ends_at == boundary - timedelta(microseconds=1)
    with w.ctx():
        ledger.redeem(
            actor=w.staff, customer=w.customer, idempotency_key="m1", source="STAFF_SEARCH", now=ist(2026, 3, 20, 13, 0)
        )
        # one second before the boundary: nothing happens
        assert passes.run_due_transitions(now=boundary - timedelta(seconds=1)) == {"expired": 0, "activated": 0}
        assert fresh(active).status == "ACTIVE"
        # at the boundary: old pass expires (29 credits forfeited), new one activates with 30
        assert passes.run_due_transitions(now=boundary) == {"expired": 1, "activated": 1}
        old, new = fresh(active), fresh(queued)
        assert (old.status, old.meals_remaining) == ("EXPIRED", 0)
        assert (new.status, new.meals_remaining) == ("ACTIVE", 30)
        exp = MealLedgerEntry.objects.get(pass_ref=active, entry_type="EXPIRE")
        assert exp.quantity == -29 and exp.balance_after == 0 and exp.source == "SYSTEM"
        issue = MealLedgerEntry.objects.get(pass_ref=queued, entry_type="ISSUE")
        assert issue.quantity == 30 and issue.balance_after == 30
        # idempotent
        assert passes.run_due_transitions(now=boundary + timedelta(minutes=5)) == {"expired": 0, "activated": 0}
        assert ledger.find_mismatches() == []
        assert {e.action for e in AuditEvent.objects.all()} >= {"pass.expire", "pass.activate"}


def test_job_rolling_mode_and_zero_balance_marker():
    w = World(buy_pass=False, plan_kwargs={"meals_per_cycle": 1})
    p = buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 11, 1, 9, 0)).pass_
    with w.ctx():
        ledger.redeem(
            actor=w.staff, customer=w.customer, idempotency_key="z1", source="STAFF_SEARCH", now=ist(2026, 11, 2, 9, 0)
        )
        passes.run_due_transitions(now=p.ends_at + timedelta(microseconds=1))
        marker = MealLedgerEntry.objects.get(pass_ref=p, entry_type="EXPIRE")
        assert marker.quantity == 0 and marker.balance_after == 0  # 0-quantity EXPIRE marker
        assert fresh(p).status == "EXPIRED"


def test_job_does_not_activate_a_queued_pass_while_another_is_active():
    w = World(buy_pass=False)
    a = buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 11, 1, 9, 0)).pass_
    q = buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 11, 1, 9, 5)).pass_
    with w.ctx():
        assert passes.run_due_transitions(now=a.ends_at - timedelta(days=1)) == {"expired": 0, "activated": 0}
        assert fresh(q).status == "QUEUED"


def test_job_task_runs_per_tenant_and_handles_many_tenants():
    w1, w2 = World(buy_pass=False), World(buy_pass=False)
    old = timezone.now() - timedelta(days=45)
    for w in (w1, w2):
        buy(w.tenant, w.owner, w.customer, w.plan, now=old)
    result = expire_and_activate_passes()
    assert result["expired"] == 2 and result["failed_tenants"] == 0 and result["tenants"] >= 2
    for w in (w1, w2):
        with w.ctx():
            assert Pass.objects.get().status == "EXPIRED"


def test_new_payment_after_expiry_but_before_job_runs_settles_first():
    w = World(buy_pass=False)
    old = buy(w.tenant, w.owner, w.customer, w.plan, now=ist(2026, 1, 1, 9, 0)).pass_
    now = old.ends_at + timedelta(hours=2)
    new = buy(w.tenant, w.owner, w.customer, w.plan, now=now).pass_
    with w.ctx():
        assert fresh(old).status == "EXPIRED"
        assert new.status == "ACTIVE" and new.starts_at == now


# --- suspend / resume / cancel ---------------------------------------------------------------------
def test_suspend_resume_cancel_rules_and_audit():
    w = World()
    with w.ctx():
        with pytest.raises(NotAllowed):
            passes.suspend_pass(actor=w.manager, pass_public_id=w.pass_.public_id, reason="r")  # OWNER only
        with pytest.raises(ValidationFailed):
            passes.suspend_pass(actor=w.owner, pass_public_id=w.pass_.public_id, reason=" ")
        s = passes.suspend_pass(actor=w.owner, pass_public_id=w.pass_.public_id, reason="fraud")
        assert s.status == "SUSPENDED" and s.ends_at == w.pass_.ends_at  # ends_at is NOT extended
        with pytest.raises(StateConflict):
            passes.suspend_pass(actor=w.owner, pass_public_id=w.pass_.public_id, reason="again")
        r = passes.resume_pass(actor=w.owner, pass_public_id=w.pass_.public_id, reason="cleared")
        assert r.status == "ACTIVE"
        c = passes.cancel_pass(actor=w.owner, pass_public_id=w.pass_.public_id, reason="requested")
        assert c.status == "CANCELLED" and c.meals_remaining == 0
        zero = MealLedgerEntry.objects.get(pass_ref=w.pass_, entry_type="EXPIRE")
        assert zero.source == "ADMIN" and zero.quantity == -30 and zero.reason == "requested"
        with pytest.raises(StateConflict):
            passes.cancel_pass(actor=w.owner, pass_public_id=w.pass_.public_id, reason="twice")
        assert [a.action for a in AuditEvent.objects.filter(object_type="pass").order_by("id")][-3:] == [
            "pass.suspend",
            "pass.resume",
            "pass.cancel",
        ]
        assert ledger.find_mismatches() == []


def test_suspended_pass_still_expires_at_its_end_and_cannot_resume_after():
    w = World()
    with w.ctx():
        passes.suspend_pass(actor=w.owner, pass_public_id=w.pass_.public_id, reason="r")
        late = w.pass_.ends_at + timedelta(seconds=1)
        with pytest.raises(StateConflict):
            passes.resume_pass(actor=w.owner, pass_public_id=w.pass_.public_id, reason="r", now=late)
        assert passes.run_due_transitions(now=late)["expired"] == 1
        assert fresh(w.pass_).status == "EXPIRED"


def test_cancelling_a_queued_pass_writes_no_ledger_entry():
    w = World(buy_pass=False)
    buy(w.tenant, w.owner, w.customer, w.plan)
    q = buy(w.tenant, w.owner, w.customer, w.plan).pass_
    with w.ctx():
        passes.cancel_pass(actor=w.owner, pass_public_id=q.public_id, reason="dup")
        assert not MealLedgerEntry.objects.filter(pass_ref=q).exists()
        assert fresh(q).status == "CANCELLED"


def test_other_customer_unaffected():
    w = World()
    other, _ = make_customer(w.tenant, w.owner, name="Zed")
    buy(w.tenant, w.owner, other, w.plan)
    with w.ctx():
        passes.cancel_pass(actor=w.owner, pass_public_id=w.pass_.public_id, reason="r")
        assert Pass.objects.get(customer=other).status == "ACTIVE"
        assert uuid.UUID(str(w.pass_.public_id))
