# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from mealtally.audit.models import AuditEvent
from mealtally.billing import services as billing
from mealtally.billing.models import FeePolicy
from mealtally.billing.models import Payment
from mealtally.billing.models import PlatformFeeEntry
from mealtally.common.errors import NotAllowed
from mealtally.common.errors import NotFound
from mealtally.common.errors import StateConflict
from mealtally.common.errors import ValidationFailed
from mealtally.common.utils import percent_of_minor
from mealtally.customers import services as customers
from mealtally.ledger import services as ledger
from mealtally.ledger.models import MealLedgerEntry
from mealtally.passes.models import Pass
from mealtally.tenancy import services as tenancy
from mealtally.testing import World
from mealtally.testing import buy

pytestmark = pytest.mark.django_db


def pay(w, *, actor=None, **kw):
    args = {
        "actor": actor or w.staff,
        "customer_public_id": w.customer.public_id,
        "plan_public_id": w.plan.public_id,
        "amount_minor": w.plan.price_minor,
        "method": "CASH",
    }
    args.update(kw)
    with w.ctx():
        return billing.record_payment(**args)


# --- fees ------------------------------------------------------------------------------------------
def test_platform_fee_is_12_percent_of_1500_major_is_18000_minor():
    w = World()
    with w.ctx():
        fees = list(PlatformFeeEntry.objects.all())
    assert len(fees) == 1
    fee = fees[0]
    assert (fee.kind, fee.base_minor, fee.pct, fee.amount_minor, fee.sign) == (
        "PLATFORM",
        150000,
        Decimal("12.00"),
        18000,
        1,
    )


@pytest.mark.parametrize(
    ("base", "pct", "expected"),
    [
        (150000, "12.00", 18000),
        (5, "10.00", 1),
        (15, "10.00", 2),
        (14, "10.00", 1),
        (1, "49.99", 0),
        (3, "50.00", 2),
        (999, "12.50", 125),
        (0, "12", 0),
    ],
)
def test_percent_rounding_is_half_up(base, pct, expected):
    assert percent_of_minor(base, Decimal(pct)) == expected


def test_fee_policy_effective_from_selects_the_applicable_row():
    w = World(buy_pass=False)
    t0 = timezone.now()
    billing.set_fee_policy(
        tenant=w.tenant,
        platform_pct=Decimal("15.00"),
        gateway_pct=Decimal("9.00"),
        effective_from=t0 + timedelta(days=1),
    )
    old = pay(w, received_at=t0, reference="")  # before the new policy takes effect -> default 12%
    new = pay(w, received_at=t0 + timedelta(days=2), actor=w.owner)  # w.customer already has pass; queue ok (max 1)
    with w.ctx():
        pcts = {f.payment_id: (f.pct, f.amount_minor) for f in PlatformFeeEntry.objects.all()}
    assert pcts[old.payment.id] == (Decimal("12.00"), 18000)
    assert pcts[new.payment.id] == (Decimal("15.00"), 22500)


def test_set_fee_policy_validates_and_audits():
    w = World(buy_pass=False)
    with pytest.raises(ValidationFailed):
        billing.set_fee_policy(tenant=w.tenant, platform_pct=Decimal("101"), gateway_pct=Decimal("1"))
    billing.set_fee_policy(tenant=w.tenant, platform_pct=Decimal("8"), gateway_pct=Decimal("5"), actor=w.owner.user)
    with w.ctx():
        assert FeePolicy.objects.count() == 2  # default + new (history kept)
        assert AuditEvent.objects.filter(action="fee_policy.set").exists()


def test_gateway_payments_also_get_a_gateway_fee_entry():
    w = World(buy_pass=False)
    rec = pay(w, method="GATEWAY", reference="pay_ABC123")
    with w.ctx():
        kinds = {f.kind: f.amount_minor for f in PlatformFeeEntry.objects.filter(payment=rec.payment)}
    assert kinds == {"PLATFORM": 18000, "GATEWAY": 15000}  # 10% gateway


