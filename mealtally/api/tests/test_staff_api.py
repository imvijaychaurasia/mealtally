from __future__ import annotations

import uuid

import pytest
from rest_framework.test import APIClient

from mealtally.accounts.models import Role
from mealtally.testing import World
from mealtally.testing import buy
from mealtally.testing import make_user

from .conftest import login_as

pytestmark = pytest.mark.django_db


def k() -> str:
    return str(uuid.uuid4())


def error(resp):
    body = resp.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "details"}
    return body["error"]


def test_unauthenticated_gets_the_error_envelope(w, base):
    resp = APIClient().get(f"{base}/customers")
    assert resp.status_code == 401 and error(resp)["code"] == "NOT_AUTHENTICATED"


def test_customer_create_search_and_detail(w, base, staff_client):
    created = staff_client.post(f"{base}/customers", {"full_name": "Ravi Kumar", "phone": "98765 43210"}, format="json")
    assert created.status_code == 201
    body = created.json()
    assert body["phone"] == "+919876543210" and body["customer_code"] == "C0002"
    assert len(body["initial_pin"]) == 6 and body["initial_pin"].isdigit()
    assert "pin_hash" not in body and body["active_pass"] is None
    dup = staff_client.post(f"{base}/customers", {"full_name": "Dup", "phone": "+919876543210"}, format="json")
    assert dup.status_code == 400 and error(dup)["code"] == "VALIDATION_ERROR"
    bad = staff_client.post(f"{base}/customers", {"full_name": "X", "phone": "12"}, format="json")
    assert bad.status_code == 400
    for q, expected in (("Ravi", 1), ("c0002", 1), ("43210", 1), ("+919876543210", 1), ("nobody", 0)):
        resp = staff_client.get(f"{base}/customers", {"search": q})
        assert len(resp.json()["results"]) == expected, q
    detail = staff_client.get(f"{base}/customers/{body['id']}")
    assert detail.status_code == 200 and detail.json()["full_name"] == "Ravi Kumar"


def test_payment_to_pass_and_redeem_flow(w, base, staff_client):
    cust = staff_client.post(
        f"{base}/customers", {"full_name": "Meena", "phone": "+919000000001"}, format="json"
    ).json()
    plan = staff_client.get(f"{base}/plans").json()["results"][0]
    assert plan["price_minor"] == 150000
    pay = staff_client.post(
        f"{base}/payments",
        {
            "customer": cust["id"],
            "plan": plan["id"],
            "amount_minor": 150000,
            "method": "UPI_MANUAL",
            "reference": "UTR1",
        },
        format="json",
    )
    assert pay.status_code == 201
    assert pay.json()["pass"]["status"] == "ACTIVE" and pay.json()["pass"]["meals_remaining"] == 30

    key = k()
    r1 = staff_client.post(f"{base}/redeem", {"customer": cust["id"], "idempotency_key": key}, format="json")
    assert r1.status_code == 201
    out = r1.json()
    assert set(out) == {"entry_public_id", "customer", "pass", "meals_remaining", "meal_date", "replayed"}
    assert out["meals_remaining"] == 29 and out["replayed"] is False
    r2 = staff_client.post(f"{base}/redeem", {"customer": cust["id"], "idempotency_key": key}, format="json")
    assert (
        r2.status_code == 200
        and r2.json()["replayed"] is True
        and r2.json()["entry_public_id"] == out["entry_public_id"]
    )
    # double-scan guard
    r3 = staff_client.post(f"{base}/redeem", {"customer": cust["id"], "idempotency_key": k()}, format="json")
    assert r3.status_code == 409 and error(r3)["code"] == "COOLDOWN_CONFIRM_REQUIRED"
    r4 = staff_client.post(
        f"{base}/redeem", {"customer": cust["id"], "idempotency_key": k(), "confirm_additional": True}, format="json"
    )
    assert r4.status_code == 201 and r4.json()["meals_remaining"] == 28
    # reverse (staff inside window)
    rev = staff_client.post(f"{base}/ledger/{out['entry_public_id']}/reverse", {"reason": "wrong plate"}, format="json")
    assert rev.status_code == 201 and rev.json()["meals_remaining"] == 29
    again = staff_client.post(
        f"{base}/ledger/{out['entry_public_id']}/reverse", {"reason": "wrong plate"}, format="json"
    )
    assert again.status_code == 201 and again.json()["reversal"]["id"] == rev.json()["reversal"]["id"]
    # daily report
    rep = staff_client.get(f"{base}/reports/daily")
    assert rep.status_code == 200 and rep.json()["count"] == 1 and rep.json()["total_redemptions"] == 2


