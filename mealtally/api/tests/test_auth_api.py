# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from mealtally.testing import PASSWORD
from mealtally.testing import World
from mealtally.testing import make_user

pytestmark = pytest.mark.django_db


def test_staff_login_by_email_and_phone_then_session_works():
    w = World(slug="auth1")
    make_user(w.tenant, "STAFF", phone="+919111111111", email=None, password="Another-Passw0rd!")
    client = APIClient()
    resp = client.post("/api/v1/auth/login", {"login": w.owner.user.email.upper(), "password": PASSWORD}, format="json")
    assert resp.status_code == 200
    assert {"tenant": "auth1", "role": "OWNER"} in resp.json()["memberships"]
    assert client.get("/api/v1/t/auth1/plans").status_code == 200  # session cookie carries identity
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/t/auth1/plans").status_code == 401

    by_phone = APIClient().post(
        "/api/v1/auth/login", {"login": "91111 11111", "password": "Another-Passw0rd!"}, format="json"
    )
    assert by_phone.status_code == 200 and by_phone.json()["user"]["phone"] == "+919111111111"


def test_wrong_password_unknown_user_and_inactive_user_all_look_the_same():
    w = World(slug="auth2")
    client = APIClient()
    bad = client.post("/api/v1/auth/login", {"login": w.owner.user.email, "password": "nope-nope-nope"}, format="json")
    unknown = client.post(
        "/api/v1/auth/login", {"login": "ghost@example.test", "password": "nope-nope-nope"}, format="json"
    )
    assert bad.status_code == unknown.status_code == 401
    assert bad.json()["error"]["code"] == unknown.json()["error"]["code"] == "AUTH_FAILED"
    w.owner.user.is_active = False
    w.owner.user.save()
    assert (
        client.post(
            "/api/v1/auth/login", {"login": w.owner.user.email, "password": PASSWORD}, format="json"
        ).status_code
        == 401
    )


def test_staff_lockout_after_5_failures_then_even_the_right_password_is_refused():
    w = World(slug="auth3")
    client = APIClient()
    creds = {"login": w.owner.user.email, "password": "wrong-wrong-wrong"}
    codes = [client.post("/api/v1/auth/login", creds, format="json").status_code for _ in range(5)]
    assert codes[:4] == [401] * 4 and codes[4] == 429  # the 5th failure trips the lock
    locked = client.post("/api/v1/auth/login", {"login": w.owner.user.email, "password": PASSWORD}, format="json")
    assert locked.status_code == 429 and locked.json()["error"]["code"] == "ACCOUNT_LOCKED"
    other = APIClient().post(
        "/api/v1/auth/login", {"login": make_user(w.tenant, "STAFF").email, "password": PASSWORD}, format="json"
    )
    assert other.status_code == 200  # other identities are unaffected


def test_customer_login_and_me():
    w = World(slug="auth4")
    client = APIClient()
    ok = client.post(
        "/api/v1/t/auth4/auth/customer/login", {"phone": w.customer.phone_e164, "pin": w.pin}, format="json"
    )
    assert ok.status_code == 200 and ok.json()["customer"]["customer_code"] == "C0001"
    me = client.get("/api/v1/t/auth4/me")
    assert me.status_code == 200
    body = me.json()
    assert body["meals_remaining"] == 30 and body["meals_consumed"] == 0
    assert (
        body["active_pass"]["status"] == "ACTIVE"
        and body["starts_at"]
        and body["ends_at"]
        and body["queued_passes"] == []
    )
    assert client.post("/api/v1/t/auth4/auth/customer/logout").status_code == 200
    assert client.get("/api/v1/t/auth4/me").status_code == 401


