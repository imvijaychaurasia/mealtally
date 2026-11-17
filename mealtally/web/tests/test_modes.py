# SPDX-License-Identifier: AGPL-3.0-only
"""Deployment mode and operator flags with the defaults a self-hosted restaurant gets (single mode, everything off)."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from mealtally.accounts.models import Membership
from mealtally.accounts.models import User
from mealtally.billing.models import PlatformFeeEntry
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.models import PlatformSettings
from mealtally.tenancy.models import Tenant
from mealtally.testing import World
from mealtally.web.tests.conftest import client_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def defaults(settings):
    settings.MEALTALLY_MODE = "single"
    settings.MEALTALLY_PLATFORM_FEES = False
    settings.MEALTALLY_MARKETING_SITE = False
    settings.MEALTALLY_DEMO_DATASET = False
    settings.MEALTALLY_LEGAL_PAGES = False
    return settings


def test_single_mode_root_goes_to_the_restaurant(defaults, client):
    w = World(slug="only-one")
    resp = client.get("/")
    assert resp.status_code == 302 and resp["Location"] == f"/t/{w.tenant.slug}/"


def test_single_mode_without_a_restaurant_explains_make_init(defaults, client):
    resp = client.get("/")
    assert resp.status_code == 503 and "make init" in resp.content.decode()


def test_multi_mode_root_is_the_restaurant_finder(defaults, client):
    defaults.MEALTALLY_MODE = "multi"
    html = client.get("/").content.decode()
    assert "Find your restaurant" in html and 'name="code"' in html
    assert client.post("/go", {"code": ""}).status_code == 400


def test_marketing_site_is_off_by_default(defaults, client):
    assert client.post("/demo-request", {}).status_code == 404
    assert client.get("/sitemap.xml").status_code == 404
    assert client.get("/robots.txt").content.decode() == "User-agent: *\nDisallow: /\n"
    defaults.MEALTALLY_MARKETING_SITE = True
    assert 'id="pricing"' in client.get("/").content.decode()


def test_platform_fees_off_hides_the_screens_and_writes_no_fee_entries(defaults):
    w = World(slug="nofees")
    owner = client_for(w.owner.user)
    u = f"/t/{w.tenant.slug}"
    assert owner.get(u + "/admin/reports/fees").status_code == 404
    assert "report-fees" not in owner.get(u + "/admin/reports").content.decode()
    with w.ctx():
        assert PlatformFeeEntry.objects.count() == 0  # the World's pass was sold with fees off
    defaults.MEALTALLY_PLATFORM_FEES = True
    assert owner.get(u + "/admin/reports/fees").status_code == 200


def test_onboarding_is_multi_mode_only(defaults):
    with platform_context():
        admin = User.objects.create_superuser(email="modes-root@example.com", password="Sup3r-Secret-Pw!")
    c = client_for(admin)
    assert c.get("/platform/onboard/").status_code == 404
    defaults.MEALTALLY_MODE = "multi"
    assert c.get("/platform/onboard/").status_code == 200


LEGAL = {
    "operator_name": "Example Meals Ltd",
    "operator_address": "1 Example Street, Exampletown",
    "contact_email": "hello@example.com",
    "privacy_contact_email": "privacy@example.com",
    "data_retention": "12 months after your last pass",
    "governing_law": "the laws of Exampleland",
}


def test_legal_pages_404_until_switched_on_and_complete(defaults, client):
    assert client.get("/privacy").status_code == 404
    defaults.MEALTALLY_LEGAL_PAGES = True
    assert client.get("/privacy").status_code == 404  # on, but the operator hasn't filled the fields
    PlatformSettings(**{**LEGAL, "data_retention": ""}).save()
    assert client.get("/terms").status_code == 404  # still one required field missing
    PlatformSettings(**LEGAL).save()
    privacy = client.get("/privacy").content.decode()
    terms = client.get("/terms").content.decode()
    assert "Example Meals Ltd" in privacy and "12 months after your last pass" in privacy
    assert "the laws of Exampleland" in terms and "SAMPLE TEMPLATE" not in terms
    assert "Contact us" not in privacy + terms and "{{" not in privacy + terms


def test_legal_values_are_escaped(defaults, client):
    defaults.MEALTALLY_LEGAL_PAGES = True
    PlatformSettings(**{**LEGAL, "operator_name": "<script>x()</script>"}).save()
    html = client.get("/privacy").content.decode()
    assert "<script>x()</script>" not in html and "&lt;script&gt;" in html


def test_mealtally_init_creates_the_admin_and_the_restaurant_once(defaults, capsys):
    call_command("mealtally_init", "--email", "owner@example.com", "--restaurant", "Corner Canteen")
    out = capsys.readouterr().out
    assert "owner@example.com" in out and "shown once" in out and "Corner Canteen" in out
    with platform_context():
        admin = User.objects.get(email="owner@example.com")
        tenant = Tenant.objects.get(slug="corner-canteen")
        assert admin.is_platform_admin and admin.must_change_password
        assert Membership.objects.filter(user=admin, tenant=tenant, role="OWNER").exists()
    call_command("mealtally_init", "--email", "owner@example.com")  # again: nothing new
    with platform_context():
        assert Tenant.objects.count() == 1 and User.objects.filter(email="owner@example.com").count() == 1
    assert "already exists" in capsys.readouterr().out


def test_mealtally_init_needs_an_email(defaults, monkeypatch):
    from django.core.management.base import CommandError

    monkeypatch.delenv("MEALTALLY_ADMIN_EMAIL", raising=False)
    with pytest.raises(CommandError):
        call_command("mealtally_init")


def test_plain_http_notice_for_admins_on_a_lan_address_until_dismissed(defaults):
    defaults.MEALTALLY_BASE_URL = "http://192.168.1.20:8000"
    w = World(slug="lan")
    owner, staff = client_for(w.owner.user), client_for(w.staff.user)
    u = f"/t/{w.tenant.slug}"
    page = owner.get(u + "/admin/").content.decode()
    assert 'data-testid="http-notice"' in page and "mkcert" in page
    assert 'data-testid="http-notice"' not in staff.get(u + "/staff/").content.decode()
    resp = owner.post("/dismiss-http-notice", {"next": u + "/admin/"})
    assert resp.status_code == 302 and resp["Location"] == u + "/admin/"
    assert 'data-testid="http-notice"' not in owner.get(u + "/admin/").content.decode()
    assert owner.post("/dismiss-http-notice", {"next": "//evil.example.com"})["Location"] == "/"
    for url in ("http://localhost:8000", "https://meals.example.com"):
        defaults.MEALTALLY_BASE_URL = url
        fresh = client_for(w.owner.user)
        assert 'data-testid="http-notice"' not in fresh.get(u + "/admin/").content.decode()


def _production_settings(base_url: str, trust_proxy: str = "false", **extra) -> dict:
    import json
    import os
    import subprocess
    import sys

    env = {
        **os.environ,
        "DJANGO_SECRET_KEY": "x" * 50,
        "MEALTALLY_BASE_URL": base_url,
        "MEALTALLY_TRUST_PROXY": trust_proxy,
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "MEALTALLY_DEFAULT_COUNTRY": "GB",
        "MEALTALLY_DEFAULT_CURRENCY": "GBP",
        "MEALTALLY_DEFAULT_TIMEZONE": "Europe/London",
        **extra,
    }
    code = (
        "import json, config.settings.production as s;"
        "print(json.dumps({k: getattr(s, k, None) for k in ('ALLOWED_HOSTS', 'CSRF_TRUSTED_ORIGINS', "
        "'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE', 'SECURE_SSL_REDIRECT', 'SECURE_HSTS_SECONDS', "
        "'SECURE_PROXY_SSL_HEADER', 'SESSION_COOKIE_NAME')}))"
    )
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)  # noqa: S603
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_production_settings_follow_the_base_url():
    plain = _production_settings("http://192.168.1.20:8000")
    assert plain["ALLOWED_HOSTS"][0] == "192.168.1.20" and plain["CSRF_TRUSTED_ORIGINS"] == ["http://192.168.1.20:8000"]
    assert not plain["SESSION_COOKIE_SECURE"] and not plain["SECURE_SSL_REDIRECT"] and plain["SECURE_HSTS_SECONDS"] == 0
    assert plain["SECURE_PROXY_SSL_HEADER"] is None and plain["SESSION_COOKIE_NAME"] == "mealtally-session"
    tls = _production_settings("https://meals.example.com", trust_proxy="true")
    assert tls["ALLOWED_HOSTS"][0] == "meals.example.com" and tls["CSRF_TRUSTED_ORIGINS"] == [
        "https://meals.example.com"
    ]
    assert tls["SESSION_COOKIE_SECURE"] and tls["CSRF_COOKIE_SECURE"] and tls["SECURE_SSL_REDIRECT"]
    assert tls["SECURE_HSTS_SECONDS"] == 31536000 and tls["SECURE_PROXY_SSL_HEADER"] == [
        "HTTP_X_FORWARDED_PROTO",
        "https",
    ]
    assert tls["SESSION_COOKIE_NAME"] == "__Secure-mealtally-session"


def test_start_is_refused_without_country_currency_and_timezone(settings):
    """`migrate` (run before the web server starts) fails with a clear message; image builds are not affected."""
    from mealtally.tenancy.checks import locale_defaults

    assert locale_defaults() == []
    settings.MEALTALLY_DEFAULT_COUNTRY = ""
    settings.MEALTALLY_DEFAULT_TIMEZONE = "Mars/Base"
    errors = locale_defaults()
    assert [e.id for e in errors] == ["mealtally.E001", "mealtally.E003"]
    assert all("make init asks for it" in e.hint for e in errors)


@pytest.mark.django_db
def test_preview_modules_are_off_for_new_restaurants(settings):
    from mealtally.tenancy.models import Tenant

    settings.MEALTALLY_DEMO_DATASET = False
    assert Tenant(slug="a", name="A").has_demo_dataset is False
    settings.MEALTALLY_DEMO_DATASET = True
    assert Tenant(slug="b", name="B").has_demo_dataset is True