# --- recording -------------------------------------------------------------------------------------
def test_record_payment_creates_payment_fee_pass_and_audit_atomically():
    w = World(buy_pass=False)
    rec = pay(w, method="UPI_MANUAL", reference="UTR123456")
    assert rec.payment.status == "RECORDED" and rec.payment.reference == "UTR123456"
    assert rec.pass_.status == "ACTIVE" and rec.pass_.meals_remaining == 30 and rec.pass_.payment_id == rec.payment.id
    assert (rec.pass_.plan_name, rec.pass_.price_minor, rec.pass_.meals_total) == ("Monthly Meal Pass", 150000, 30)
    with w.ctx():
        ev = AuditEvent.objects.get(action="payment.record")
        assert ev.after["pass"] == str(rec.pass_.public_id) and ev.actor_id == w.staff.user.pk


def test_pass_snapshot_is_unaffected_by_later_plan_edits():
    w = World()
    with w.ctx():
        w.plan.price_minor = 200000
        w.plan.meals_per_cycle = 60
        w.plan.save()
        p = Pass.objects.get(pk=w.pass_.pk)
    assert (p.price_minor, p.meals_total) == (150000, 30)


@pytest.mark.parametrize(
    ("kwargs", "code", "field"),
    [
        ({"amount_minor": 140000}, "AMOUNT_MISMATCH", None),
        ({"method": "UPI_MANUAL", "reference": ""}, "VALIDATION_ERROR", "reference"),
        ({"method": "CARD_MANUAL", "reference": "  "}, "VALIDATION_ERROR", "reference"),
        ({"method": "BITCOIN"}, "VALIDATION_ERROR", "method"),
    ],
)
def test_record_payment_validation(kwargs, code, field):
    w = World(buy_pass=False)
    with pytest.raises(ValidationFailed) as exc:
        pay(w, **kwargs)
    assert exc.value.code == code
    if field:
        assert exc.value.details["field"] == field
    with w.ctx():
        assert not Payment.objects.exists() and not Pass.objects.exists()  # nothing half-written


def test_record_payment_rejects_inactive_plan_blocked_customer_and_inactive_tenant():
    w = World(buy_pass=False)
    with w.ctx():
        w.plan.is_active = False
        w.plan.save()
    with pytest.raises(ValidationFailed) as exc:
        pay(w)
    assert exc.value.code == "PLAN_INACTIVE"
    with w.ctx():
        w.plan.is_active = True
        w.plan.save()
        customers.set_status(actor=w.owner, customer=w.customer, status="BLOCKED")
    with pytest.raises(NotAllowed):
        pay(w)
    with w.ctx():
        customers.set_status(actor=w.owner, customer=w.customer, status="ACTIVE")
    tenancy.set_status(tenant=w.tenant, status="SUSPENDED")
    with pytest.raises(NotAllowed):
        pay(w)


def test_unknown_customer_or_plan_is_not_found_and_customer_role_cannot_pay():
    import uuid

    from mealtally.accounts.models import Role
    from mealtally.accounts.policy import Actor

    w = World(buy_pass=False)
    with pytest.raises(NotFound):
        pay(w, customer_public_id=uuid.uuid4())
    with pytest.raises(NotFound):
        pay(w, plan_public_id=uuid.uuid4())
    cust = Actor(user=w.customer.user, role=Role.CUSTOMER, tenant_id=w.tenant.id)
    with pytest.raises(NotAllowed):
        pay(w, actor=cust)


# --- void ------------------------------------------------------------------------------------------
def test_void_cancels_pass_zeroes_credits_reverses_fees_and_audits():
    w = World()
    with w.ctx():
        voided = billing.void_payment(
            actor=w.manager, payment_public_id=w.recorded.payment.public_id, reason="entered twice"
        )
        assert (
            voided.status == "VOIDED"
            and voided.void_reason == "entered twice"
            and voided.voided_by_id == w.manager.user.pk
        )
        assert Pass.objects.get(pk=w.pass_.pk).status == "CANCELLED"
        zero = MealLedgerEntry.objects.get(pass_ref=w.pass_, entry_type="EXPIRE")
        assert zero.source == "ADMIN" and zero.quantity == -30 and zero.reason == "entered twice"
        fees = list(PlatformFeeEntry.objects.order_by("id").values_list("sign", "amount_minor"))
        assert fees == [(1, 18000), (-1, 18000)]  # net zero
        assert AuditEvent.objects.filter(action="payment.void").count() == 1
        assert ledger.find_mismatches() == []