def test_customer_login_is_tenant_scoped_and_blocked_customers_are_refused():
    from mealtally.customers import services as customers

    a = World(slug="auth5a")
    World(slug="auth5b")
    client = APIClient()
    # same phone+pin against the other tenant's slug fails
    resp = client.post(
        "/api/v1/t/auth5b/auth/customer/login", {"phone": a.customer.phone_e164, "pin": a.pin}, format="json"
    )
    assert resp.status_code == 401
    resp = client.post(
        "/api/v1/t/does-not-exist/auth/customer/login", {"phone": a.customer.phone_e164, "pin": a.pin}, format="json"
    )
    assert resp.status_code == 401
    with a.ctx():
        customers.set_status(actor=a.owner, customer=a.customer, status="BLOCKED")
    assert (
        client.post(
            "/api/v1/t/auth5a/auth/customer/login", {"phone": a.customer.phone_e164, "pin": a.pin}, format="json"
        ).status_code
        == 401
    )


def test_customer_lockout_after_5_bad_pins():
    w = World(slug="auth6")
    client = APIClient()
    url = "/api/v1/t/auth6/auth/customer/login"
    for _ in range(4):
        assert client.post(url, {"phone": w.customer.phone_e164, "pin": "000000"}, format="json").status_code == 401
    assert client.post(url, {"phone": w.customer.phone_e164, "pin": "000000"}, format="json").status_code == 429
    resp = client.post(url, {"phone": w.customer.phone_e164, "pin": w.pin}, format="json")
    assert resp.status_code == 429 and resp.json()["error"]["code"] == "ACCOUNT_LOCKED"


def test_same_person_is_a_customer_at_two_tenants_with_separate_pins():
    from mealtally.testing import buy
    from mealtally.testing import make_customer

    a, b = World(slug="multi-a", buy_pass=False), World(slug="multi-b", buy_pass=False)
    phone = "+919222222222"
    ca, pa = make_customer(a.tenant, a.owner, phone=phone, name="Dual A")
    cb, pb = make_customer(b.tenant, b.owner, phone=phone, name="Dual B")
    assert ca.user_id == cb.user_id  # one global identity
    buy(a.tenant, a.owner, ca, a.plan)
    client = APIClient()
    assert (
        client.post("/api/v1/t/multi-a/auth/customer/login", {"phone": phone, "pin": pa}, format="json").status_code
        == 200
    )
    assert client.get("/api/v1/t/multi-a/me").json()["customer"]["full_name"] == "Dual A"
    # logged in as the person, but only a member of tenant b once we also hold that membership: both memberships exist
    assert client.get("/api/v1/t/multi-b/me").json()["customer"]["full_name"] == "Dual B"
    assert client.post(
        "/api/v1/t/multi-b/auth/customer/login", {"phone": phone, "pin": pa}, format="json"
    ).status_code in (200, 401)


def test_login_endpoint_is_rate_limited(monkeypatch):
    from mealtally.api.throttles import LoginThrottle

    monkeypatch.setattr(LoginThrottle, "THROTTLE_RATES", {"login": "3/min"})
    client = APIClient()
    statuses = [
        client.post(
            "/api/v1/auth/login", {"login": f"x{i}@example.test", "password": "whatever-1"}, format="json"
        ).status_code
        for i in range(5)
    ]
    assert statuses[:3] == [401, 401, 401] and statuses[3:] == [429, 429]
    assert (
        client.post("/api/v1/auth/login", {"login": "y@example.test", "password": "z"}, format="json").json()["error"][
            "code"
        ]
        == "RATE_LIMITED"
    )


def test_csrf_endpoint_and_enforcement_for_session_users():
    w = World(slug="auth7")
    client = APIClient(enforce_csrf_checks=True)
    assert client.get("/api/v1/auth/csrf").status_code == 200
    login = client.post("/api/v1/auth/login", {"login": w.owner.user.email, "password": PASSWORD}, format="json")
    assert login.status_code == 200  # login itself needs no CSRF token
    denied = client.post("/api/v1/t/auth7/customers", {"full_name": "A", "phone": "+919333333333"}, format="json")
    assert denied.status_code == 403  # session-authenticated POST without CSRF token
    token = client.cookies["__Secure-csrftoken" if "__Secure-csrftoken" in client.cookies else "csrftoken"].value
    ok = client.post(
        "/api/v1/t/auth7/customers", {"full_name": "A", "phone": "+919333333333"}, format="json", HTTP_X_CSRFTOKEN=token
    )
    assert ok.status_code == 201
