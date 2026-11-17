from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from mealtally.audit.models import AuditEvent
from mealtally.common.errors import AlreadyReversed
from mealtally.common.errors import IdempotencyKeyReused
from mealtally.common.errors import NotAllowed
from mealtally.common.errors import NotFound
from mealtally.common.errors import StateConflict
from mealtally.common.errors import ValidationFailed
from mealtally.ledger import services as ledger
from mealtally.ledger.models import MealLedgerEntry
from mealtally.passes import services as passes
from mealtally.passes.models import Pass
from mealtally.testing import World

pytestmark = pytest.mark.django_db


def redeem(w, now=None):
    return ledger.redeem(
        actor=w.staff,
        customer=w.customer,
        idempotency_key=str(uuid.uuid4()),
        source="STAFF_SEARCH",
        confirm_additional=True,
        now=now,
    )


def test_reverse_restores_credit_links_entry_and_audits():
    w = World()
    with w.ctx():
        res = redeem(w)
        rev = ledger.reverse_redemption(actor=w.manager, entry_public_id=res.entry.public_id, reason="wrong customer")
        assert rev.entry_type == "REVERSAL" and rev.quantity == 1 and rev.balance_after == 30
        assert rev.reverses_id == res.entry.id and rev.meal_date == res.entry.meal_date
        assert Pass.objects.get(pk=w.pass_.pk).meals_remaining == 30
        event = AuditEvent.objects.get(action="ledger.reverse")
        assert event.object_public_id == res.entry.public_id and event.actor_id == w.manager.user.pk


def test_reverse_is_idempotent_and_at_most_once():
    w = World()
    with w.ctx():
        res = redeem(w)
        first = ledger.reverse_redemption(actor=w.owner, entry_public_id=res.entry.public_id, reason="r")
        again = ledger.reverse_redemption(actor=w.owner, entry_public_id=res.entry.public_id, reason="r")
        assert again.public_id == first.public_id  # default key == retry
        with pytest.raises(AlreadyReversed):
            ledger.reverse_redemption(
                actor=w.owner, entry_public_id=res.entry.public_id, reason="r", idempotency_key="a-different-key"
            )
        assert MealLedgerEntry.objects.filter(entry_type="REVERSAL").count() == 1


def test_reverse_requires_reason_redeem_type_and_known_entry():
    w = World()
    with w.ctx():
        res = redeem(w)
        with pytest.raises(ValidationFailed):
            ledger.reverse_redemption(actor=w.owner, entry_public_id=res.entry.public_id, reason=" ")
        issue = MealLedgerEntry.objects.get(entry_type="ISSUE")
        with pytest.raises(ValidationFailed):
            ledger.reverse_redemption(actor=w.owner, entry_public_id=issue.public_id, reason="x")
        with pytest.raises(NotFound):
            ledger.reverse_redemption(actor=w.owner, entry_public_id=uuid.uuid4(), reason="x")
        with pytest.raises(NotFound):
            ledger.reverse_redemption(actor=w.owner, entry_public_id="not-a-uuid", reason="x")


def test_reverse_key_cannot_be_hijacked():
    w = World()
    with w.ctx():
        a, b = redeem(w), redeem(w)
        rev = ledger.reverse_redemption(
            actor=w.owner, entry_public_id=a.entry.public_id, reason="r", idempotency_key="K1"
        )
        assert rev.idempotency_key == "K1"
        with pytest.raises(IdempotencyKeyReused):
            ledger.reverse_redemption(
                actor=w.owner, entry_public_id=b.entry.public_id, reason="r", idempotency_key="K1"
            )