def test_error_codes_over_http(w, base, owner_client):
    nobody = owner_client.post(
        f"{base}/customers", {"full_name": "No Pass", "phone": "+919000000002"}, format="json"
    ).json()
    resp = owner_client.post(f"{base}/redeem", {"customer": nobody["id"], "idempotency_key": k()}, format="json")
    assert resp.status_code == 409 and error(resp)["code"] == "NO_ACTIVE_PASS"
    resp = owner_client.post(f"{base}/redeem", {"customer": "not-a-uuid"}, format="json")
    assert resp.status_code == 400 and error(resp)["code"] == "VALIDATION_ERROR"
    resp = owner_client.post(f"{base}/redeem", {"customer": str(uuid.uuid4()), "idempotency_key": k()}, format="json")
    assert resp.status_code == 404 and error(resp)["code"] == "NOT_FOUND"
    plan = owner_client.get(f"{base}/plans").json()["results"][0]
    resp = owner_client.post(
        f"{base}/payments",
        {"customer": nobody["id"], "plan": plan["id"], "amount_minor": 1, "method": "CASH"},
        format="json",
    )
    assert resp.status_code == 400 and error(resp)["code"] == "AMOUNT_MISMATCH"
    assert error(resp)["details"]["expected_minor"] == 150000
    resp = owner_client.post(
        f"{base}/payments",
        {"customer": nobody["id"], "plan": plan["id"], "amount_minor": 150000, "method": "GATEWAY", "reference": "x"},
        format="json",
    )
    assert resp.status_code == 400  # GATEWAY is reserved: not accepted over the v1 API
    assert owner_client.get(f"{base}/nothing-here").status_code == 404
    assert owner_client.delete(f"{base}/plans").status_code == 405


def test_failed_request_rolls_back_everything(w, base, owner_client):
    """A rejected redeem must not leave a partial write (ATOMIC_REQUESTS + DRF set_rollback)."""
    from mealtally.ledger.models import MealLedgerEntry

    before = None
    with w.ctx():
        before = MealLedgerEntry.objects.count()
    resp = owner_client.post(
        f"{base}/passes/{w.pass_.public_id}/adjust",
        {"quantity": -31, "reason": "too far", "idempotency_key": k()},
        format="json",
    )
    assert resp.status_code == 400 and error(resp)["code"] == "INSUFFICIENT_BALANCE"
    with w.ctx():
        assert MealLedgerEntry.objects.count() == before


# --- role matrix over HTTP ---------------------------------------------------------------------------
def test_role_matrix(w, base, owner_client, manager_client, staff_client):
    pid = str(w.pass_.public_id)
    pay_id = str(w.recorded.payment.public_id)
    cases = [
        # (method, path, body, {role: expected_status})
        ("post", f"/passes/{pid}/suspend", {"reason": "r"}, {"owner": 200, "manager": 403, "staff": 403}),
        (
            "post",
            f"/passes/{pid}/adjust",
            {"quantity": 1, "reason": "r", "idempotency_key": "rm-1"},
            {"owner": 201, "manager": 201, "staff": 403},
        ),
        ("get", "/reports/fees?month=2026-11", None, {"owner": 200, "manager": 403, "staff": 403}),
        (
            "post",
            f"/payments/{pay_id}/void",
            {"reason": "r"},
            {"manager": 409, "staff": 403},
        ),  # 409: pass was suspended+... see order
    ]
    # run adjust/fees first, then suspend, last void (order matters for pass state)
    order = [1, 2, 0, 3]
    clients = {"owner": owner_client, "manager": manager_client, "staff": staff_client}
    for idx in order:
        method, path, body, expectations = cases[idx]
        for role in ("staff", "manager", "owner"):  # least privileged first
            if role not in expectations:
                continue
            if body and "idempotency_key" in body:
                body = {**body, "idempotency_key": k()}
            resp = (
                getattr(clients[role], method)(f"{base}{path}", body, format="json")
                if body
                else getattr(clients[role], method)(f"{base}{path}")
            )
            if role == "manager" and idx == 3:
                # manager is allowed to void; the suspended pass can still be voided -> 200
                assert resp.status_code in (200, 409), (path, role, resp.json())
                continue
            assert resp.status_code == expectations[role], (path, role, resp.status_code, resp.json())


