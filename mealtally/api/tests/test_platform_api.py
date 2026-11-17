from __future__ import annotations

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from mealtally.accounts.models import User
from mealtally.tenancy.context import platform_context

from .conftest import login_as

pytestmark = pytest.mark.django_db


@pytest.fixture
def root(db):
    with platform_context():
        return User.objects.create_superuser(email="root@example.test", password="Sup3r-Secret-Pw!")


def test_platform_endpoints_require_platform_admin(w, root):
    assert APIClient().get("/api/v1/platform/tenants").status_code == 401
    assert login_as(w.owner.user).get("/api/v1/platform/tenants").status_code == 403
    resp = login_as(root).get("/api/v1/platform/tenants")
    assert resp.status_code == 200 and "pilot" in [t["slug"] for t in resp.json()["results"]]


def test_platform_admin_creates_suspends_and_sets_fee_policy(root):
    c = login_as(root)
    created = c.post("/api/v1/platform/tenants", {"name": "Second Tiffin", "slug": "second-tiffin"}, format="json")
    assert created.status_code == 201 and created.json()["timezone"] == "Asia/Kolkata"
    assert (
        c.post("/api/v1/platform/tenants", {"name": "Dup", "slug": "second-tiffin"}, format="json").status_code == 400
    )
    assert c.post("/api/v1/platform/tenants", {"name": "Bad", "slug": "Bad Slug!"}, format="json").status_code == 400
    assert (
        c.post(
            "/api/v1/platform/tenants", {"name": "Tz", "slug": "tz-bad", "timezone": "Mars/Base"}, format="json"
        ).status_code
        == 400
    )

    fee = c.post(
        "/api/v1/platform/tenants/second-tiffin/fee-policy",
        {"platform_pct": "9.50", "gateway_pct": "2.00"},
        format="json",
    )
    assert fee.status_code == 201 and fee.json()["platform_pct"] == "9.50"
    assert (
        c.post(
            "/api/v1/platform/tenants/second-tiffin/fee-policy",
            {"platform_pct": "120", "gateway_pct": "1"},
            format="json",
        ).status_code
        == 400
    )

    sus = c.post("/api/v1/platform/tenants/second-tiffin/suspend", {"reason": "non-payment"}, format="json")
    assert sus.status_code == 200 and sus.json()["status"] == "SUSPENDED"
    assert c.post("/api/v1/platform/tenants/second-tiffin/activate", {}, format="json").json()["status"] == "ACTIVE"
    assert c.post("/api/v1/platform/tenants/nope/suspend", {}, format="json").status_code == 404


def test_healthz_is_public_and_checks_db_and_valkey(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200 and resp.json() == {"status": "ok", "database": "ok", "valkey": "ok"}


def test_healthz_reports_503_when_valkey_is_down(client, monkeypatch):
    def boom(_alias):
        raise ConnectionError

    monkeypatch.setattr("mealtally.api.views.get_redis_connection", boom)
    resp = client.get("/healthz")
    assert resp.status_code == 503 and resp.json()["valkey"] == "error"


def test_openapi_docs_are_restricted_to_platform_admins(w, root):
    assert APIClient().get("/api/v1/schema/").status_code in (401, 403)
    assert login_as(w.owner.user).get("/api/v1/schema/").status_code == 403
    resp = login_as(root).get("/api/v1/schema/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "/api/v1/t/{tenant_slug}/redeem" in body and "/api/v1/platform/tenants" in body
    assert login_as(root).get("/api/v1/docs/").status_code == 200


def test_create_platform_admin_command(capsys):
    call_command("create_platform_admin", "--email", "boss@example.test")
    assert "CREDENTIALS (shown once)" in capsys.readouterr().out
    call_command("create_platform_admin", "--email", "boss@example.test")
    assert "already exists" in capsys.readouterr().out
    call_command("create_platform_admin", "--email", "boss@example.test", "--reset-password")
    assert "CREDENTIALS" in capsys.readouterr().out
    with platform_context():
        assert User.objects.get(email="boss@example.test").is_platform_admin


def test_logging_json_formatter():
    import json
    import logging

    from mealtally.common.logging import JsonFormatter

    rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "hello %s", ("w",), None)
    rec.tenant_id = 7
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "hello w" and out["level"] == "ERROR" and out["tenant_id"] == 7


def test_client_ip_trusts_forwarded_for_only_from_trusted_proxy(rf, settings):
    from mealtally.common.net import client_ip

    settings.MEALTALLY_TRUST_PROXY = False  # the default: X-Forwarded-For is ignored
    assert client_ip(rf.get("/", REMOTE_ADDR="172.18.0.5", HTTP_X_FORWARDED_FOR="203.0.113.9")) == "172.18.0.5"
    settings.MEALTALLY_TRUST_PROXY = True
    trusted = rf.get("/", REMOTE_ADDR="172.18.0.5", HTTP_X_FORWARDED_FOR="203.0.113.9, 198.51.100.7")
    assert client_ip(trusted) == "198.51.100.7"
    spoof = rf.get("/", REMOTE_ADDR="8.8.8.8", HTTP_X_FORWARDED_FOR="1.2.3.4")
    assert client_ip(spoof) == "8.8.8.8"
    assert client_ip(rf.get("/", REMOTE_ADDR="172.18.0.5", HTTP_X_FORWARDED_FOR="not-an-ip")) == "172.18.0.5"