def test_staff_may_reverse_only_inside_the_window_and_today():
    w = World(tenant_settings={"staff_reversal_window_hours": 12})
    t0 = timezone.now()
    with w.ctx():
        res = redeem(w, now=t0)
        late = t0 + timedelta(hours=13)
        with pytest.raises(NotAllowed):
            ledger.reverse_redemption(actor=w.staff, entry_public_id=res.entry.public_id, reason="r", now=late)
        # MANAGER / OWNER may reverse any time while the pass is ACTIVE
        rev = ledger.reverse_redemption(actor=w.manager, entry_public_id=res.entry.public_id, reason="r", now=late)
        assert rev.source == "ADMIN"
        res2 = redeem(w, now=t0)
        ok = ledger.reverse_redemption(
            actor=w.staff, entry_public_id=res2.entry.public_id, reason="r", now=t0 + timedelta(minutes=5)
        )
        assert ok.source == "STAFF_SEARCH"


def test_never_resurrect_credits_on_an_ended_pass():
    w = World()
    with w.ctx():
        res = redeem(w)
        passes.expire(Pass.objects.get(pk=w.pass_.pk), now=timezone.now())
        with pytest.raises(StateConflict) as exc:
            ledger.reverse_redemption(actor=w.owner, entry_public_id=res.entry.public_id, reason="late")
        assert exc.value.code == "PASS_NOT_ACTIVE"


def test_adjust_up_down_audited_and_never_negative():
    w = World()
    with w.ctx():
        up = ledger.adjust(
            actor=w.manager, pass_public_id=w.pass_.public_id, quantity=5, reason="goodwill", idempotency_key="adj-1"
        )
        assert up.entry_type == "ADJUST" and up.quantity == 5 and up.balance_after == 35 and up.source == "ADMIN"
        down = ledger.adjust(
            actor=w.owner, pass_public_id=w.pass_.public_id, quantity=-35, reason="correction", idempotency_key="adj-2"
        )
        assert down.balance_after == 0
        with pytest.raises(ValidationFailed) as exc:
            ledger.adjust(
                actor=w.owner, pass_public_id=w.pass_.public_id, quantity=-1, reason="too far", idempotency_key="adj-3"
            )
        assert exc.value.code == "INSUFFICIENT_BALANCE"
        assert Pass.objects.get(pk=w.pass_.pk).meals_remaining == 0
        assert AuditEvent.objects.filter(action="ledger.adjust").count() == 2


def test_adjust_rules():
    w = World()
    with w.ctx():
        with pytest.raises(NotAllowed):
            ledger.adjust(actor=w.staff, pass_public_id=w.pass_.public_id, quantity=1, reason="r", idempotency_key="a1")
        with pytest.raises(ValidationFailed):
            ledger.adjust(actor=w.owner, pass_public_id=w.pass_.public_id, quantity=1, reason="", idempotency_key="a2")
        with pytest.raises(ValidationFailed):
            ledger.adjust(actor=w.owner, pass_public_id=w.pass_.public_id, quantity=0, reason="r", idempotency_key="a3")
        first = ledger.adjust(
            actor=w.owner, pass_public_id=w.pass_.public_id, quantity=2, reason="r", idempotency_key="a4"
        )
        assert (
            ledger.adjust(
                actor=w.owner, pass_public_id=w.pass_.public_id, quantity=2, reason="r", idempotency_key="a4"
            ).id
            == first.id
        )
        passes.suspend_pass(actor=w.owner, pass_public_id=w.pass_.public_id, reason="r")
        with pytest.raises(StateConflict):
            ledger.adjust(actor=w.owner, pass_public_id=w.pass_.public_id, quantity=1, reason="r", idempotency_key="a5")


def test_reports_daily_visibility_by_role():
    w = World()
    with w.ctx():
        redeem(w)
        today = timezone.localdate(timezone.now(), timezone=w.tenant.zone)
        assert ledger.daily_redemptions(actor=w.staff, day=today).count() == 1
        with pytest.raises(NotAllowed):
            ledger.daily_redemptions(actor=w.staff, day=today - timedelta(days=1))
        assert ledger.daily_redemptions(actor=w.manager, day=today - timedelta(days=1)).count() == 0
