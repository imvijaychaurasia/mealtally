from __future__ import annotations

import statistics
import time

import pytest
from django.contrib.auth.hashers import make_password

from mealtally.accounts.models import Role
from mealtally.accounts.models import User
from mealtally.common.errors import NotAllowed
from mealtally.common.errors import ValidationFailed
from mealtally.customers import services as customers
from mealtally.customers.models import Customer
from mealtally.tenancy.context import platform_context
from mealtally.testing import World
from mealtally.testing import buy
from mealtally.testing import make_customer

pytestmark = pytest.mark.django_db


def test_create_with_chosen_pin_sets_must_change_and_validates():
    w = World(buy_pass=False)
    with w.ctx():
        c, pin = customers.create_customer(actor=w.staff, full_name="Chosen", phone="9811111111", pin="482916")
        assert pin == "482916" and c.must_change_pin is True
        for bad in ("123", "abcdef", "111111", "1234567"):
            with pytest.raises(ValidationFailed):
                customers.create_customer(actor=w.staff, full_name="Bad", phone="9822222222", pin=bad)
        c2, generated = customers.create_customer(actor=w.staff, full_name="Gen", phone="9833333333")
        assert len(generated) == 6 and c2.must_change_pin is True


def test_reset_pin_forces_change_and_change_pin_validates():
    w = World(buy_pass=False)
    with w.ctx():
        c = customers.get_customer(w.customer.public_id)
        new = customers.reset_pin(actor=w.staff, customer=c, pin="739104")
        assert new == "739104" and c.must_change_pin
        with pytest.raises(ValidationFailed):
            customers.change_pin(customer=c, old_pin="000000", new_pin="582013")
        with pytest.raises(ValidationFailed):
            customers.change_pin(customer=c, old_pin="739104", new_pin="739104")
        with pytest.raises(ValidationFailed):
            customers.change_pin(customer=c, old_pin="739104", new_pin="12")
        customers.change_pin(customer=c, old_pin="739104", new_pin="582013")
        c.refresh_from_db()
        assert not c.must_change_pin and customers.verify_pin(
            tenant_slug=w.tenant.slug, phone=c.phone_e164, pin="582013"
        )


def test_update_block_roles_and_own_name():
    w = World(buy_pass=False)
    with w.ctx():
        c = customers.get_customer(w.customer.public_id)
        customers.update_customer(actor=w.staff, customer=c, full_name="  New Name ", notes="vip")
        assert c.full_name == "New Name" and c.notes == "vip"
        with pytest.raises(ValidationFailed):
            customers.update_customer(actor=w.staff, customer=c, full_name=" ")
        with pytest.raises(NotAllowed):
            customers.set_status(actor=w.staff, customer=c, status="BLOCKED")
        customers.set_status(actor=w.manager, customer=c, status="BLOCKED", reason="x")
        assert (
            customers.verify_pin(tenant_slug=w.tenant.slug, phone=c.phone_e164, pin=w.pin) is None
        )  # blocked: cannot log in


def test_self_signup_requires_the_tenant_flag():
    w = World(buy_pass=False)
    with w.ctx(), pytest.raises(NotAllowed):
        customers.self_signup(tenant_id=w.tenant.id, full_name="S", phone="9844444444", pin="482916")
    w2 = World(buy_pass=False, tenant_settings={"allow_self_signup": True})
    with w2.ctx():
        c = customers.self_signup(tenant_id=w2.tenant.id, full_name="Self", phone="9855555555", pin="482916")
        assert c.status == "ACTIVE" and not c.must_change_pin and not c.passes.exists()
        with pytest.raises(ValidationFailed):
            customers.self_signup(tenant_id=w2.tenant.id, full_name="Self", phone="9855555555", pin="482916")
        with pytest.raises(ValidationFailed):
            customers.self_signup(tenant_id=w2.tenant.id, full_name="", phone="9866666666", pin="482916")
        with pytest.raises(ValidationFailed):
            customers.self_signup(tenant_id=w2.tenant.id, full_name="X", phone="9866666666", pin="12")


def test_list_customers_filters():
    w = World(buy_pass=False)
    with_pass, _ = make_customer(w.tenant, w.owner, name="Has Pass")
    nopass, _ = make_customer(w.tenant, w.owner, name="No Pass")
    buy(w.tenant, w.owner, with_pass, w.plan)
    with w.ctx():
        customers.set_status(actor=w.owner, customer=customers.get_customer(nopass.public_id), status="BLOCKED")
        names = lambda **kw: sorted(c.full_name for c in customers.list_customers(**kw))  # noqa: E731
        assert names(status="active_pass") == ["Has Pass"]
        assert "Has Pass" not in names(status="no_pass") and "No Pass" in names(status="no_pass")
        assert names(status="blocked") == ["No Pass"]
        assert names(status="expiring") == []
        assert (
            names(query="has p") == ["Has Pass"]
            and names(query=with_pass.customer_code) == ["Has Pass"]
            and names(query=with_pass.phone_e164) == ["Has Pass"]
        )


def test_search_p95_under_200ms_with_2000_customers():
    w = World(buy_pass=False)
    with platform_context():
        users = User.objects.bulk_create(
            User(phone_e164=f"+9170{i:08d}", password=make_password(None), name=f"Cust {i}") for i in range(2000)
        )
        Customer.objects.bulk_create(
            Customer(
                tenant_id=w.tenant.id,
                user=u,
                customer_code=f"X{i:05d}",
                full_name=f"{['Asha', 'Ravi', 'Meena', 'Kiran'][i % 4]} Person{i}",
                phone_e164=u.phone_e164,
                pin_hash="x",
            )
            for i, u in enumerate(users)
        )
    queries = ["Asha", "Person19", "X0150", "7000001", "+917000", "Kiran Pers", "Meena", "00199"]
    timings = []
    with w.ctx():
        assert Customer.objects.count() == 2001
        for _ in range(6):
            for q in queries:
                t0 = time.perf_counter()
                list(customers.search(q, limit=8))
                timings.append((time.perf_counter() - t0) * 1000)
    p95 = statistics.quantiles(timings, n=100)[94]
    print(f"\nSEARCH p95 over 2000 customers: {p95:.1f} ms (n={len(timings)})")  # noqa: T201
    assert p95 <= 200


def test_role_enum_membership_for_customers():
    w = World(buy_pass=False)
    assert Role.CUSTOMER == "CUSTOMER" and w.customer.user_id