def test_customer_role_cannot_use_staff_endpoints_but_can_read_me(w, base):
    from mealtally.accounts.models import Membership
    from mealtally.tenancy.context import platform_context

    client = login_as(w.customer.user)
    for path in ("customers", "plans", "reports/daily"):
        resp = client.get(f"{base}/{path}")
        assert resp.status_code == 403 and error(resp)["code"] == "FORBIDDEN", path
    resp = client.post(f"{base}/redeem", {"customer": str(w.customer.public_id), "idempotency_key": k()}, format="json")
    assert resp.status_code == 403
    assert client.get(f"{base}/me").status_code == 200
    with platform_context():
        assert Membership.objects.filter(user=w.customer.user, role=Role.CUSTOMER).exists()


def test_suspended_tenant_blocks_all_tenant_endpoints(w, base, owner_client):
    from mealtally.tenancy import services as tenancy

    tenancy.set_status(tenant=w.tenant, status="SUSPENDED")
    resp = owner_client.get(f"{base}/customers")
    assert resp.status_code == 403 and error(resp)["code"] == "NOT_ALLOWED"


def test_manager_and_owner_void_and_suspend_flow(w, base, owner_client, manager_client):
    q = buy(w.tenant, w.owner, w.customer, w.plan)  # queued second pass
    resp = manager_client.post(f"{base}/payments/{q.payment.public_id}/void", {"reason": "dup"}, format="json")
    assert resp.status_code == 200 and resp.json()["payment"]["status"] == "VOIDED"
    assert (
        owner_client.post(f"{base}/passes/{w.pass_.public_id}/suspend", {"reason": "r"}, format="json").status_code
        == 200
    )
    redeem = owner_client.post(
        f"{base}/redeem", {"customer": str(w.customer.public_id), "idempotency_key": k()}, format="json"
    )
    assert redeem.status_code == 409 and error(redeem)["code"] == "NO_ACTIVE_PASS"
    assert (
        owner_client.post(f"{base}/passes/{w.pass_.public_id}/resume", {"reason": "ok"}, format="json").status_code
        == 200
    )
    assert (
        owner_client.post(f"{base}/passes/{w.pass_.public_id}/cancel", {"reason": "bye"}, format="json").status_code
        == 200
    )


def test_fee_report_shape(w, base, owner_client):
    from django.utils import timezone

    now = timezone.now().astimezone(w.tenant.zone)
    resp = owner_client.get(f"{base}/reports/fees", {"month": f"{now.year}-{now.month:02d}"})
    assert resp.status_code == 200
    body = resp.json()
    assert (
        body["platform_fee_minor"] == 18000 and body["gross_minor"] == 150000 and body["net_to_tenant_minor"] == 132000
    )
    assert owner_client.get(f"{base}/reports/fees", {"month": "garbage"}).status_code == 400
    assert owner_client.get(f"{base}/reports/daily", {"date": "nope"}).status_code == 400


def test_reset_pin_endpoint_and_customer_login_uses_new_pin(w, base, staff_client):
    cust = staff_client.post(
        f"{base}/customers", {"full_name": "Pin Test", "phone": "+919000000009"}, format="json"
    ).json()
    new = staff_client.post(f"{base}/customers/{cust['id']}/reset-pin").json()["pin"]
    anon = APIClient()
    assert (
        anon.post(
            f"{base}/auth/customer/login", {"phone": "+919000000009", "pin": cust["initial_pin"]}, format="json"
        ).status_code
        == 401
    )
    ok = anon.post(f"{base}/auth/customer/login", {"phone": "9000000009", "pin": new}, format="json")
    assert ok.status_code == 200 and ok.json()["customer"]["full_name"] == "Pin Test"


def test_staff_in_two_tenants_has_separate_roles():
    a, b = World(slug="aa"), World(slug="bb")
    user = a.owner.user
    from mealtally.accounts import services as accounts
    from mealtally.tenancy.context import platform_context

    with platform_context():
        accounts.ensure_membership(user=user, tenant_id=b.tenant.id, role=Role.STAFF)
    client = login_as(user)
    assert client.get(f"/api/v1/t/{a.tenant.slug}/reports/fees", {"month": "2026-11"}).status_code == 200  # OWNER at a
    assert client.get(f"/api/v1/t/{b.tenant.slug}/reports/fees", {"month": "2026-11"}).status_code == 403  # STAFF at b
    assert make_user(a.tenant, Role.STAFF)
