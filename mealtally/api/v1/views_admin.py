"""API parity for the D02 UI: everything a screen can do is also available as JSON (future mobile apps)."""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import update_session_auth_hash
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from mealtally.accounts import services as accounts
from mealtally.accounts.models import STAFF_ROLES
from mealtally.accounts.models import Role
from mealtally.api import serializers as s
from mealtally.api.base import ALL_ROLES
from mealtally.api.base import PlatformAPIView
from mealtally.api.base import TenantAPIView
from mealtally.api.throttles import LoginThrottle
from mealtally.billing import receipts
from mealtally.billing import services as billing
from mealtally.common.errors import NotFound
from mealtally.common.errors import ValidationFailed
from mealtally.common.utils import local_date
from mealtally.customers import services as customers
from mealtally.passes import services as passes
from mealtally.plans import services as plans
from mealtally.reports import services as reports
from mealtally.tenancy import services as tenancy
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.models import Tenant

OBJ = inline_serializer("Object", fields={"detail": serializers.CharField(required=False)})


def _date(raw, default):
    try:
        return date.fromisoformat(raw) if raw else default
    except ValueError as exc:
        raise ValidationFailed("Dates must be YYYY-MM-DD.", details={"field": "date"}) from exc


def _period(request):
    today = local_date(timezone.now(), request.tenant.timezone)
    return _date(request.query_params.get("start"), today - timedelta(days=29)), _date(
        request.query_params.get("end"), today
    )


def _month(request):
    raw = request.query_params.get("month", "")
    try:
        y, m = raw.split("-")
        return int(y), int(m)
    except ValueError:
        today = local_date(timezone.now(), request.tenant.timezone)
        return today.year, today.month


