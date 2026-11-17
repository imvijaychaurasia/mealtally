# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import pytest

from mealtally.accounts import services as accounts
from mealtally.accounts.models import Role
from mealtally.audit.models import AuditEvent
from mealtally.billing.models import FeePolicy
from mealtally.common.errors import AuthFailed
from mealtally.common.errors import NotAllowed
from mealtally.common.errors import NotFound
from mealtally.common.errors import ValidationFailed
from mealtally.plans import services as plans
from mealtally.plans.models import Plan
from mealtally.tenancy import services as tenancy
from mealtally.tenancy.context import platform_context
from mealtally.testing import PASSWORD
from mealtally.testing import World
from mealtally.testing import make_user

pytestmark = pytest.mark.django_db


def test_onboard_tenant_creates_everything_in_one_go():
    with platform_context():
        root = accounts.User.objects.create_superuser(email="root-onb@example.test", password="Sup3r-Secret-Pw!")
    tenant, owner, password = tenancy.onboard_tenant(
        actor_user=root,
        name="Fresh Tiffin",
        slug="fresh-tiffin",
        timezone_name="Asia/Kolkata",
        owner_name="Fay",
        owner_email="fay@fresh.example.com",
    )
    assert owner.must_change_password is True and password and owner.check_password(password)
    with platform_context():
        assert (
            Plan.objects.get(tenant=tenant).price_minor == 150000
            and Plan.objects.get(tenant=tenant).meals_per_cycle == 30
        )
        assert FeePolicy.objects.get(tenant=tenant).platform_pct == 12
        assert tenancy.get_settings(tenant.id).display_name == "Fresh Tiffin"
        assert accounts.active_roles(user=owner, tenant_id=tenant.id) == [Role.OWNER]
        assert AuditEvent.objects.filter(action="tenant.onboard", tenant=tenant).exists()
    with pytest.raises(ValidationFailed):  # duplicate slug => nothing half created
        tenancy.onboard_tenant(
            actor_user=root,
            name="Dup",
            slug="fresh-tiffin",
            timezone_name="Asia/Kolkata",
            owner_name="X",
            owner_email="x@fresh.example.com",
        )
    with pytest.raises(Exception):  # noqa: B017,PT011 -- invalid timezone: model validation, whole transaction undone
        tenancy.onboard_tenant(
            actor_user=root,
            name="Bad",
            slug="bad-tz",
            timezone_name="Mars/Base",
            owner_name="X",
            owner_email="bad@fresh.example.com",
        )
    with platform_context():
        assert not accounts.User.objects.filter(email="bad@fresh.example.com").exists()


def test_update_settings_validation_audit_and_timezone():
    w = World(buy_pass=False)
    with w.ctx():
        row = tenancy.update_settings(
            actor=w.owner,
            timezone_name="Asia/Dubai",
            display_name="Pilot Tiffin (test)",
            brand_color="#112233",
            redeem_cooldown_seconds=60,
            allow_self_signup=True,
            tax_id="29ABCDE1234F1Z5",
            max_queued_passes=2,
            receipt_footer="Hi",
        )
        assert row.brand_color == "#112233" and row.allow_self_signup and row.max_queued_passes == 2
        assert tenancy.get_settings(w.tenant.id).display_name == "Pilot Tiffin (test)"
        assert AuditEvent.objects.filter(action="settings.update").count() == 1
        from mealtally.tenancy.models import Tenant

        assert Tenant.objects.get(pk=w.tenant.id).timezone == "Asia/Dubai"
        for bad in (
            {"brand_color": "teal"},
            {"redeem_cooldown_seconds": -1},
            {"redeem_cooldown_seconds": 99999},
            {"max_queued_passes": 9},
            {"tax_id": "short"},
            {"staff_reversal_window_hours": "x"},
        ):
            with pytest.raises(ValidationFailed):
                tenancy.update_settings(actor=w.owner, **bad)
        with pytest.raises(ValidationFailed):
            tenancy.update_settings(actor=w.owner, timezone_name="Nope/Zone")
        with pytest.raises(NotAllowed):
            tenancy.update_settings(actor=w.manager, display_name="x")


