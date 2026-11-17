# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

from datetime import date
from datetime import timedelta

import pytest
from django.utils import timezone

from mealtally.billing import services as billing
from mealtally.common.errors import NotAllowed
from mealtally.common.errors import ValidationFailed
from mealtally.ledger import services as ledger
from mealtally.passes import services as passes
from mealtally.reports import services as reports
from mealtally.tenancy.context import platform_context
from mealtally.testing import World
from mealtally.testing import buy
from mealtally.testing import make_customer

pytestmark = pytest.mark.django_db


def redeem(w, key, customer=None, **kw):
    return ledger.redeem(
        actor=w.staff,
        customer=customer or w.customer,
        idempotency_key=key,
        source="STAFF_SEARCH",
        confirm_additional=True,
        **kw,
    )


def today(w):
    from mealtally.common.utils import local_date

    return local_date(timezone.now(), w.tenant.timezone)


def test_dashboard_numbers():
    w = World()
    other, _ = make_customer(w.tenant, w.owner, name="Second")
    buy(w.tenant, w.owner, other, w.plan)
    with w.ctx():
        redeem(w, "d1")
        r2 = redeem(w, "d2")
        ledger.reverse_redemption(actor=w.owner, entry_public_id=r2.entry.public_id, reason="x")
        d = reports.dashboard(actor=w.owner)
        assert d["meals_today"] == 1 and d["active_passes"] == 2 and d["expiring_3_days"] == 0
        assert (
            d["passes_sold_month"] == 2
            and d["revenue_month_minor"] == 300000
            and d["platform_fee_month_minor"] == 36000
        )
        with pytest.raises(NotAllowed):
            reports.dashboard(actor=w.staff)


def test_daily_consumption_nets_reversals_and_lists_customers():
    w = World()
    with w.ctx():
        redeem(w, "c1")
        r = redeem(w, "c2")
        ledger.reverse_redemption(actor=w.owner, entry_public_id=r.entry.public_id, reason="x")
        out = reports.daily_consumption(actor=w.manager, start=today(w) - timedelta(days=1), end=today(w))
        assert out["total"] == 1 and out["days"][-1]["meals"] == 1 and out["customers"][0]["meals"] == 1
        with pytest.raises(ValidationFailed):
            reports.daily_consumption(actor=w.manager, start=today(w), end=today(w) - timedelta(days=1))


def test_monthly_subscriptions_by_plan_and_voids():
    w = World()
    second = buy(w.tenant, w.owner, w.customer, w.plan)
    with w.ctx():
        billing.void_payment(actor=w.owner, payment_public_id=second.payment.public_id, reason="dup")
        t = today(w)
        r = reports.monthly_subscriptions(actor=w.owner, year=t.year, month=t.month)
        assert (
            r["passes_sold"] == 1
            and r["revenue_minor"] == 150000
            and r["voids"] == 1
            and r["void_amount_minor"] == 150000
        )
        assert r["by_plan"] == [{"plan": "Monthly Meal Pass", "passes": 1, "revenue_minor": 150000}]
        with pytest.raises(ValidationFailed):
            reports.monthly_subscriptions(actor=w.owner, year=2026, month=13)


def test_expired_unused_report_and_statement_and_audit():
    w = World()
    with w.ctx():
        redeem(w, "e1")
        passes.expire(w.pass_.__class__.objects.get(pk=w.pass_.pk), now=timezone.now())
        t = today(w)
        r = reports.expired_unused(actor=w.owner, start=t - timedelta(days=1), end=t + timedelta(days=40))
        assert (
            r["total_forfeited"] == 29
            and r["passes"][0]["unused"] == 29
            and r["passes"][0]["customer"] == w.customer.full_name
        )
        st = reports.customer_statement(
            actor=w.owner, customer=w.customer, start=t - timedelta(days=1), end=t + timedelta(days=1)
        )
        assert [p["receipt"] for p in st["payments"]] == ["R-000001"] and len(st["passes"]) == 1
        assert [e["type"] for e in st["ledger"]] == ["ISSUE", "REDEEM", "EXPIRE"]
        events = reports.audit_log(actor=w.owner, action="payment")
        assert [e.action for e in events] == ["payment.record"]
        assert list(reports.audit_log(actor=w.owner, actor_query="zzz-nobody")) == []
        assert len(list(reports.audit_log(actor=w.owner, start=t, end=t))) >= 1
        with pytest.raises(NotAllowed):
            reports.audit_log(actor=w.staff)


def test_platform_dashboard_lists_every_tenant():
    a = World(slug="pd-a")
    World(slug="pd-b", buy_pass=False)
    with a.ctx():
        redeem(a, "p1")
    with platform_context():
        rows = {r["slug"]: r for r in reports.platform_dashboard()}
    assert (
        rows["pd-a"]["active_passes"] == 1
        and rows["pd-a"]["meals_month"] == 1
        and rows["pd-a"]["fees_month_minor"] == 18000
    )
    assert rows["pd-b"]["customers"] == 1 and rows["pd-b"]["active_passes"] == 0


def test_csv_guards_against_formula_injection():
    out = reports.to_csv(["a", "b"], [["=SUM(A1)", "ok"], ["@cmd", 3], ["+919800000000", "x"]])
    lines = out.splitlines()
    assert lines[1].startswith("'=SUM(A1)") and lines[2].startswith("'@cmd") and lines[3].startswith("+919800000000")
    assert date(2026, 1, 1)
