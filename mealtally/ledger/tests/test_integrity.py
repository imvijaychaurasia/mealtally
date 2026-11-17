# SPDX-License-Identifier: AGPL-3.0-only
"""Append-only triggers, reconciliation, and the mandatory concurrency / idempotency tests."""

from __future__ import annotations

import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.db import connection
from django.db import transaction

from mealtally.audit.models import AuditEvent
from mealtally.billing.models import PlatformFeeEntry
from mealtally.common.errors import DomainError
from mealtally.ledger import services as ledger
from mealtally.ledger.models import MealLedgerEntry
from mealtally.passes.models import Pass
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.context import tenant_context
from mealtally.testing import World


# --- append-only (DB level) -----------------------------------------------------------------------
@pytest.mark.django_db
@pytest.mark.parametrize(
    ("table", "update_sql"),
    [
        ("ledger_mealledgerentry", "UPDATE ledger_mealledgerentry SET quantity = quantity"),
        ("audit_auditevent", "UPDATE audit_auditevent SET action = 'x'"),
        ("billing_platformfeeentry", "UPDATE billing_platformfeeentry SET amount_minor = 1"),
    ],
)
def test_update_and_delete_are_rejected_by_the_database(table, update_sql):
    w = World()
    with w.ctx():
        assert PlatformFeeEntry.objects.exists() and AuditEvent.objects.exists() and MealLedgerEntry.objects.exists()
        with pytest.raises(DatabaseError, match="append-only"), transaction.atomic(), connection.cursor() as cur:
            cur.execute(update_sql)
        with pytest.raises(DatabaseError, match="append-only"), transaction.atomic(), connection.cursor() as cur:
            cur.execute(f"DELETE FROM {table}")  # noqa: S608


@pytest.mark.django_db
def test_orm_update_delete_on_ledger_are_rejected_too():
    w = World()
    with w.ctx():
        entry = MealLedgerEntry.objects.first()
        with pytest.raises(DatabaseError), transaction.atomic():
            MealLedgerEntry.objects.filter(pk=entry.pk).update(quantity=999)
        with pytest.raises(DatabaseError), transaction.atomic():
            entry.delete()
        with pytest.raises(DatabaseError), transaction.atomic():
            entry.reason = "tamper"
            entry.save()


@pytest.mark.django_db
def test_negative_balance_is_impossible_at_the_database_level():
    w = World()
    with w.ctx():
        with pytest.raises(DatabaseError), transaction.atomic():
            Pass.objects.filter(pk=w.pass_.pk).update(meals_remaining=-1)  # PositiveInteger/CHECK


@pytest.mark.django_db
def test_only_one_active_pass_per_customer_at_the_database_level():
    from django.utils import timezone

    w = World()
    with w.ctx(), pytest.raises(DatabaseError), transaction.atomic():
        p = Pass.objects.get(pk=w.pass_.pk)
        Pass.objects.create(
            tenant_id=w.tenant.id,
            customer=w.customer,
            payment=_fresh_payment(w),
            plan=w.plan,
            plan_name="x",
            price_minor=1,
            meals_total=1,
            validity_mode="ROLLING_DAYS",
            validity_days=1,
            status="ACTIVE",
            starts_at=timezone.now(),
            ends_at=p.ends_at,
            meals_remaining=0,
        )


def _fresh_payment(w):
    from mealtally.billing.models import Payment

    return Payment.objects.create(
        tenant_id=w.tenant.id, customer=w.customer, plan=w.plan, amount_minor=1, method="CASH", recorded_by=w.owner.user
    )


# --- reconciliation -------------------------------------------------------------------------------
@pytest.mark.django_db
def test_reconciliation_detects_cache_drift():
    w = World()
    with w.ctx():
        assert ledger.find_mismatches() == []
        call_command("reconcile_ledger")
        Pass.objects.filter(pk=w.pass_.pk).update(meals_remaining=7)  # corrupt the cache
        problems = ledger.find_mismatches()
        assert len(problems) == 1 and problems[0]["ledger_sum"] == 30 and problems[0]["meals_remaining"] == 7
        with pytest.raises(CommandError):
            call_command("reconcile_ledger")


@pytest.mark.django_db
def test_reconciliation_flags_ended_pass_with_credits():
    w = World()
    with w.ctx():
        MealLedgerEntry.objects.count()  # warm
        Pass.objects.filter(pk=w.pass_.pk).update(status="EXPIRED")
        assert [p["status"] for p in ledger.find_mismatches()] == ["EXPIRED"]


@pytest.mark.django_db
def test_nightly_reconcile_task_counts_mismatches():
    from mealtally.ledger.tasks import reconcile_ledgers

    w = World()
    assert reconcile_ledgers() == {"mismatches": 0}
    with w.ctx():
        Pass.objects.filter(pk=w.pass_.pk).update(meals_remaining=1)
    assert reconcile_ledgers() == {"mismatches": 1}


