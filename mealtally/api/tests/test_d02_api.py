from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from mealtally.accounts.models import User
from mealtally.tenancy.context import platform_context
from mealtally.testing import PASSWORD
from mealtally.testing import World
from mealtally.testing import buy

from .conftest import login_as

pytestmark = pytest.mark.django_db


def test_login_responses_carry_forced_change_flags():
    w = World(slug="apif")
    w.owner.user.must_change_password = True
    w.owner.user.save()
    r = APIClient().post("/api/v1/auth/login", {"login": w.owner.user.email, "password": PASSWORD}, format="json")
    assert r.json()["must_change_password"] is True
    r = APIClient().post(
        "/api/v1/t/apif/auth/customer/login", {"phone": w.customer.phone_e164, "pin": w.pin}, format="json"
    )
    assert r.json()["must_change_pin"] is True


def test_change_password_and_change_pin(w, base, owner_client):
    assert (
        owner_client.post(
            "/api/v1/auth/change-password", {"old_password": "bad", "new_password": "Brand-New-Pass-99"}, format="json"
        ).status_code
        == 401
    )
    assert (
        owner_client.post(
            "/api/v1/auth/change-password", {"old_password": PASSWORD, "new_password": "short"}, format="json"
        ).status_code
        == 400
    )
    assert (
        owner_client.post(
            "/api/v1/auth/change-password",
            {"old_password": PASSWORD, "new_password": "Brand-New-Pass-99"},
            format="json",
        ).status_code
        == 200
    )
    cust = login_as(w.customer.user)
    assert cust.post(f"{base}/me/change-pin", {"old_pin": w.pin, "new_pin": "573920"}, format="json").status_code == 200
    assert cust.post(f"{base}/me/change-pin", {"old_pin": w.pin, "new_pin": "573921"}, format="json").status_code == 400


def test_signup_endpoint_respects_the_flag(w, base):
    anon = APIClient()
    assert (
        anon.post(
            f"{base}/auth/customer/signup", {"full_name": "A", "phone": "9822000001", "pin": "482916"}, format="json"
        ).status_code
        == 403
    )
    r = login_as(w.owner.user).patch(f"{base}/settings", {"allow_self_signup": True}, format="json")
    assert r.status_code == 200 and r.json()["allow_self_signup"] is True
    ok = anon.post(
        f"{base}/auth/customer/signup", {"full_name": "A", "phone": "9822000001", "pin": "482916"}, format="json"
    )
    assert ok.status_code == 201 and ok.json()["customer"]["customer_code"].startswith("C")
    assert anon.post("/api/v1/t/nope/auth/customer/signup", {}, format="json").status_code == 404


def test_customer_admin_endpoints(w, base, owner_client, manager_client, staff_client):
    lst = owner_client.get(f"{base}/customers/admin-list", {"status": "active_pass"}).json()["results"]
    assert lst[0]["has_active_pass"] is True
    cid = w.customer.public_id
    assert (
        owner_client.patch(
            f"{base}/customers/{cid}/update", {"full_name": "Asha K", "notes": "n"}, format="json"
        ).json()["full_name"]
        == "Asha K"
    )
    assert staff_client.post(f"{base}/customers/{cid}/block", {"reason": "x"}, format="json").status_code == 403
    assert (
        manager_client.post(f"{base}/customers/{cid}/block", {"reason": "x"}, format="json").json()["status"]
        == "BLOCKED"
    )
    assert (
        manager_client.post(f"{base}/customers/{cid}/unblock", {"reason": "x"}, format="json").json()["status"]
        == "ACTIVE"
    )
    r = staff_client.post(f"{base}/customers/{cid}/reset-pin", {"pin": "630418"}, format="json")
    assert r.json()["pin"] == "630418"
    c = staff_client.post(
        f"{base}/customers", {"full_name": "Own Pin", "phone": "9833000001", "pin": "482916"}, format="json"
    )
    assert c.status_code == 201 and c.json()["initial_pin"] == "482916"


def test_plans_staff_settings_endpoints(w, base, owner_client, manager_client):
    assert (
        manager_client.post(
            f"{base}/plans/manage",
            {"name": "Weekly", "price_major": "700", "meals_per_cycle": 7, "validity_days": 7},
            format="json",
        ).status_code
        == 201
    )
    allp = manager_client.get(f"{base}/plans/manage", {"all": "1"}).json()["results"]
    weekly = next(p for p in allp if p["name"] == "Weekly")
    assert weekly["price_minor"] == 70000
    assert (
        manager_client.patch(
            f"{base}/plans/{weekly['id']}", {"is_active": False, "max_meals_per_day": 1}, format="json"
        ).json()["is_active"]
        is False
    )
    assert all(p["name"] != "Weekly" for p in manager_client.get(f"{base}/plans/manage").json()["results"])
    assert (
        manager_client.post(
            f"{base}/staff", {"name": "x", "email": "s@x.example.com", "role": "STAFF"}, format="json"
        ).status_code
        == 403
    )
    r = owner_client.post(
        f"{base}/staff", {"name": "New", "email": "newstaff@x.example.com", "role": "STAFF"}, format="json"
    )
    assert r.status_code == 201 and r.json()["temporary_password"] and r.json()["must_change_password"]
    uid = r.json()["user_id"]
    assert any(m["user_id"] == uid for m in owner_client.get(f"{base}/staff").json()["results"])
    assert owner_client.post(f"{base}/staff/{uid}/reset-password").json()["temporary_password"]
    assert owner_client.post(f"{base}/staff/{uid}/deactivate").json()["is_active"] is False
    assert owner_client.post(f"{base}/staff/{uid}/activate").json()["is_active"] is True
    assert owner_client.post(f"{base}/staff/{uid}/bogus").status_code == 404
    s = owner_client.get(f"{base}/settings").json()
    assert s["timezone"] == "Asia/Kolkata" and s["redeem_cooldown_seconds"] == 120
    assert (
        owner_client.patch(f"{base}/settings", {"brand_color": "#102030", "timezone": "UTC"}, format="json").json()[
            "timezone"
        ]
        == "UTC"
    )
    assert owner_client.patch(f"{base}/settings", {"brand_color": "teal"}, format="json").status_code == 400
    assert manager_client.patch(f"{base}/settings", {"display_name": "x"}, format="json").status_code == 403


