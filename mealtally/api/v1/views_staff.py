from __future__ import annotations

from datetime import date

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response

from mealtally.accounts.models import STAFF_ROLES
from mealtally.api import serializers as s
from mealtally.api.base import TenantAPIView
from mealtally.api.throttles import RedeemTenantThrottle
from mealtally.api.throttles import RedeemUserThrottle
from mealtally.billing import services as billing
from mealtally.common.errors import ValidationFailed
from mealtally.common.utils import local_date
from mealtally.customers import qr
from mealtally.customers import services as customers
from mealtally.ledger import services as ledger
from mealtally.ledger.models import MealLedgerEntry
from mealtally.passes import services as passes
from mealtally.plans import services as plans


def _customer_detail(customer) -> dict:
    active = passes.active_pass_for(customer.id)
    return {
        **s.customer_out(customer),
        "notes": customer.notes,
        "active_pass": s.pass_out(active, consumed=ledger.consumed_count(active)) if active else None,
        "queued_passes": [s.pass_out(p) for p in passes.queued_passes_for(customer.id)],
    }


def _redeem_out(result) -> dict:
    return {
        "entry_public_id": str(result.entry.public_id),
        "customer": s.customer_out(result.customer),
        "pass": s.pass_out(result.pass_),
        "meals_remaining": result.meals_remaining,
        "meal_date": result.meal_date.isoformat(),
        "replayed": result.replayed,
    }


class _StaffView(TenantAPIView):
    allowed_roles = STAFF_ROLES


class CustomerListCreateView(_StaffView):
    @extend_schema(responses=dict)
    def get(self, request):
        rows = customers.search(request.query_params.get("search", ""))
        return Response({"results": [s.customer_out(c) for c in rows]})

    @extend_schema(request=s.CustomerCreateIn, responses=dict)
    def post(self, request):
        data = s.CustomerCreateIn(data=request.data)
        data.is_valid(raise_exception=True)
        customer, pin = customers.create_customer(
            actor=request.actor, pin=request.data.get("pin") or None, **data.validated_data
        )
        # The PIN is shown exactly once; only its hash is stored.
        return Response({**_customer_detail(customer), "initial_pin": pin}, status=status.HTTP_201_CREATED)


class CustomerDetailView(_StaffView):
    @extend_schema(responses=dict)
    def get(self, request, customer_id):
        return Response(_customer_detail(customers.get_customer(customer_id)))


class CustomerResetPinView(_StaffView):
    @extend_schema(request=None, responses=dict)
    def post(self, request, customer_id):
        customer = customers.get_customer(customer_id)
        return Response(
            {
                "customer": s.customer_out(customer),
                "pin": customers.reset_pin(actor=request.actor, customer=customer, pin=request.data.get("pin") or None),
            }
        )


class PlanListView(_StaffView):
    @extend_schema(responses=dict)
    def get(self, request):
        return Response({"results": [s.plan_out(p) for p in plans.list_plans()]})


class PaymentCreateView(_StaffView):
    @extend_schema(request=s.PaymentCreateIn, responses=dict)
    def post(self, request):
        data = s.PaymentCreateIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        result = billing.record_payment(
            actor=request.actor,
            customer_public_id=v["customer"],
            plan_public_id=v["plan"],
            amount_paise=v["amount_paise"],
            method=v["method"],
            reference=v["reference"],
            received_at=v.get("received_at"),
        )
        return Response(
            {"payment": s.payment_out(result.payment), "pass": s.pass_out(result.pass_)}, status=status.HTTP_201_CREATED
        )


class PaymentVoidView(_StaffView):
    @extend_schema(request=s.ReasonIn, responses=dict)
    def post(self, request, payment_id):
        data = s.ReasonIn(data=request.data)
        data.is_valid(raise_exception=True)
        payment = billing.void_payment(
            actor=request.actor, payment_public_id=payment_id, reason=data.validated_data["reason"]
        )
        return Response({"payment": s.payment_out(payment)})


class RedeemView(_StaffView):
    throttle_classes = (RedeemUserThrottle, RedeemTenantThrottle)

    @extend_schema(request=s.RedeemIn, responses=dict)
    def post(self, request):
        data = s.RedeemIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        customer = customers.get_customer(v["customer"])
        result = ledger.redeem(
            actor=request.actor,
            customer=customer,
            idempotency_key=v["idempotency_key"],
            source=MealLedgerEntry.Source.STAFF_SEARCH,
            confirm_additional=v["confirm_additional"],
            device_ref=v["device_ref"],
        )
        return Response(_redeem_out(result), status=status.HTTP_200_OK if result.replayed else status.HTTP_201_CREATED)