def _csv_or_json(request, header, rows, payload, name):
    if request.query_params.get("export") == "csv":  # not "format": DRF reserves ?format= for renderer selection
        resp = HttpResponse(reports.to_csv(header, rows), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{name}.csv"'
        return resp
    return Response(payload)


class _Staff(TenantAPIView):
    allowed_roles = STAFF_ROLES


# --- auth / self-service --------------------------------------------------------------------------------------
class ChangePasswordView(APIView):
    """Any signed-in user (forced first-login change for staff)."""

    @extend_schema(
        request=inline_serializer(
            "ChangePassword", {"old_password": serializers.CharField(), "new_password": serializers.CharField()}
        ),
        responses=OBJ,
    )
    def post(self, request):
        accounts.change_password(
            user=request.user,
            old_password=request.data.get("old_password", ""),
            new_password=request.data.get("new_password", ""),
        )
        update_session_auth_hash(request._request, request.user)  # stay signed in after the hash changes
        return Response({"detail": "Password changed."})


class CustomerSignupView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (LoginThrottle,)

    @extend_schema(
        request=inline_serializer(
            "Signup",
            {"full_name": serializers.CharField(), "phone": serializers.CharField(), "pin": serializers.CharField()},
        ),
        responses=OBJ,
    )
    def post(self, request, tenant_slug):
        tenant = tenancy.get_tenant_by_slug(tenant_slug)
        if tenant.status != Tenant.Status.ACTIVE:
            raise NotFound("Not found.")
        from mealtally.tenancy.context import tenant_context  # noqa: PLC0415

        with tenant_context(tenant.id):
            c = customers.self_signup(
                tenant_id=tenant.id,
                full_name=request.data.get("full_name", ""),
                phone=request.data.get("phone", ""),
                pin=request.data.get("pin", ""),
            )
            return Response(
                {"customer": s.customer_out(c), "detail": "Account created. Pay at the counter to start your pass."},
                status=status.HTTP_201_CREATED,
            )


class MeChangePinView(TenantAPIView):
    allowed_roles = ALL_ROLES
    credential_exempt = True

    @extend_schema(
        request=inline_serializer(
            "ChangePin", {"old_pin": serializers.CharField(), "new_pin": serializers.CharField()}
        ),
        responses=OBJ,
    )
    def post(self, request):
        c = customers.get_customer_for_user(user=request.user, tenant_id=request.tenant.id)
        customers.change_pin(
            customer=c, old_pin=request.data.get("old_pin", ""), new_pin=request.data.get("new_pin", "")
        )
        return Response({"detail": "PIN changed."})


# --- customers ---------------------------------------------------------------------------------------------------
class CustomerAdminListView(_Staff):
    @extend_schema(responses=OBJ)
    def get(self, request):
        rows = customers.list_customers(
            query=request.query_params.get("search", ""), status=request.query_params.get("status", "")
        )
        return Response(
            {
                "results": [
                    {**s.customer_out(c), "has_active_pass": c.has_active, "expiring": c.has_expiring} for c in rows
                ]
            }
        )


class CustomerUpdateView(_Staff):
    @extend_schema(
        request=inline_serializer(
            "CustomerUpdate",
            {
                "full_name": serializers.CharField(),
                "notes": serializers.CharField(required=False),
                "address": serializers.CharField(required=False),
            },
        ),
        responses=OBJ,
    )
    def patch(self, request, customer_id):
        c = customers.update_customer(
            actor=request.actor,
            customer=customers.get_customer(customer_id),
            full_name=request.data.get("full_name", ""),
            notes=request.data.get("notes", ""),
            address=request.data.get("address"),
        )
        return Response(s.customer_out(c))


class CustomerBlockView(_Staff):
    block = True

    @extend_schema(request=s.ReasonIn, responses=OBJ)
    def post(self, request, customer_id):
        c = customers.set_status(
            actor=request.actor,
            customer=customers.get_customer(customer_id),
            status="BLOCKED" if self.block else "ACTIVE",
            reason=request.data.get("reason", ""),
        )
        return Response(s.customer_out(c))


class CustomerUnblockView(CustomerBlockView):
    block = False


# --- plans ---------------------------------------------------------------------------------------------------------
def _plan_in(data) -> dict:
    out = {}
    for key in ("name", "meals_per_cycle", "validity_mode", "validity_days", "max_meals_per_day", "is_active"):
        if key in data:
            out[key] = data[key]
    if "price_paise" in data:
        out["price_paise"] = data["price_paise"]
    elif "price_rupees" in data:
        out["price_paise"] = int(Decimal(str(data["price_rupees"])) * 100)
    return out


class PlanAdminView(_Staff):
    @extend_schema(responses=OBJ)
    def get(self, request):
        return Response(
            {"results": [s.plan_out(p) for p in plans.list_plans(active_only=request.query_params.get("all") != "1")]}
        )

    @extend_schema(request=OBJ, responses=OBJ)
    def post(self, request):
        return Response(
            s.plan_out(plans.save_plan(actor=request.actor, **_plan_in(request.data))), status=status.HTTP_201_CREATED
        )


class PlanDetailView(_Staff):
    @extend_schema(request=OBJ, responses=OBJ)
    def patch(self, request, plan_id):
        return Response(
            s.plan_out(plans.save_plan(actor=request.actor, plan=plans.get_plan(plan_id), **_plan_in(request.data)))
        )


# --- staff (OWNER) -------------------------------------------------------------------------------------------------
def _member_out(m):
    return {
        "user_id": m.user_id,
        "name": m.user.name,
        "email": m.user.email,
        "phone": m.user.phone_e164,
        "role": m.role,
        "is_active": m.is_active,
    }


class StaffListView(_Staff):
    @extend_schema(responses=OBJ)
    def get(self, request):
        return Response({"results": [_member_out(m) for m in accounts.list_staff(request.tenant.id)]})

    @extend_schema(
        request=inline_serializer(
            "AddStaff",
            {
                "name": serializers.CharField(),
                "email": serializers.EmailField(required=False),
                "phone": serializers.CharField(required=False),
                "role": serializers.CharField(),
            },
        ),
        responses=OBJ,
    )
    def post(self, request):
        d = request.data
        user, password = accounts.add_staff_member(
            actor=request.actor,
            name=d.get("name", ""),
            email=d.get("email") or None,
            phone=d.get("phone") or None,
            role=d.get("role", ""),
        )
        return Response(
            {
                "user_id": user.pk,
                "login": user.get_username(),
                "temporary_password": password,
                "must_change_password": True,
            },
            status=status.HTTP_201_CREATED,
        )


class StaffActionView(_Staff):
    @extend_schema(request=None, responses=OBJ)
    def post(self, request, user_id, action):
        if action == "reset-password":
            user, password = accounts.reset_staff_password(actor=request.actor, user_id=user_id)
            return Response({"login": user.get_username(), "temporary_password": password})
        if action in ("deactivate", "activate"):
            return Response(
                _member_out(
                    accounts.set_staff_active(actor=request.actor, user_id=user_id, active=action == "activate")
                )
            )
        raise NotFound("Unknown action.")


# --- settings (OWNER write, staff read) ----------------------------------------------------------------------------
def _settings_out(t, row) -> dict:
    keys = (
        "display_name",
        "address",
        "contact_phone",
        "brand_color",
        "receipt_footer",
        "gstin",
        "fssai_no",
        "redeem_cooldown_seconds",
        "staff_reversal_window_hours",
        "max_queued_passes",
        "allow_self_signup",
        "customer_pin_length",
    )
    return {**{k: getattr(row, k) for k in keys}, "timezone": t.timezone}


class SettingsView(_Staff):
    @extend_schema(responses=OBJ)
    def get(self, request):
        return Response(_settings_out(request.tenant, tenancy.get_settings(request.tenant.id)))

    @extend_schema(request=OBJ, responses=OBJ)
    def patch(self, request):
        data = dict(request.data)
        row = tenancy.update_settings(actor=request.actor, timezone_name=data.pop("timezone", None), **data)
        return Response(_settings_out(Tenant.objects.get(pk=request.tenant.id), row))


# --- reports ---------------------------------------------------------------------------------------------------------
class DashboardView(_Staff):
    @extend_schema(responses=OBJ)
    def get(self, request):
        return Response(reports.dashboard(actor=request.actor))


class DailyConsumptionView(_Staff):
    @extend_schema(responses=OBJ)
    def get(self, request):
        a, b = _period(request)
        r = reports.daily_consumption(actor=request.actor, start=a, end=b)
        rows = [[x["date"], x["meals"]] for x in r["days"]] + [
            [f"{c['code']} {c['name']}", c["meals"]] for c in r["customers"]
        ]
        return _csv_or_json(request, ["Date / customer", "Meals"], rows, r, "daily-consumption")


class MonthlySubscriptionsView(_Staff):
    @extend_schema(responses=OBJ)
    def get(self, request):
        y, m = _month(request)
        r = reports.monthly_subscriptions(actor=request.actor, year=y, month=m)
        return _csv_or_json(
            request,
            ["Plan", "Passes", "Revenue (paise)"],
            [[p["plan"], p["passes"], p["revenue_paise"]] for p in r["by_plan"]],
            r,
            f"subscriptions-{r['month']}",
        )


class ExpiredUnusedView(_Staff):
    @extend_schema(responses=OBJ)
    def get(self, request):
        a, b = _period(request)
        r = reports.expired_unused(actor=request.actor, start=a, end=b)
        rows = [
            [x["customer_code"], x["customer"], x["plan"], x["ended"], x["meals_total"], x["unused"]]
            for x in r["passes"]
        ]
        return _csv_or_json(
            request, ["Code", "Customer", "Plan", "Ended", "Meals", "Unused"], rows, r, "expired-unused"
        )


class CustomerStatementView(_Staff):
    @extend_schema(responses=OBJ)
    def get(self, request, customer_id):
        a, b = _period(request)
        r = reports.customer_statement(
            actor=request.actor, customer=customers.get_customer(customer_id), start=a, end=b
        )
        rows = (
            [["PASS", p["plan"], p["status"], p["starts"], p["ends"], p["remaining"]] for p in r["passes"]]
            + [["PAYMENT", p["receipt"], p["status"], p["date"], p["method"], p["amount_paise"]] for p in r["payments"]]
            + [["LEDGER", e["type"], "", e["at"], e["quantity"], e["balance"]] for e in r["ledger"]]
        )
        return _csv_or_json(
            request, ["Kind", "Item", "Status", "Date", "Detail", "Amount/balance"], rows, r, "statement"
        )


class AuditLogView(_Staff):
    @extend_schema(responses=OBJ)
    def get(self, request):
        q = request.query_params
        events = reports.audit_log(
            actor=request.actor,
            actor_query=q.get("actor", ""),
            action=q.get("action", ""),
            start=_date(q.get("start"), None),
            end=_date(q.get("end"), None),
        )
        return Response(
            {
                "results": [
                    {
                        "at": e.created_at.isoformat(),
                        "actor": e.actor.get_username() if e.actor else None,
                        "action": e.action,
                        "object_type": e.object_type,
                        "object": str(e.object_public_id) if e.object_public_id else None,
                    }
                    for e in events
                ]
            }
        )


# --- sales preview + receipts -----------------------------------------------------------------------------------------
class SalePreviewView(_Staff):
    @extend_schema(
        request=inline_serializer(
            "SalePreview", {"plan": serializers.UUIDField(), "customer": serializers.UUIDField(required=False)}
        ),
        responses=OBJ,
    )
    def post(self, request):
        plan = plans.get_plan(request.data.get("plan"))
        cust = customers.get_customer(request.data["customer"]) if request.data.get("customer") else None
        pv = passes.preview_purchase(
            customer_id=cust.id if cust else None,
            plan=plan,
            tenant=request.tenant,
            settings_row=tenancy.get_settings(request.tenant.id),
        )
        gap = pv["gap"]
        return Response(
            {
                "status": pv["status"],
                "starts_at": pv["starts_at"].isoformat(),
                "ends_at": pv["ends_at"].isoformat(),
                "queue_full": pv["queue_full"],
                "no_proration": pv["no_proration"],
                "gap": {"from": gap["from"].isoformat(), "to": gap["to"].isoformat()} if gap else None,
                "amount_paise": plan.price_paise,
            }
        )


class PaymentDetailView(_Staff):
    @extend_schema(responses=OBJ)
    def get(self, request, payment_id):
        p = billing.get_payment(payment_id)
        return Response(
            {
                **s.payment_out(p),
                "receipt_number": p.receipt_number,
                "void_reason": p.void_reason,
                "customer": s.customer_out(p.customer),
            }
        )


class ReceiptPdfView(TenantAPIView):
    allowed_roles = ALL_ROLES

    @extend_schema(responses={(200, "application/pdf"): bytes})
    def get(self, request, payment_id):
        p = billing.get_payment(payment_id)
        if request.actor.role == Role.CUSTOMER and p.customer.user_id != request.user.id:
            raise NotFound("Payment not found.")
        resp = HttpResponse(receipts.render_receipt_pdf(p), content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{p.receipt_number or "receipt"}.pdf"'
        return resp


# --- platform --------------------------------------------------------------------------------------------------------
class PlatformOnboardView(PlatformAPIView):
    @extend_schema(
        request=inline_serializer(
            "Onboard",
            {
                "name": serializers.CharField(),
                "slug": serializers.SlugField(),
                "timezone": serializers.CharField(required=False),
                "owner_name": serializers.CharField(),
                "owner_email": serializers.EmailField(required=False),
                "owner_phone": serializers.CharField(required=False),
            },
        ),
        responses=OBJ,
    )
    def post(self, request):
        d = request.data
        tenant, owner, password = tenancy.onboard_tenant(
            actor_user=request.user,
            name=d.get("name", ""),
            slug=d.get("slug", ""),
            timezone_name=d.get("timezone", "Asia/Kolkata"),
            owner_name=d.get("owner_name", ""),
            owner_email=d.get("owner_email") or None,
            owner_phone=d.get("owner_phone") or None,
            is_test=bool(d.get("is_test", False)),
        )
        return Response(
            {"tenant": s.tenant_out(tenant), "owner_login": owner.get_username(), "temporary_password": password},
            status=status.HTTP_201_CREATED,
        )


class PlatformDashboardView(PlatformAPIView):
    @extend_schema(responses=OBJ)
    def get(self, request):
        with platform_context():
            return Response({"results": reports.platform_dashboard()})
