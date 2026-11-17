from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import pytest
from django.core import signing

from mealtally.ledger.models import MealLedgerEntry
from mealtally.testing import World
from mealtally.testing import make_customer

from .conftest import login_as

pytestmark = pytest.mark.django_db


def k() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def cust_client(w):
    return login_as(w.customer.user)


def test_me_endpoints(w, base, cust_client, owner_client):
    owner_client.post(f"{base}/redeem", {"customer": str(w.customer.public_id), "idempotency_key": k()}, format="json")
    me = cust_client.get(f"{base}/me").json()
    assert me["meals_remaining"] == 29 and me["meals_consumed"] == 1
    ledger = cust_client.get(f"{base}/me/ledger").json()
    assert ledger["count"] == 2 and [e["entry_type"] for e in ledger["results"]] == ["REDEEM", "ISSUE"]  # newest first
    pays = cust_client.get(f"{base}/me/payments").json()
    assert pays["count"] == 1 and pays["results"][0]["amount_minor"] == 150000
    assert cust_client.get(f"{base}/me/ledger", {"page_size": 1}).json()["next"]
    patched = cust_client.patch(f"{base}/me", {"full_name": "New Name"}, format="json")
    assert patched.status_code == 200 and patched.json()["customer"]["full_name"] == "New Name"
    other = cust_client.patch(f"{base}/me", {"phone": "+919999999999", "full_name": "Still"}, format="json")
    assert other.json()["customer"]["phone"] == w.customer.phone_e164  # name only


def test_customers_cannot_see_each_others_history(w, base):
    other, _ = make_customer(w.tenant, w.owner, name="Other")
    me = login_as(other.user).get(f"{base}/me").json()  # `me` works even with a temporary PIN
    assert me["active_pass"] is None and me["meals_remaining"] == 0
    blocked = login_as(other.user).get(f"{base}/me/ledger")  # everything else needs the PIN change first (D02.1 Q2)
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "CREDENTIAL_CHANGE_REQUIRED"
    with w.ctx():
        other.must_change_pin = False
        other.save()
    assert login_as(other.user).get(f"{base}/me/ledger").json()["count"] == 0


def test_qr_token_svg_and_redeem_via_qr(w, base, cust_client, staff_client):
    tok = cust_client.get(f"{base}/me/qr-token").json()
    assert tok["expires_in"] == 90 and tok["token"]
    svg = cust_client.get(f"{base}/me/qr.svg")
    assert (
        svg.status_code == 200 and svg["Content-Type"] == "image/svg+xml" and svg.content.lstrip().startswith(b"<svg")
    )
    assert svg["Cache-Control"] == "no-store"

    key = k()
    ok = staff_client.post(f"{base}/redeem/qr", {"token": tok["token"], "idempotency_key": key}, format="json")
    assert ok.status_code == 201 and ok.json()["meals_remaining"] == 29
    with w.ctx():
        assert MealLedgerEntry.objects.get(entry_type="REDEEM").source == "QR_SCAN"
    # same request retried (network blip): allowed, replayed
    retry = staff_client.post(f"{base}/redeem/qr", {"token": tok["token"], "idempotency_key": key}, format="json")
    assert retry.status_code == 200 and retry.json()["replayed"] is True
    # token reuse with a NEW idempotency key: single-use violated
    reuse = staff_client.post(
        f"{base}/redeem/qr", {"token": tok["token"], "idempotency_key": k(), "confirm_additional": True}, format="json"
    )
    assert reuse.status_code == 409 and reuse.json()["error"]["code"] == "QR_ALREADY_USED"


def test_qr_token_payload_and_expiry(w, base, cust_client, staff_client, monkeypatch):
    data = cust_client.get(f"{base}/me/qr-token").json()
    assert data["format"] == "code" and len(data["token"]) == 12 and data["expires_in"] == 90
    token = data["signed_token"]  # the signed form is still accepted by redeem/qr
    payload = signing.TimestampSigner(salt="mealtally.qr.v1").unsign_object(token, max_age=90)
    assert set(payload) == {"tid", "cid", "jti"} and payload["cid"] == str(w.customer.public_id)
    assert payload["tid"] == str(w.tenant.public_id)
    real = time.time
    monkeypatch.setattr(signing, "time", SimpleNamespace(time=lambda: real() + 91))
    expired = staff_client.post(f"{base}/redeem/qr", {"token": token, "idempotency_key": k()}, format="json")
    assert expired.status_code == 400 and expired.json()["error"]["code"] == "QR_EXPIRED"


def test_qr_tampered_wrong_salt_and_wrong_tenant_are_invalid(w, base, cust_client, staff_client):
    token = cust_client.get(f"{base}/me/qr-token").json()["signed_token"]
    for bad in (
        token[:-2] + "xx",
        "garbage",
        signing.TimestampSigner(salt="other").sign_object({"tid": "x", "cid": "y", "jti": "z"}),
    ):
        resp = staff_client.post(f"{base}/redeem/qr", {"token": bad, "idempotency_key": k()}, format="json")
        assert resp.status_code == 400 and resp.json()["error"]["code"] == "QR_INVALID", bad
    # a perfectly valid token minted for tenant A cannot be redeemed at tenant B
    b = World(slug="qr-other")
    resp = login_as(b.staff.user).post(
        f"/api/v1/t/{b.tenant.slug}/redeem/qr", {"token": token, "idempotency_key": k()}, format="json"
    )
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "QR_INVALID"
    with b.ctx():
        assert MealLedgerEntry.objects.filter(entry_type="REDEEM").count() == 0


def test_staff_cannot_mint_qr_without_a_customer_profile(w, base, staff_client):
    assert staff_client.get(f"{base}/me/qr-token").status_code == 404


def test_redeem_rate_limits_per_user_and_per_tenant(w, base, monkeypatch):
    from mealtally.api.throttles import RedeemTenantThrottle
    from mealtally.api.throttles import RedeemUserThrottle

    monkeypatch.setattr(RedeemUserThrottle, "THROTTLE_RATES", {"redeem_user": "2/min"})
    monkeypatch.setattr(RedeemTenantThrottle, "THROTTLE_RATES", {"redeem_tenant": "4/min"})
    s1, s2 = login_as(w.staff.user), login_as(w.manager.user)
    body = lambda: {"customer": str(w.customer.public_id), "idempotency_key": k(), "confirm_additional": True}  # noqa: E731
    assert [s1.post(f"{base}/redeem", body(), format="json").status_code for _ in range(3)] == [201, 201, 429]
    assert (
        s2.post(f"{base}/redeem", body(), format="json").status_code == 201
    )  # other user: 4th hit on the tenant (rejected attempts count too)
    assert s2.post(f"{base}/redeem", body(), format="json").status_code == 429  # tenant ceiling reached
    assert s1.get(f"{base}/customers").status_code == 200  # non-redeem endpoints are not throttled
