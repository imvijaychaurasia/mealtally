# SPDX-License-Identifier: AGPL-3.0-only
"""Recording / voiding payments and platform-fee accounting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

from mealtally.accounts.policy import Action
from mealtally.accounts.policy import Actor
from mealtally.accounts.policy import require
from mealtally.audit import services as audit
from mealtally.common.errors import NotAllowed
from mealtally.common.errors import NotFound
from mealtally.common.errors import StateConflict
from mealtally.common.errors import ValidationFailed
from mealtally.common.utils import percent_of_minor
from mealtally.customers import services as customers
from mealtally.ledger import services as ledger
from mealtally.passes import services as passes
from mealtally.passes.models import Pass
from mealtally.plans import services as plans
from mealtally.tenancy import services as tenancy
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.models import Tenant

from . import fees
from .models import FeePolicy
from .models import Payment
from .models import PlatformFeeEntry

DEFAULT_PLATFORM_PCT = Decimal("12.00")
DEFAULT_GATEWAY_PCT = Decimal("10.00")
_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class RecordedPayment:
    payment: Payment
    pass_: Pass


# --- fee policy ----------------------------------------------------------------------------------


def ensure_default_fee_policy(*, tenant_id: int) -> FeePolicy:
    with platform_context():
        policy = FeePolicy.objects.filter(tenant_id=tenant_id).first()
        if policy is None:
            policy = FeePolicy.objects.create(
                tenant_id=tenant_id,
                platform_pct=DEFAULT_PLATFORM_PCT,
                gateway_pct=DEFAULT_GATEWAY_PCT,
                effective_from=_EPOCH,
            )
    return policy


def set_fee_policy(
    *, tenant: Tenant, platform_pct: Decimal, gateway_pct: Decimal, effective_from: datetime | None = None, actor=None
) -> FeePolicy:
    """Platform admin: append a new policy row (history is kept; latest effective_from wins)."""
    for name, pct in (("platform_pct", platform_pct), ("gateway_pct", gateway_pct)):
        if not (Decimal(0) <= Decimal(pct) <= Decimal(100)):
            raise ValidationFailed("Percentages must be between 0 and 100.", details={"field": name})
    with platform_context(), transaction.atomic():
        policy = FeePolicy.objects.create(
            tenant_id=tenant.id,
            platform_pct=Decimal(pct_str(platform_pct)),
            gateway_pct=Decimal(pct_str(gateway_pct)),
            effective_from=effective_from or timezone.now(),
        )
        audit.record(
            action="fee_policy.set",
            tenant_id=tenant.id,
            actor=actor,
            object_type="fee_policy",
            object_public_id=policy.public_id,
            after={
                "platform_pct": str(policy.platform_pct),
                "gateway_pct": str(policy.gateway_pct),
                "effective_from": policy.effective_from.isoformat(),
            },
        )
    return policy


def pct_str(value) -> str:
    return str(Decimal(value).quantize(Decimal("0.01")))


def policy_for(received_at: datetime) -> tuple[Decimal, Decimal]:
    """(platform_pct, gateway_pct) in force at ``received_at``: latest effective_from <= it."""
    policy = FeePolicy.objects.filter(effective_from__lte=received_at).order_by("-effective_from", "-id").first()
    if policy is None:
        return DEFAULT_PLATFORM_PCT, DEFAULT_GATEWAY_PCT
    return policy.platform_pct, policy.gateway_pct


def _write_fee_entries(payment: Payment) -> list[PlatformFeeEntry]:
    platform_pct, gateway_pct = policy_for(payment.received_at)
    base = payment.amount_minor
    rows = [(PlatformFeeEntry.Kind.PLATFORM, platform_pct)]
    if payment.method == Payment.Method.GATEWAY:  # never in v1, but the path exists
        rows.append((PlatformFeeEntry.Kind.GATEWAY, gateway_pct))
    return [
        PlatformFeeEntry.objects.create(
            tenant_id=payment.tenant_id,
            payment=payment,
            kind=kind,
            base_minor=base,
            pct=pct,
            amount_minor=percent_of_minor(base, pct),
            sign=1,
        )
        for kind, pct in rows
    ]


# --- record --------------------------------------------------------------------------------------


def record_payment(
    *,
    actor: Actor,
    customer_public_id,
    plan_public_id,
    amount_minor: int,
    method: str,
    reference: str = "",
    received_at: datetime | None = None,
    now: datetime | None = None,
) -> RecordedPayment:
    """Payment + fee entries + pass (ACTIVE now, or QUEUED behind the current pass) + audit, atomically."""
    require(actor, Action.RECORD_PAYMENT)
    now = now or timezone.now()
    reference = (reference or "").strip()
    if method not in Payment.Method.values:
        raise ValidationFailed("Unknown payment method.", details={"field": "method"})
    if method != Payment.Method.CASH and not reference:
        raise ValidationFailed(
            "A reference (the UPI UTR or the bank transfer ID) is required for non-cash payments.",
            details={"field": "reference"},
        )
    with transaction.atomic():
        tenant = Tenant.objects.get(pk=actor.tenant_id)
        if tenant.status != Tenant.Status.ACTIVE:
            raise NotAllowed("This tenant is not active.")
        if method == Payment.Method.UPI_MANUAL and tenant.country != "IN":
            raise ValidationFailed("UPI is only offered for restaurants in India.", details={"field": "method"})
        # Lock the customer: serialises concurrent purchases (queue limit, one ACTIVE pass).
        customer = customers.get_customer(customer_public_id, lock=True)
        if customer.status != customer.Status.ACTIVE:
            raise NotAllowed("This customer is blocked.")
        plan = plans.get_plan(plan_public_id)
        if not plan.is_active:
            raise ValidationFailed("This plan is not active.", code="PLAN_INACTIVE", details={"field": "plan"})
        if amount_minor != plan.price_minor:
            raise ValidationFailed(
                "Amount must equal the plan price (no discounts in v1).",
                code="AMOUNT_MISMATCH",
                details={"expected_minor": plan.price_minor, "got_minor": amount_minor},
            )
        payment = Payment.objects.create(
            tenant_id=tenant.id,
            customer=customer,
            plan=plan,
            amount_minor=amount_minor,
            method=method,
            reference=reference,
            received_at=received_at or now,
            recorded_by=actor.user,
            receipt_number=tenancy.next_receipt_number(tenant.id),
        )
        if settings.MEALTALLY_PLATFORM_FEES:  # a self-hosted restaurant pays no platform fee
            _write_fee_entries(payment)
        pass_ = passes.create_pass_for_payment(
            actor=actor,
            tenant=tenant,
            settings_row=tenancy.get_settings(tenant.id),
            payment=payment,
            customer=customer,
            plan=plan,
            now=now,
        )
        audit.record(
            action="payment.record",
            tenant_id=tenant.id,
            actor=actor.user,
            object_type="payment",
            object_public_id=payment.public_id,
            after={
                "amount_minor": amount_minor,
                "method": method,
                "customer": str(customer.public_id),
                "pass": str(pass_.public_id),
                "pass_status": pass_.status,
            },
        )
    return RecordedPayment(payment=payment, pass_=pass_)


# --- void ----------------------------------------------------------------------------------------


def void_payment(*, actor: Actor, payment_public_id, reason: str, now: datetime | None = None) -> Payment:
    """OWNER/MANAGER. Only while the pass has no REDEEM entries; cancels the pass, reverses fees."""
    require(actor, Action.VOID_PAYMENT)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationFailed("A reason is required.", details={"field": "reason"})
    now = now or timezone.now()
    with transaction.atomic():
        try:
            payment = Payment.objects.select_for_update().get(public_id=payment_public_id)
        except (Payment.DoesNotExist, ValueError, TypeError, DjangoValidationError) as exc:
            raise NotFound("Payment not found.") from exc
        if payment.status == Payment.Status.VOIDED:
            raise StateConflict("This payment is already void.", code="ALREADY_VOIDED")
        pass_ = passes.get_pass_for_payment(payment, lock=True)
        if ledger.pass_has_redemptions(pass_):
            raise StateConflict("A payment cannot be voided once a meal was redeemed.", code="VOID_NOT_ALLOWED")
        if pass_.status not in (Pass.Status.ACTIVE, Pass.Status.QUEUED, Pass.Status.SUSPENDED):
            raise StateConflict("This payment's pass has already ended.", code="VOID_NOT_ALLOWED")
        passes.cancel_for_void(pass_=pass_, actor=actor, reason=reason, now=now)
        payment.status = Payment.Status.VOIDED
        payment.void_reason = reason
        payment.voided_by = actor.user
        payment.voided_at = now
        payment.save(update_fields=["status", "void_reason", "voided_by", "voided_at", "updated_at"])
        for fee in PlatformFeeEntry.objects.filter(payment=payment, sign=1):
            PlatformFeeEntry.objects.create(
                tenant_id=fee.tenant_id,
                payment=payment,
                kind=fee.kind,
                base_minor=fee.base_minor,
                pct=fee.pct,
                amount_minor=fee.amount_minor,
                sign=-1,
            )
        audit.record(
            action="payment.void",
            tenant_id=actor.tenant_id,
            actor=actor.user,
            object_type="payment",
            object_public_id=payment.public_id,
            before={"status": Payment.Status.RECORDED},
            after={"status": Payment.Status.VOIDED, "reason": reason, "pass": str(pass_.public_id)},
        )
    return payment


# --- reads ---------------------------------------------------------------------------------------


def get_payment(public_id) -> Payment:
    try:
        return Payment.objects.select_related("customer", "plan").get(public_id=public_id)
    except (Payment.DoesNotExist, ValueError, TypeError, DjangoValidationError) as exc:
        raise NotFound("Payment not found.") from exc


def payments_for_customer(customer_id: int):
    return Payment.objects.filter(customer_id=customer_id).select_related("plan").order_by("-received_at", "-id")


def fee_statement(*, actor: Actor, year: int, month: int) -> dict:
    """Monthly platform-fee statement (charges by payment month, voids by void month): see ``billing.fees``."""
    require(actor, Action.FEE_STATEMENT)
    if not (1 <= month <= 12):  # noqa: PLR2004
        raise ValidationFailed("month must be between 1 and 12.", details={"field": "month"})
    tenant = Tenant.objects.get(pk=actor.tenant_id)
    m = fees.fee_month(tenant, year, month)
    return {
        "month": m["month"],
        "currency": tenant.currency,
        "payments_count": m["payments_count"],
        "gross_minor": m["gross_minor"],
        "voided_count": m["voided_count"],
        "platform_fee_minor": m["platform_fee_minor"],
        "gateway_fee_minor": m["gateway_fee_minor"],
        "total_fee_minor": m["total_minor"],
        "net_to_tenant_minor": m["gross_minor"] - m["total_minor"],
        "lines": m["lines"],
        "entries": [
            {
                "id": str(e.public_id),
                "payment": str(e.payment.public_id),
                "kind": e.kind,
                "sign": e.sign,
                "base_minor": e.base_minor,
                "pct": str(e.pct),
                "amount_minor": e.amount_minor,
                "created_at": e.created_at.isoformat(),
            }
            for e in m["entries"]
        ],
    }