def test_void_rules():
    w = World()
    pid = w.recorded.payment.public_id
    with w.ctx():
        with pytest.raises(NotAllowed):
            billing.void_payment(actor=w.staff, payment_public_id=pid, reason="r")
        with pytest.raises(ValidationFailed):
            billing.void_payment(actor=w.owner, payment_public_id=pid, reason="")
        ledger.redeem(actor=w.staff, customer=w.customer, idempotency_key="v1", source="STAFF_SEARCH")
        with pytest.raises(StateConflict) as exc:
            billing.void_payment(actor=w.owner, payment_public_id=pid, reason="r")
        assert (
            exc.value.code == "VOID_NOT_ALLOWED"
        )  # even if the redemption were reversed later: no REDEEM entries allowed


def test_void_not_allowed_after_redemption_was_reversed_either():
    w = World()
    with w.ctx():
        res = ledger.redeem(actor=w.staff, customer=w.customer, idempotency_key="v2", source="STAFF_SEARCH")
        ledger.reverse_redemption(actor=w.owner, entry_public_id=res.entry.public_id, reason="oops")
        with pytest.raises(StateConflict):
            billing.void_payment(actor=w.owner, payment_public_id=w.recorded.payment.public_id, reason="r")


def test_void_queued_pass_and_double_void_and_ended_pass():
    w = World()
    queued = buy(w.tenant, w.owner, w.customer, w.plan)
    with w.ctx():
        billing.void_payment(actor=w.owner, payment_public_id=queued.payment.public_id, reason="dup")
        assert Pass.objects.get(pk=queued.pass_.pk).status == "CANCELLED"
        assert not MealLedgerEntry.objects.filter(pass_ref=queued.pass_).exists()
        with pytest.raises(StateConflict) as exc:
            billing.void_payment(actor=w.owner, payment_public_id=queued.payment.public_id, reason="dup")
        assert exc.value.code == "ALREADY_VOIDED"
        from mealtally.passes import services as passes

        passes.expire(Pass.objects.get(pk=w.pass_.pk), now=timezone.now())
        with pytest.raises(StateConflict):
            billing.void_payment(actor=w.owner, payment_public_id=w.recorded.payment.public_id, reason="late")
        with pytest.raises(NotFound):
            billing.void_payment(actor=w.owner, payment_public_id="nope", reason="x")


# --- statement -------------------------------------------------------------------------------------
def test_fee_statement_nets_charges_and_voids():
    w = World()
    second = buy(w.tenant, w.owner, w.customer, w.plan)  # queued
    now = timezone.now().astimezone(w.tenant.zone)
    with w.ctx():
        billing.void_payment(actor=w.owner, payment_public_id=second.payment.public_id, reason="dup")
        stmt = billing.fee_statement(actor=w.owner, year=now.year, month=now.month)
        assert stmt["payments_count"] == 1 and stmt["gross_minor"] == 150000
        assert stmt["voided_count"] == 1
        assert stmt["platform_fee_minor"] == 18000 and stmt["gateway_fee_minor"] == 0
        assert stmt["net_to_tenant_minor"] == 132000
        assert len(stmt["entries"]) == 3  # +, +, - (the voided payment's charge and its reversal)
        with pytest.raises(NotAllowed):
            billing.fee_statement(actor=w.staff, year=now.year, month=now.month)
        with pytest.raises(NotAllowed):  # owner only
            billing.fee_statement(actor=w.manager, year=now.year, month=now.month)
        with pytest.raises(ValidationFailed):
            billing.fee_statement(actor=w.owner, year=2026, month=13)