# --- mandatory concurrency & idempotency tests ------------------------------------------------------
def _run_parallel(w, n, make_kwargs):
    barrier = threading.Barrier(n)
    outcomes = []

    def worker(i):
        barrier.wait()
        try:
            with tenant_context(w.tenant.id):
                res = ledger.redeem(actor=w.staff, customer=w.customer, source="STAFF_SEARCH", **make_kwargs(i))
            return ("ok", res)
        except DomainError as exc:
            return ("err", exc.code)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=n) as pool:
        outcomes = list(pool.map(worker, range(n)))
    return outcomes


@pytest.mark.django_db(transaction=True)
def test_25_parallel_redeems_on_a_3_credit_pass_succeed_exactly_3_times():
    w = World(plan_kwargs={"meals_per_cycle": 3})
    outcomes = _run_parallel(w, 25, lambda i: {"idempotency_key": str(uuid.uuid4()), "confirm_additional": True})
    ok = [o for o in outcomes if o[0] == "ok"]
    errors = [o[1] for o in outcomes if o[0] == "err"]
    sys.stdout.write(f"\nCONCURRENCY: successes={len(ok)} rejected={len(errors)} codes={sorted(set(errors))}" + "\n")
    assert len(ok) == 3
    assert len(errors) == 22 and set(errors) == {"NO_CREDITS"}
    assert len({res.entry.public_id for _, res in ok}) == 3
    with tenant_context(w.tenant.id):
        pass_ = Pass.objects.get(pk=w.pass_.pk)
        assert pass_.meals_remaining == 0
        entries = list(MealLedgerEntry.objects.filter(pass_ref=pass_).order_by("id"))
        assert sum(e.quantity for e in entries) == 0
        assert all(e.balance_after >= 0 for e in entries)
        assert [e.entry_type for e in entries].count("REDEEM") == 3
        assert ledger.find_mismatches() == []


@pytest.mark.django_db(transaction=True)
def test_10_parallel_calls_with_the_same_idempotency_key_make_exactly_one_entry():
    w = World()
    shared = str(uuid.uuid4())
    outcomes = _run_parallel(w, 10, lambda i: {"idempotency_key": shared, "confirm_additional": False})
    assert all(o[0] == "ok" for o in outcomes), outcomes
    ids = {res.entry.public_id for _, res in outcomes}
    replayed = [res.replayed for _, res in outcomes]
    sys.stdout.write(
        f"\nIDEMPOTENCY: responses=10 distinct_entry_ids={len(ids)} "
        f"replayed={sum(replayed)} fresh={replayed.count(False)}\n"
    )
    assert len(ids) == 1
    assert replayed.count(False) == 1 and replayed.count(True) == 9
    with tenant_context(w.tenant.id):
        assert MealLedgerEntry.objects.filter(idempotency_key=shared).count() == 1
        assert MealLedgerEntry.objects.filter(entry_type="REDEEM").count() == 1
        assert Pass.objects.get(pk=w.pass_.pk).meals_remaining == 29


@pytest.mark.django_db(transaction=True)
def test_parallel_expiry_job_runs_do_not_double_expire():
    from datetime import timedelta

    from django.utils import timezone

    from mealtally.passes import services as passes
    from mealtally.testing import buy

    w = World(buy_pass=False)
    past = timezone.now() - timedelta(days=40)
    buy(w.tenant, w.owner, w.customer, w.plan, now=past)
    barrier = threading.Barrier(6)

    def job(_):
        barrier.wait()
        try:
            with tenant_context(w.tenant.id):
                return passes.run_due_transitions()
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(job, range(6)))
    assert sum(r["expired"] for r in results) == 1
    with tenant_context(w.tenant.id):
        assert MealLedgerEntry.objects.filter(entry_type="EXPIRE").count() == 1
        assert Pass.objects.get().status == "EXPIRED" and Pass.objects.get().meals_remaining == 0
    with platform_context():
        assert ledger.find_mismatches() == []


@pytest.mark.django_db(transaction=True)
def test_truncate_is_rejected_on_the_three_append_only_tables(admin_connection):
    from mealtally.tenancy.rls import APPEND_ONLY_TABLES

    w = World()  # noqa: F841
    for table in APPEND_ONLY_TABLES:
        admin_connection.execute(f'ALTER TABLE "{table}" ENABLE TRIGGER "{table}_no_truncate"')
    try:
        for table in APPEND_ONLY_TABLES:
            with pytest.raises(Exception, match="TRUNCATE is not allowed"):
                admin_connection.execute(f'TRUNCATE "{table}" CASCADE')
    finally:
        for table in APPEND_ONLY_TABLES:
            admin_connection.execute(f'ALTER TABLE "{table}" DISABLE TRIGGER "{table}_no_truncate"')