def test_report_endpoints_json_and_csv(w, base, owner_client, staff_client):
    assert owner_client.get(f"{base}/reports/dashboard").json()["active_passes"] == 1
    for path, needle in (
        ("reports/daily-consumption", "total"),
        ("reports/monthly", "passes_sold"),
        ("reports/expired", "total_forfeited"),
        (f"customers/{w.customer.public_id}/statement", "payments"),
    ):
        assert needle in owner_client.get(f"{base}/{path}").json(), path
        csv = owner_client.get(f"{base}/{path}", {"export": "csv"})
        assert csv.status_code == 200 and csv["Content-Type"].startswith("text/csv"), path
    assert owner_client.get(f"{base}/reports/daily-consumption", {"start": "bad"}).status_code == 400
    assert staff_client.get(f"{base}/reports/dashboard").status_code == 403
    audit = owner_client.get(f"{base}/audit", {"action": "payment"}).json()["results"]
    assert audit and audit[0]["action"] == "payment.record"
    assert staff_client.get(f"{base}/audit").status_code == 403


def test_sale_preview_and_receipts(w, base, owner_client, staff_client):
    cal = owner_client.post(
        f"{base}/plans/manage",
        {
            "name": "Cal",
            "price_major": "1000",
            "meals_per_cycle": 30,
            "validity_mode": "CALENDAR_MONTH",
            "validity_days": 30,
        },
        format="json",
    ).json()
    pv = staff_client.post(
        f"{base}/sales/preview", {"plan": cal["id"], "customer": str(w.customer.public_id)}, format="json"
    ).json()
    assert (
        pv["status"] == "QUEUED"
        and pv["no_proration"] is True
        and pv["gap"]["from"] < pv["gap"]["to"]
        and pv["amount_minor"] == 100000
    )
    fresh = staff_client.post(f"{base}/sales/preview", {"plan": cal["id"]}, format="json").json()
    assert fresh["status"] == "ACTIVE" and fresh["gap"] is None
    pid = w.recorded.payment.public_id
    d = staff_client.get(f"{base}/payments/{pid}").json()
    assert d["receipt_number"] == "R-000001" and d["customer"]["customer_code"] == w.customer.customer_code
    pdf = staff_client.get(f"{base}/payments/{pid}/receipt.pdf")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf" and pdf.content[:5] == b"%PDF-"
    cust = login_as(w.customer.user)
    assert cust.get(f"{base}/payments/{pid}/receipt.pdf").status_code == 200
    other = buy(
        w.tenant,
        w.owner,
        __import__("mealtally.testing", fromlist=["make_customer"]).make_customer(w.tenant, w.owner, name="Other")[0],
        w.plan,
    )
    assert cust.get(f"{base}/payments/{other.payment.public_id}/receipt.pdf").status_code == 404


def test_platform_onboard_and_dashboard_endpoints(w):
    with platform_context():
        root = User.objects.create_superuser(email="root-api@example.test", password="Sup3r-Secret-Pw!")
    c = login_as(root)
    r = c.post(
        "/api/v1/platform/onboard",
        {"name": "API Tenant", "slug": "api-tenant", "owner_name": "Ola", "owner_email": "ola@api.example.com"},
        format="json",
    )
    assert r.status_code == 201 and r.json()["temporary_password"] and r.json()["owner_login"] == "ola@api.example.com"
    rows = {t["slug"]: t for t in c.get("/api/v1/platform/dashboard").json()["results"]}
    assert "api-tenant" in rows and rows["webt" if "webt" in rows else "api-tenant"]
    assert login_as(w.owner.user).post("/api/v1/platform/onboard", {}, format="json").status_code == 403
    assert w


def test_login_throttle_is_30_per_10_minutes():
    from mealtally.api.throttles import LoginThrottle

    num, duration = LoginThrottle().parse_rate("30/10min")
    assert (num, duration) == (30, 600)
    assert LoginThrottle().parse_rate("5/min") == (5, 60) and LoginThrottle().parse_rate(None) == (None, None)