class RedeemQrView(_StaffView):
    throttle_classes = (RedeemUserThrottle, RedeemTenantThrottle)

    @extend_schema(request=s.RedeemQrIn, responses=dict)
    def post(self, request):
        data = s.RedeemQrIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        payload = qr.resolve(v["token"], tenant=request.tenant)
        customer = customers.get_customer(payload["cid"])
        qr.claim_jti(payload["jti"], v["idempotency_key"])
        result = ledger.redeem(
            actor=request.actor,
            customer=customer,
            idempotency_key=v["idempotency_key"],
            source=MealLedgerEntry.Source.QR_SCAN,
            confirm_additional=v["confirm_additional"],
        )
        return Response(_redeem_out(result), status=status.HTTP_200_OK if result.replayed else status.HTTP_201_CREATED)


class LedgerReverseView(_StaffView):
    @extend_schema(request=s.ReverseIn, responses=dict)
    def post(self, request, entry_id):
        data = s.ReverseIn(data=request.data)
        data.is_valid(raise_exception=True)
        entry = ledger.reverse_redemption(
            actor=request.actor,
            entry_public_id=entry_id,
            reason=data.validated_data["reason"],
            idempotency_key=data.validated_data.get("idempotency_key"),
        )
        return Response(
            {"reversal": s.entry_out(entry), "meals_remaining": entry.balance_after}, status=status.HTTP_201_CREATED
        )


class PassAdjustView(_StaffView):
    @extend_schema(request=s.AdjustIn, responses=dict)
    def post(self, request, pass_id):
        data = s.AdjustIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        entry = ledger.adjust(
            actor=request.actor,
            pass_public_id=pass_id,
            quantity=v["quantity"],
            reason=v["reason"],
            idempotency_key=v["idempotency_key"],
        )
        return Response(
            {"adjustment": s.entry_out(entry), "meals_remaining": entry.balance_after}, status=status.HTTP_201_CREATED
        )


class _PassReasonView(_StaffView):
    service = None

    @extend_schema(request=s.ReasonIn, responses=dict)
    def post(self, request, pass_id):
        data = s.ReasonIn(data=request.data)
        data.is_valid(raise_exception=True)
        pass_ = type(self).service(actor=request.actor, pass_public_id=pass_id, reason=data.validated_data["reason"])
        return Response({"pass": s.pass_out(pass_)})


class PassSuspendView(_PassReasonView):
    service = staticmethod(passes.suspend_pass)


class PassResumeView(_PassReasonView):
    service = staticmethod(passes.resume_pass)


class PassCancelView(_PassReasonView):
    service = staticmethod(passes.cancel_pass)


class DailyReportView(_StaffView):
    @extend_schema(responses=dict)
    def get(self, request):
        raw = request.query_params.get("date")
        try:
            day = date.fromisoformat(raw) if raw else local_date(timezone.now(), request.tenant.timezone)
        except ValueError as exc:
            raise ValidationFailed("date must be YYYY-MM-DD.", details={"field": "date"}) from exc
        rows = list(ledger.daily_redemptions(actor=request.actor, day=day))
        reversed_flags = [hasattr(r, "reversal") for r in rows]
        return Response(
            {
                "date": day.isoformat(),
                "count": sum(1 for flag in reversed_flags if not flag),
                "total_redemptions": len(rows),
                "entries": [
                    {
                        "id": str(r.public_id),
                        "customer": s.customer_out(r.customer),
                        "occurred_at": s.iso(r.occurred_at),
                        "source": r.source,
                        "operator": r.operator.get_username() if r.operator else None,
                        "reversed": flag,
                    }
                    for r, flag in zip(rows, reversed_flags, strict=True)
                ],
            }
        )


class FeeReportView(_StaffView):
    @extend_schema(responses=dict)
    def get(self, request):
        raw = request.query_params.get("month", "")
        try:
            year_s, month_s = raw.split("-")
            year, month = int(year_s), int(month_s)
        except ValueError as exc:
            raise ValidationFailed("month must be YYYY-MM.", details={"field": "month"}) from exc
        return Response(billing.fee_statement(actor=request.actor, year=year, month=month))