def test_change_password_rules():
    w = World(buy_pass=False)
    user = w.owner.user
    user.must_change_password = True
    user.save()
    with pytest.raises(AuthFailed):
        accounts.change_password(user=user, old_password="wrong", new_password="Another-Strong-1")
    with pytest.raises(ValidationFailed):
        accounts.change_password(user=user, old_password=PASSWORD, new_password=PASSWORD)
    with pytest.raises(ValidationFailed):
        accounts.change_password(user=user, old_password=PASSWORD, new_password="short")
    accounts.change_password(user=user, old_password=PASSWORD, new_password="Another-Strong-1")
    user.refresh_from_db()
    assert not user.must_change_password and user.check_password("Another-Strong-1")


def test_staff_management_by_owner_only():
    w = World(buy_pass=False)
    with w.ctx():
        user, pw = accounts.add_staff_member(
            actor=w.owner, name="New Staff", email="ns@x.example.com", phone=None, role="STAFF"
        )
        assert user.must_change_password and user.check_password(pw)
        assert {m.role for m in accounts.list_staff(w.tenant.id)} >= {"OWNER", "STAFF"}
        for kwargs in (
            {"email": "ns@x.example.com", "role": "STAFF"},
            {"email": None, "phone": None, "role": "STAFF"},
            {"email": "r@x.example.com", "role": "OWNER"},
        ):
            with pytest.raises(ValidationFailed):
                accounts.add_staff_member(actor=w.owner, name="X", phone=kwargs.pop("phone", None), **kwargs)
        with pytest.raises(NotAllowed):
            accounts.add_staff_member(actor=w.manager, name="X", email="m@x.example.com", phone=None, role="STAFF")
        m = accounts.set_staff_active(actor=w.owner, user_id=user.pk, active=False)
        assert not m.is_active
        assert accounts.set_staff_active(actor=w.owner, user_id=user.pk, active=True).is_active
        with pytest.raises(ValidationFailed):
            accounts.set_staff_active(actor=w.owner, user_id=w.owner.user.pk, active=False)
        with pytest.raises(NotFound):
            accounts.set_staff_active(actor=w.owner, user_id=999999, active=False)
        u2, pw2 = accounts.reset_staff_password(actor=w.owner, user_id=user.pk)
        assert u2.check_password(pw2) and u2.must_change_password and not u2.check_password(pw)
        with pytest.raises(NotFound):
            accounts.reset_staff_password(actor=w.owner, user_id=999999)
    other = make_user(w.tenant, Role.STAFF)  # noqa: F841


def test_plan_management_roles_validation_and_snapshot_independence():
    w = World()
    with w.ctx():
        plan = plans.save_plan(
            actor=w.manager,
            name="Weekly",
            price_minor=70000,
            meals_per_cycle=7,
            validity_mode="ROLLING_DAYS",
            validity_days=7,
            max_meals_per_day=1,
            is_active=True,
        )
        assert plan.max_meals_per_day == 1
        plans.save_plan(
            actor=w.owner, plan=w.plan, price_minor=999900, meals_per_cycle=99
        )  # edit the plan the pilot pass was sold from
        from mealtally.passes.models import Pass

        p = Pass.objects.get(pk=w.pass_.pk)
        assert (p.price_minor, p.meals_total) == (150000, 30)  # snapshot untouched
        for bad in (
            {"name": " "},
            {"price_minor": 0},
            {"meals_per_cycle": -1},
            {"max_meals_per_day": 0},
            {"validity_mode": "WEEKLY"},
        ):
            with pytest.raises(ValidationFailed):
                plans.save_plan(actor=w.owner, plan=plan, **bad)
        plans.save_plan(actor=w.owner, plan=plan, max_meals_per_day=None, is_active=False)
        assert plan.max_meals_per_day is None and not plan.is_active
        with pytest.raises(NotAllowed):
            plans.save_plan(actor=w.staff, name="x", price_minor=1, meals_per_cycle=1, validity_days=1)
        assert AuditEvent.objects.filter(action__in=["plan.create", "plan.update"]).count() >= 3
