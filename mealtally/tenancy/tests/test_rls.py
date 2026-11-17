"""Tenant isolation: ORM, raw SQL, DRF endpoints and admin -- enforced by Postgres RLS."""

from __future__ import annotations

import pytest
from django.db import DatabaseError
from django.db import connection
from django.db import transaction
from rest_framework.test import APIClient

from mealtally.accounts.models import Membership
from mealtally.accounts.models import Role
from mealtally.customers.models import Customer
from mealtally.ledger.models import MealLedgerEntry
from mealtally.passes.models import Pass
from mealtally.plans.models import Plan
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.context import tenant_context
from mealtally.tenancy.management.commands.check_rls import rls_problems
from mealtally.tenancy.management.commands.check_rls import tenant_scoped_tables
from mealtally.tenancy.models import Tenant
from mealtally.testing import World

pytestmark = pytest.mark.django_db

TENANT_TABLES = [
    "plans_plan",
    "plans_mealslot",  # D03.9
    "plans_planmealslot",  # D03.9
    "customers_customer",
    "passes_pass",
    "ledger_mealledgerentry",
    "billing_payment",
    "billing_feepolicy",
    "billing_platformfeeentry",
    "accounts_membership",
    "tenancy_tenant",
    "tenancy_tenantsettings",
    "audit_auditevent",
]


def count(sql: str, params=None) -> int:
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.fetchone()[0]


def test_app_role_is_not_superuser_and_cannot_bypass_rls():
    with connection.cursor() as cur:
        cur.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        assert cur.fetchone() == (False, False)


def test_every_tenant_scoped_table_has_forced_rls_policy_and_append_only_triggers():
    assert set(tenant_scoped_tables()) == set(TENANT_TABLES)
    assert rls_problems() == []


@pytest.fixture
def two_tenants():
    a, b = World(slug="alpha"), World(slug="bravo")
    return a, b


def test_missing_context_returns_zero_rows_never_all(two_tenants):
    # no tenant_context / platform_context active
    assert Plan.objects.count() == 0 and Customer.objects.count() == 0 and Pass.objects.count() == 0
    for table in TENANT_TABLES:
        assert count(f'SELECT count(*) FROM "{table}"') == 0, table  # raw SQL: RLS, not the ORM manager
    assert not Tenant.objects.exists()


def test_tenant_a_cannot_read_tenant_b_via_orm_or_raw_sql(two_tenants):
    a, b = two_tenants
    with a.ctx():
        assert set(Customer.objects.values_list("id", flat=True)) == {a.customer.id}
        assert Customer.objects.filter(pk=b.customer.pk).first() is None
        assert Customer._base_manager.filter(pk=b.customer.pk).first() is None  # bypasses the ORM manager
        assert count("SELECT count(*) FROM customers_customer WHERE id = %s", [b.customer.pk]) == 0
        assert count("SELECT count(*) FROM customers_customer") == 1
        assert count("SELECT count(*) FROM ledger_mealledgerentry WHERE tenant_id = %s", [b.tenant.id]) == 0
        assert list(Tenant.objects.values_list("slug", flat=True)) == ["alpha"]
        assert Pass.objects.count() == 1 and MealLedgerEntry.objects.count() == 1


def test_tenant_a_cannot_write_tenant_b_rows(two_tenants):
    a, b = two_tenants
    with a.ctx():
        # UPDATE / DELETE of another tenant's row silently match nothing
        with connection.cursor() as cur:
            cur.execute("UPDATE customers_customer SET full_name = 'hacked' WHERE id = %s", [b.customer.pk])
            assert cur.rowcount == 0
            cur.execute("DELETE FROM plans_plan WHERE id = %s", [b.plan.pk])
            assert cur.rowcount == 0
        # INSERT claiming another tenant is rejected by WITH CHECK
        with pytest.raises(DatabaseError), transaction.atomic():
            Plan.objects.create(tenant_id=b.tenant.id, name="evil", price_minor=1)
    with b.ctx():
        assert Customer.objects.get(pk=b.customer.pk).full_name != "hacked"
        assert Plan.objects.filter(pk=b.plan.pk).exists()


def test_insert_without_context_is_rejected(two_tenants):
    a, _ = two_tenants
    with pytest.raises(DatabaseError), transaction.atomic():
        Plan.objects.create(tenant_id=a.tenant.id, name="no-context", price_minor=1)


