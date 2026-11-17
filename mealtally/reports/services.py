"""Read-only reporting (D02 section 5.3). Every function checks the role and runs in the caller's tenant context."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date
from datetime import datetime
from datetime import timedelta

from django.db.models import Count
from django.db.models import Q
from django.db.models import Sum
from django.utils import timezone

from mealtally.accounts.policy import Action
from mealtally.accounts.policy import Actor
from mealtally.accounts.policy import require
from mealtally.audit.models import AuditEvent
from mealtally.billing import fees
from mealtally.billing.models import Payment
from mealtally.common.errors import ValidationFailed
from mealtally.common.utils import local_date
from mealtally.common.utils import start_of_local_day
from mealtally.ledger.models import MealLedgerEntry
from mealtally.passes.models import Pass
from mealtally.tenancy.models import Tenant

E = MealLedgerEntry.EntryType


def _tenant(actor: Actor) -> Tenant:
    return Tenant.objects.get(pk=actor.tenant_id)


def period_bounds(tenant: Tenant, start: date, end: date) -> tuple[datetime, datetime]:
    if end < start:
        raise ValidationFailed("The end date is before the start date.", details={"field": "end"})
    return start_of_local_day(start, tenant.timezone), start_of_local_day(end + timedelta(days=1), tenant.timezone)


def month_range(year: int, month: int) -> tuple[date, date]:
    if not 1 <= month <= 12:  # noqa: PLR2004
        raise ValidationFailed("month must be 1-12.", details={"field": "month"})
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return first, nxt - timedelta(days=1)


def dashboard(*, actor: Actor) -> dict:
    require(actor, Action.REPORTS_FULL)
    tenant = _tenant(actor)
    now = timezone.now()
    today = local_date(now, tenant.timezone)
    first, last = month_range(today.year, today.month)
    m_start, m_end = period_bounds(tenant, first, last)
    base = MealLedgerEntry.objects.filter(meal_date=today)
    meals_today = base.filter(entry_type=E.REDEEM).count() - base.filter(entry_type=E.REVERSAL).count()
    sold = Payment.objects.filter(received_at__gte=m_start, received_at__lt=m_end, status=Payment.Status.RECORDED)
    fee_total = fees.fee_month(tenant, today.year, today.month)["total_paise"]
    return {
        "meals_today": meals_today,
        "active_passes": Pass.objects.filter(status=Pass.Status.ACTIVE).count(),
        "expiring_3_days": Pass.objects.filter(status=Pass.Status.ACTIVE, ends_at__lte=now + timedelta(days=3)).count(),
        "passes_sold_month": sold.count(),
        "revenue_month_paise": sold.aggregate(t=Sum("amount_paise"))["t"] or 0,
        "platform_fee_month_paise": fee_total,
    }


def daily_consumption(*, actor: Actor, start: date, end: date) -> dict:
    require(actor, Action.REPORTS_FULL)
    if end < start:
        raise ValidationFailed("The end date is before the start date.", details={"field": "end"})
    rows = (
        MealLedgerEntry.objects.filter(meal_date__gte=start, meal_date__lte=end, entry_type__in=[E.REDEEM, E.REVERSAL])
        .values("meal_date", "customer__customer_code", "customer__full_name", "entry_type")
        .annotate(n=Count("id"))
    )
    per_day: dict = defaultdict(int)
    per_customer: dict = defaultdict(int)
    for r in rows:
        sign = 1 if r["entry_type"] == E.REDEEM else -1
        per_day[r["meal_date"]] += sign * r["n"]
        per_customer[(r["customer__customer_code"], r["customer__full_name"])] += sign * r["n"]
    return {
        "days": [{"date": d.isoformat(), "meals": n} for d, n in sorted(per_day.items())],
        "customers": [
            {"code": c, "name": n, "meals": v}
            for (c, n), v in sorted(per_customer.items(), key=lambda kv: (-kv[1], kv[0]))
            if v
        ],
        "total": sum(per_day.values()),
    }


def monthly_subscriptions(*, actor: Actor, year: int, month: int) -> dict:
    require(actor, Action.REPORTS_FULL)
    tenant = _tenant(actor)
    first, last = month_range(year, month)
    start, end = period_bounds(tenant, first, last)
    in_month = Payment.objects.filter(received_at__gte=start, received_at__lt=end)
    sold = in_month.filter(status=Payment.Status.RECORDED)
    voided = Payment.objects.filter(voided_at__gte=start, voided_at__lt=end, status=Payment.Status.VOIDED)
    by_plan = sold.values("plan__name").annotate(n=Count("id"), total=Sum("amount_paise")).order_by("plan__name")
    return {
        "month": f"{year:04d}-{month:02d}",
        "passes_sold": sold.count(),
        "revenue_paise": sold.aggregate(t=Sum("amount_paise"))["t"] or 0,
        "by_plan": [{"plan": r["plan__name"], "passes": r["n"], "revenue_paise": r["total"]} for r in by_plan],
        "voids": voided.count(),
        "void_amount_paise": voided.aggregate(t=Sum("amount_paise"))["t"] or 0,
    }


def expired_unused(*, actor: Actor, start: date, end: date) -> dict:
    require(actor, Action.REPORTS_FULL)
    tenant = _tenant(actor)
    lo, hi = period_bounds(tenant, start, end)
    expire = (
        MealLedgerEntry.objects.filter(
            entry_type=E.EXPIRE,
            pass_ref__status=Pass.Status.EXPIRED,
            pass_ref__ends_at__gte=lo,
            pass_ref__ends_at__lt=hi,
        )
        .select_related("pass_ref", "customer")
        .order_by("pass_ref__ends_at")
    )
    rows = [
        {
            "customer_code": e.customer.customer_code,
            "customer": e.customer.full_name,
            "plan": e.pass_ref.plan_name,
            "ended": e.pass_ref.ends_at.astimezone(tenant.zone).date().isoformat(),
            "meals_total": e.pass_ref.meals_total,
            "unused": -e.quantity,
        }
        for e in expire
    ]
    return {"passes": rows, "total_forfeited": sum(r["unused"] for r in rows)}


def customer_statement(*, actor: Actor, customer, start: date, end: date) -> dict:
    require(actor, Action.REPORTS_FULL)
    tenant = _tenant(actor)
    lo, hi = period_bounds(tenant, start, end)
    zone = tenant.zone
    return {
        "customer": {"code": customer.customer_code, "name": customer.full_name, "phone": customer.phone_e164},
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "passes": [
            {
                "plan": p.plan_name,
                "status": p.status,
                "starts": p.starts_at.astimezone(zone).date().isoformat(),
                "ends": p.ends_at.astimezone(zone).date().isoformat(),
                "meals_total": p.meals_total,
                "remaining": p.meals_remaining,
            }
            for p in Pass.objects.filter(customer=customer)
            .filter(Q(starts_at__lt=hi) & Q(ends_at__gte=lo))
            .order_by("starts_at")
        ],
        "payments": [
            {
                "receipt": p.receipt_number,
                "date": p.received_at.astimezone(zone).date().isoformat(),
                "amount_paise": p.amount_paise,
                "method": p.method,
                "status": p.status,
            }
            for p in Payment.objects.filter(customer=customer, received_at__gte=lo, received_at__lt=hi).order_by(
                "received_at"
            )
        ],
        "ledger": [
            {
                "at": e.occurred_at.astimezone(zone).isoformat(timespec="minutes"),
                "type": e.entry_type,
                "quantity": e.quantity,
                "balance": e.balance_after,
            }
            for e in MealLedgerEntry.objects.filter(
                customer=customer, occurred_at__gte=lo, occurred_at__lt=hi
            ).order_by("id")
        ],
    }


def audit_log(
    *,
    actor: Actor,
    actor_query: str = "",
    action: str = "",
    start: date | None = None,
    end: date | None = None,
    limit: int = 200,
):
    require(actor, Action.VIEW_AUDIT)
    qs = AuditEvent.objects.select_related("actor").order_by("-id")
    if actor_query:
        qs = qs.filter(
            Q(actor__email__icontains=actor_query)
            | Q(actor__phone_e164__icontains=actor_query)
            | Q(actor__name__icontains=actor_query)
        )
    if action:
        qs = qs.filter(action__icontains=action)
    if start or end:
        tenant = _tenant(actor)
        lo = start_of_local_day(start, tenant.timezone) if start else None
        hi = start_of_local_day(end + timedelta(days=1), tenant.timezone) if end else None
        if lo:
            qs = qs.filter(created_at__gte=lo)
        if hi:
            qs = qs.filter(created_at__lt=hi)
    return qs[:limit]


def platform_dashboard(*, include_test: bool = False) -> list[dict]:
    """Per tenant: customers, active passes, meals this month, fees this month (shared ``fee_month``).

    Call inside platform_context(). Test tenants (e2e/perf) are hidden unless ``include_test``.
    """
    from mealtally.customers.models import Customer  # noqa: PLC0415
    from mealtally.tenancy.models import TenantSettings  # noqa: PLC0415

    now = timezone.now()
    rows = []
    tenants = Tenant.objects.order_by("slug")
    if not include_test:
        tenants = tenants.filter(is_test=False)
    names = dict(TenantSettings.objects.values_list("tenant_id", "display_name"))
    for t in tenants:
        today = local_date(now, t.timezone)
        first, last = month_range(today.year, today.month)
        m = MealLedgerEntry.objects.filter(tenant_id=t.id, meal_date__gte=first, meal_date__lte=last)
        meals = m.filter(entry_type=E.REDEEM).count() - m.filter(entry_type=E.REVERSAL).count()
        rows.append(
            {
                "slug": t.slug,
                "name": names.get(t.id) or t.name,
                "status": t.status,
                "is_test": t.is_test,
                "customers": Customer.objects.filter(tenant_id=t.id).count(),
                "active_passes": Pass.objects.filter(tenant_id=t.id, status=Pass.Status.ACTIVE).count(),
                "meals_month": meals,
                "fees_month_paise": fees.fee_month(t, today.year, today.month)["total_paise"],
            }
        )
    return rows


def platform_totals(rows: list[dict]) -> dict:
    return {
        "active_tenants": sum(1 for r in rows if r["status"] == "ACTIVE"),
        "customers": sum(r["customers"] for r in rows),
        "meals_month": sum(r["meals_month"] for r in rows),
        "fees_month_paise": sum(r["fees_month_paise"] for r in rows),
    }


def to_csv(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow(
            [
                ("'" + str(c))
                if isinstance(c, str) and c[:1] in "=+-@" and not c[:1].isdigit() and c[:2] != "+9"
                else c
                for c in row
            ]
        )
    return buf.getvalue()
