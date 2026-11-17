# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from mealtally.accounts.models import Role
from mealtally.accounts.policy import Actor
from mealtally.common.errors import CooldownConfirmRequired
from mealtally.common.errors import DailyCapReached
from mealtally.common.errors import IdempotencyKeyReused
from mealtally.common.errors import NoActivePass
from mealtally.common.errors import NoCredits
from mealtally.common.errors import NotAllowed
from mealtally.common.errors import PassNotValidNow
from mealtally.common.errors import ValidationFailed
from mealtally.customers import services as customers
from mealtally.ledger import services as ledger
from mealtally.ledger.models import MealLedgerEntry
from mealtally.passes import services as passes
from mealtally.passes.models import Pass
from mealtally.tenancy import services as tenancy
from mealtally.testing import World
from mealtally.testing import make_customer

pytestmark = pytest.mark.django_db
SRC = MealLedgerEntry.Source


def key() -> str:
    return str(uuid.uuid4())


def do_redeem(w, *, actor=None, customer=None, confirm=True, now=None, idem=None, source=SRC.STAFF_SEARCH):
    return ledger.redeem(
        actor=actor or w.staff,
        customer=customer or w.customer,
        idempotency_key=idem or key(),
        source=source,
        confirm_additional=confirm,
        now=now,
    )


def test_redeem_happy_path():
    w = World()
    with w.ctx():
        res = do_redeem(w, source=SRC.QR_SCAN)
        assert res.replayed is False
        assert res.meals_remaining == 29
        assert res.entry.entry_type == "REDEEM" and res.entry.quantity == -1 and res.entry.balance_after == 29
        assert res.entry.source == "QR_SCAN" and res.entry.operator_id == w.staff.user.pk
        assert res.entry.meal_date == timezone.localdate(res.entry.occurred_at, timezone=w.tenant.zone)
        assert Pass.objects.get(pk=w.pass_.pk).meals_remaining == 29
        assert res.pass_.id == w.pass_.id and res.customer.id == w.customer.id


def test_idempotent_replay_writes_nothing_new():
    w = World()
    k = key()
    with w.ctx():
        first = do_redeem(w, idem=k)
        again = do_redeem(w, idem=k)
        assert again.replayed is True and again.entry.public_id == first.entry.public_id
        assert again.meals_remaining == first.meals_remaining
        assert MealLedgerEntry.objects.filter(entry_type="REDEEM").count() == 1
        assert Pass.objects.get(pk=w.pass_.pk).meals_remaining == 29


def test_key_cannot_be_reused_for_another_customer():
    w = World()
    other, _ = make_customer(w.tenant, w.owner, name="Other")
    from mealtally.testing import buy

    buy(w.tenant, w.owner, other, w.plan)
    k = key()
    with w.ctx():
        do_redeem(w, idem=k)
        with pytest.raises(IdempotencyKeyReused):
            do_redeem(w, customer=other, idem=k)


def test_missing_idempotency_key_is_a_validation_error():
    w = World()
    with w.ctx(), pytest.raises(ValidationFailed):
        ledger.redeem(actor=w.staff, customer=w.customer, idempotency_key="", source=SRC.STAFF_SEARCH)


def test_no_active_pass():
    w = World(buy_pass=False)
    with w.ctx(), pytest.raises(NoActivePass):
        do_redeem(w)


def test_pass_not_valid_now_after_end_and_before_start():
    w = World()
    with w.ctx():
        with pytest.raises(PassNotValidNow):
            do_redeem(w, now=w.pass_.ends_at + timedelta(seconds=1))
        with pytest.raises(PassNotValidNow):
            do_redeem(w, now=w.pass_.starts_at - timedelta(seconds=5))
        do_redeem(w, now=w.pass_.ends_at)  # inclusive upper bound


def test_no_credits():
    w = World(plan_kwargs={"meals_per_cycle": 1})
    with w.ctx():
        do_redeem(w)
        with pytest.raises(NoCredits):
            do_redeem(w)


def test_blocked_customer_and_inactive_tenant_are_not_allowed():
    w = World()
    with w.ctx():
        customers.set_status(actor=w.owner, customer=w.customer, status="BLOCKED", reason="abuse")
        with pytest.raises(NotAllowed):
            do_redeem(w)
        customers.set_status(actor=w.owner, customer=w.customer, status="ACTIVE")
        do_redeem(w)
    tenancy.set_status(tenant=w.tenant, status="SUSPENDED")
    with w.ctx(), pytest.raises(NotAllowed):
        do_redeem(w)


def test_suspended_pass_cannot_redeem():
    w = World()
    with w.ctx():
        passes.suspend_pass(actor=w.owner, pass_public_id=w.pass_.public_id, reason="chargeback")
        with pytest.raises(NoActivePass):
            do_redeem(w)


def test_customer_role_cannot_redeem():
    w = World()
    actor = Actor(user=w.customer.user, role=Role.CUSTOMER, tenant_id=w.tenant.id)
    with w.ctx(), pytest.raises(NotAllowed):
        do_redeem(w, actor=actor)


def test_max_meals_per_day_counts_net_redemptions():
    w = World(plan_kwargs={"max_meals_per_day": 2})
    with w.ctx():
        first = do_redeem(w)
        do_redeem(w)
        with pytest.raises(DailyCapReached):
            do_redeem(w)
        ledger.reverse_redemption(actor=w.manager, entry_public_id=first.entry.public_id, reason="mistake")
        do_redeem(w)  # net is 1 again
        with pytest.raises(DailyCapReached):
            do_redeem(w)


def test_max_meals_per_day_is_per_meal_date():
    w = World(plan_kwargs={"max_meals_per_day": 1})
    with w.ctx():
        t0 = timezone.now()
        do_redeem(w, now=t0)
        with pytest.raises(DailyCapReached):
            do_redeem(w, now=t0 + timedelta(minutes=5))
        do_redeem(w, now=t0 + timedelta(days=1))


def test_cooldown_guard_requires_confirmation_then_allows_two_meals():
    w = World()
    t0 = timezone.now()
    with w.ctx():
        do_redeem(w, now=t0, confirm=False)
        with pytest.raises(CooldownConfirmRequired) as exc:
            do_redeem(w, now=t0 + timedelta(seconds=30), confirm=False)
        assert exc.value.code == "COOLDOWN_CONFIRM_REQUIRED" and exc.value.details["cooldown_seconds"] == 120
        res = do_redeem(w, now=t0 + timedelta(seconds=30), confirm=True)
        assert res.meals_remaining == 28
        # outside the window no confirmation needed
        do_redeem(w, now=t0 + timedelta(seconds=30 + 121), confirm=False)


def test_cooldown_ignores_reversed_redemptions_and_is_configurable():
    w = World(tenant_settings={"redeem_cooldown_seconds": 10})
    t0 = timezone.now()
    with w.ctx():
        first = do_redeem(w, now=t0, confirm=False)
        ledger.reverse_redemption(actor=w.owner, entry_public_id=first.entry.public_id, reason="oops", now=t0)
        do_redeem(w, now=t0 + timedelta(seconds=1), confirm=False)  # previous *unreversed* redeem: none
        do_redeem(w, now=t0 + timedelta(seconds=12), confirm=False)  # > 10 s cooldown
