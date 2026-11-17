# SPDX-License-Identifier: AGPL-3.0-only
"""D02.1 Q2: while a temporary password / PIN is in force the API refuses everything except the change itself."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from mealtally.accounts.models import User
from mealtally.tenancy.context import platform_context
from mealtally.testing import PASSWORD
from mealtally.testing import World

from .conftest import login_as

pytestmark = pytest.mark.django_db


def test_staff_with_a_temporary_password_is_blocked_until_the_change():
    w = World(slug="d021api")
    user = w.owner.user
    user.must_change_password = True
    user.save()
    c = login_as(user)
    base = "/api/v1/t/d021api"
    for method, path in (("get", "/plans"), ("get", "/customers"), ("get", "/reports/dashboard"), ("get", "/staff")):
        r = getattr(c, method)(base + path)
        assert r.status_code == 403 and r.json()["error"]["code"] == "CREDENTIAL_CHANGE_REQUIRED", path
    assert c.post("/api/v1/auth/logout").status_code == 200  # logout is always allowed
    c = login_as(user)
    assert (
        c.post(
            "/api/v1/auth/change-password",
            {"old_password": PASSWORD, "new_password": "Brand-New-Pass-99"},
            format="json",
        ).status_code
        == 200
    )
    assert c.get(base + "/plans").status_code == 200


def test_customer_with_a_temporary_pin_can_only_read_me_and_change_the_pin():
    w = World(slug="d021pin")
    c = APIClient()
    assert (
        c.post(
            "/api/v1/t/d021pin/auth/customer/login", {"phone": w.customer.phone_e164, "pin": w.pin}, format="json"
        ).json()["must_change_pin"]
        is True
    )
    base = "/api/v1/t/d021pin"
    me = c.get(base + "/me")
    assert me.status_code == 200
    for path in ("/me/ledger", "/me/payments", "/me/qr-token", "/me/qr.svg"):
        r = c.get(base + path)
        assert r.status_code == 403 and r.json()["error"]["code"] == "CREDENTIAL_CHANGE_REQUIRED", path
    assert c.post(base + "/me/change-pin", {"old_pin": w.pin, "new_pin": "573920"}, format="json").status_code == 200
    assert c.get(base + "/me/ledger").status_code == 200 and c.get(base + "/me/qr-token").status_code == 200


def test_platform_admin_with_a_temporary_password_is_blocked_too():
    with platform_context():
        root = User.objects.create_superuser(email="root-q2@example.test", password="Sup3r-Secret-Pw!")
        root.must_change_password = True
        root.save()
    c = login_as(root)
    r = c.get("/api/v1/platform/tenants")
    assert r.status_code == 403 and r.json()["error"]["code"] == "CREDENTIAL_CHANGE_REQUIRED"
    assert (
        c.post(
            "/api/v1/auth/change-password",
            {"old_password": "Sup3r-Secret-Pw!", "new_password": "Another-Strong-77"},
            format="json",
        ).status_code
        == 200
    )
    assert c.get("/api/v1/platform/tenants").status_code == 200
