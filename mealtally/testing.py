"""Builders shared by the test-suite (they go through the real service layer)."""

from __future__ import annotations

import itertools
from datetime import datetime

from django.utils import timezone

from mealtally.accounts import services as accounts
from mealtally.accounts.models import Role
from mealtally.accounts.policy import Actor
from mealtally.billing import services as billing
from mealtally.customers import services as customers
from mealtally.plans import services as plans
from mealtally.plans.models import Plan
from mealtally.tenancy import services as tenancy
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.context import tenant_context

_seq = itertools.count(1)
PASSWORD = "S3cure-Passw0rd!"


def make_tenant(slug: str | None = None, *, timezone_name: str = "Asia/Kolkata", **settings_overrides):
    n = next(_seq)
    slug = slug or f"tenant-{n}"
    tenant = tenancy.create_tenant(name=slug.title(), slug=slug, timezone=timezone_name)
    if settings_overrides:
        with platform_context():
            row = tenancy.get_settings(tenant.id)
            for key, value in settings_overrides.items():
                setattr(row, key, value)
            row.save()
    return tenant


def make_user(tenant, role=Role.OWNER, *, email: str | None = None, phone: str | None = None, password: str = PASSWORD):
    n = next(_seq)
    email = email if (email or phone) else f"user{n}@example.test"
    with platform_context():
        return accounts.create_staff_user(tenant_id=tenant.id, role=role, email=email, phone=phone, password=password)


def make_actor(tenant, role=Role.OWNER, **kwargs) -> Actor:
    user = make_user(tenant, role, **kwargs)
    return Actor(user=user, role=role, tenant_id=tenant.id)


def make_plan(tenant, **kwargs) -> Plan:
    defaults = {"name": "Monthly Meal Pass", "price_minor": 150000, "meals_per_cycle": 30, "validity_days": 30}
    defaults.update(kwargs)
    with tenant_context(tenant.id):
        return plans.create_plan(tenant_id=tenant.id, **defaults)


def make_customer(tenant, actor: Actor, *, phone: str | None = None, name: str = "Asha Customer"):
    n = next(_seq)
    phone = phone or f"+9198{n:08d}"
    with tenant_context(tenant.id):
        return customers.create_customer(actor=actor, full_name=name, phone=phone)  # -> (customer, pin)


def buy(
    tenant, actor: Actor, customer, plan, *, now: datetime | None = None, method: str = "CASH", reference: str = ""
):
    if method != "CASH" and not reference:
        reference = f"UTR{next(_seq):010d}"
    with tenant_context(tenant.id):
        return billing.record_payment(
            actor=actor,
            customer_public_id=customer.public_id,
            plan_public_id=plan.public_id,
            amount_minor=plan.price_minor,
            method=method,
            reference=reference,
            now=now or timezone.now(),
        )


class World:
    """One tenant with an owner, a plan, a customer and (optionally) an active pass."""

    def __init__(
        self,
        *,
        slug=None,
        buy_pass=True,
        plan_kwargs=None,
        tenant_settings=None,
        timezone_name="Asia/Kolkata",
        ui_shell="classic",
    ):
        self.tenant = make_tenant(slug, timezone_name=timezone_name, **(tenant_settings or {}))
        if ui_shell != "console":  # the product default is console (D03.5); most UI tests exercise the classic fallback
            with platform_context():
                type(self.tenant).objects.filter(pk=self.tenant.pk).update(ui_shell=ui_shell)
            self.tenant.ui_shell = ui_shell
        self.owner = make_actor(self.tenant, Role.OWNER)
        self.manager = make_actor(self.tenant, Role.MANAGER)
        self.staff = make_actor(self.tenant, Role.STAFF)
        self.plan = make_plan(self.tenant, **(plan_kwargs or {}))
        self.customer, self.pin = make_customer(self.tenant, self.owner)
        self.recorded = buy(self.tenant, self.owner, self.customer, self.plan) if buy_pass else None
        self.pass_ = self.recorded.pass_ if self.recorded else None

    def ctx(self):
        return tenant_context(self.tenant.id)
