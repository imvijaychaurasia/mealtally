# SPDX-License-Identifier: AGPL-3.0-only
"""Input validation (DRF serializers) and output shaping (plain dicts keyed by ``public_id``)."""

from __future__ import annotations

from rest_framework import serializers

from mealtally.billing.models import Payment


# --- input ---------------------------------------------------------------------------------------
class StaffLoginIn(serializers.Serializer):
    login = serializers.CharField(help_text="E-mail or phone number")
    password = serializers.CharField(trim_whitespace=False)


class CustomerLoginIn(serializers.Serializer):
    phone = serializers.CharField()
    pin = serializers.CharField(trim_whitespace=False)


class CustomerCreateIn(serializers.Serializer):
    full_name = serializers.CharField(max_length=200)
    phone = serializers.CharField(max_length=32)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class OwnProfileIn(serializers.Serializer):
    full_name = serializers.CharField(max_length=200)


class PaymentCreateIn(serializers.Serializer):
    customer = serializers.UUIDField()
    plan = serializers.UUIDField()
    amount_minor = serializers.IntegerField(min_value=1)
    method = serializers.ChoiceField(choices=[m for m in Payment.Method.values if m != Payment.Method.GATEWAY])
    reference = serializers.CharField(required=False, allow_blank=True, default="", max_length=120)
    received_at = serializers.DateTimeField(required=False)


class ReasonIn(serializers.Serializer):
    reason = serializers.CharField()


class RedeemIn(serializers.Serializer):
    customer = serializers.UUIDField()
    idempotency_key = serializers.CharField(max_length=200)
    confirm_additional = serializers.BooleanField(required=False, default=False)
    device_ref = serializers.CharField(required=False, allow_null=True, allow_blank=True, default=None)


class RedeemQrIn(serializers.Serializer):
    token = serializers.CharField()
    idempotency_key = serializers.CharField(max_length=200)
    confirm_additional = serializers.BooleanField(required=False, default=False)


class ReverseIn(serializers.Serializer):
    reason = serializers.CharField()
    idempotency_key = serializers.CharField(required=False, max_length=200)


class AdjustIn(serializers.Serializer):
    quantity = serializers.IntegerField()
    reason = serializers.CharField()
    idempotency_key = serializers.CharField(max_length=200)


class TenantCreateIn(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    slug = serializers.SlugField(max_length=50)
    timezone = serializers.CharField(required=False, default="Asia/Kolkata")


class TenantStatusIn(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class FeePolicyIn(serializers.Serializer):
    platform_pct = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100)
    gateway_pct = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100)
    effective_from = serializers.DateTimeField(required=False)


# --- output --------------------------------------------------------------------------------------
def iso(dt):
    return dt.isoformat() if dt else None


def customer_out(c) -> dict:
    return {
        "id": str(c.public_id),
        "customer_code": c.customer_code,
        "full_name": c.full_name,
        "phone": c.phone_e164,
        "status": c.status,
        "address": c.address,
    }


def pass_out(p, *, consumed: int | None = None) -> dict:
    data = {
        "id": str(p.public_id),
        "status": p.status,
        "plan_name": p.plan_name,
        "price_minor": p.price_minor,
        "validity_mode": p.validity_mode,
        "max_meals_per_day": p.max_meals_per_day,
        "meals_total": p.meals_total,
        "meals_remaining": p.meals_remaining,
        "starts_at": iso(p.starts_at),
        "ends_at": iso(p.ends_at),
    }
    if consumed is not None:
        data["meals_consumed"] = consumed
    return data


def payment_out(p) -> dict:
    return {
        "id": str(p.public_id),
        "amount_minor": p.amount_minor,
        "method": p.method,
        "reference": p.reference,
        "status": p.status,
        "received_at": iso(p.received_at),
        "plan_name": p.plan.name if p.plan_id else None,
    }


def entry_out(e) -> dict:
    return {
        "id": str(e.public_id),
        "entry_type": e.entry_type,
        "quantity": e.quantity,
        "balance_after": e.balance_after,
        "meal_date": e.meal_date.isoformat(),
        "occurred_at": iso(e.occurred_at),
        "source": e.source,
        "reason": e.reason,
        "reverses": str(e.reverses.public_id) if e.reverses_id and getattr(e, "reverses", None) else None,
        "pass": str(e.pass_ref.public_id),
    }


def plan_out(p) -> dict:
    return {
        "id": str(p.public_id),
        "name": p.name,
        "price_minor": p.price_minor,
        "meals_per_cycle": p.meals_per_cycle,
        "validity_mode": p.validity_mode,
        "validity_days": p.validity_days,
        "max_meals_per_day": p.max_meals_per_day,
        "is_active": p.is_active,
    }


def tenant_out(t) -> dict:
    return {
        "id": str(t.public_id),
        "slug": t.slug,
        "name": t.name,
        "status": t.status,
        "timezone": t.timezone,
        "currency": t.currency,
    }