def test_platform_context_sees_everything(two_tenants):
    with platform_context():
        assert Tenant.objects.count() == 2
        assert Customer.objects.count() == 2
        assert count("SELECT count(*) FROM customers_customer") == 2


def test_nested_contexts_restore_the_outer_one(two_tenants):
    a, b = two_tenants
    with a.ctx():
        with b.ctx():
            assert [c.id for c in Customer.objects.all()] == [b.customer.id]
            assert count("SELECT count(*) FROM customers_customer") == 1
        assert [c.id for c in Customer.objects.all()] == [a.customer.id]
        assert count("SELECT current_setting('app.tenant_id', true)::bigint") == a.tenant.id


@pytest.mark.django_db(transaction=True)
def test_context_does_not_leak_to_the_next_transaction_on_the_same_connection():
    w = World(slug="leaky")
    with tenant_context(w.tenant.id):
        assert Customer.objects.count() == 1
    # same connection, new (auto-commit) statement: nothing may remain set
    with connection.cursor() as cur:
        cur.execute("SELECT current_setting('app.tenant_id', true), current_setting('app.platform', true)")
        tenant_setting, platform_setting = cur.fetchone()
    assert tenant_setting in (None, "")
    assert platform_setting in (None, "", "off")
    assert Customer.objects.count() == 0 and count("SELECT count(*) FROM customers_customer") == 0


# --- DRF endpoints ------------------------------------------------------------------------------
def _client(user):
    client = APIClient()
    client.force_login(user, backend="mealtally.accounts.backends.IdentifierPasswordBackend")
    return client


def test_api_user_of_a_cannot_reach_tenant_b_and_gets_404(two_tenants):
    a, b = two_tenants
    client = _client(a.owner.user)
    ok = client.get(f"/api/v1/t/{a.tenant.slug}/customers")
    assert ok.status_code == 200 and len(ok.json()["results"]) == 1
    for path in ("customers", f"customers/{b.customer.public_id}", "plans", "reports/daily"):
        resp = client.get(f"/api/v1/t/{b.tenant.slug}/{path}")
        assert resp.status_code == 404, path
        assert resp.json()["error"]["code"] == "NOT_FOUND"
    # a customer id from B used inside A's URL does not resolve either
    resp = client.get(f"/api/v1/t/{a.tenant.slug}/customers/{b.customer.public_id}")
    assert resp.status_code == 404


def test_api_cannot_redeem_or_pay_across_tenants(two_tenants):
    a, b = two_tenants
    client = _client(a.owner.user)
    resp = client.post(
        f"/api/v1/t/{a.tenant.slug}/redeem",
        {"customer": str(b.customer.public_id), "idempotency_key": "k-cross-1"},
        format="json",
    )
    assert resp.status_code == 404
    resp = client.post(
        f"/api/v1/t/{a.tenant.slug}/payments",
        {
            "customer": str(b.customer.public_id),
            "plan": str(b.plan.public_id),
            "amount_minor": 150000,
            "method": "CASH",
        },
        format="json",
    )
    assert resp.status_code == 404
    with b.ctx():
        assert MealLedgerEntry.objects.count() == 1  # only the ISSUE entry


def test_unknown_tenant_slug_is_also_404(two_tenants):
    a, _ = two_tenants
    assert _client(a.owner.user).get("/api/v1/t/nope/customers").status_code == 404


# --- admin ----------------------------------------------------------------------------------------
def test_django_admin_is_platform_admin_only(two_tenants):
    from django.contrib.auth import get_user_model

    a, b = two_tenants
    owner_client = _client(a.owner.user)
    resp = owner_client.get("/platform/admin/customers/customer/")
    assert resp.status_code == 302 and "login" in resp["Location"]  # tenant owner is not a platform admin

    with platform_context():
        admin_user = get_user_model().objects.create_superuser(email="root@example.test", password="Sup3r-Secret-Pw!")
    resp = _client(admin_user).get("/platform/admin/customers/customer/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert a.customer.customer_code in body and "C0001" in body
    # both tenants' customers are visible to the platform admin
    assert body.count("C0001") >= 2


def test_membership_table_is_rls_protected(two_tenants):
    a, b = two_tenants
    with a.ctx():
        assert Membership.objects.filter(tenant_id=b.tenant.id).count() == 0
        assert {m.role for m in Membership.objects.all()} >= {Role.OWNER, Role.STAFF, Role.MANAGER, Role.CUSTOMER}
