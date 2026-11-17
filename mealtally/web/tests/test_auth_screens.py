# SPDX-License-Identifier: AGPL-3.0-only
"""D03.6 Part A: every sign-in screen uses the split-panel shell in all three themes, CSP-clean, auth unchanged."""

from __future__ import annotations

import re

import pytest

from mealtally.tenancy.context import platform_context
from mealtally.tenancy.models import Tenant
from mealtally.tenancy.models import TenantSettings

pytestmark = pytest.mark.django_db
THEMES = ("masala", "fresh", "tally")


def set_theme(w, theme):
    with platform_context():
        Tenant.objects.filter(pk=w.tenant.pk).update(theme=theme)


@pytest.mark.parametrize("theme", THEMES)
def test_tenant_entry_and_both_logins_use_the_split_panel_in_each_theme(w, client, u, theme):
    set_theme(w, theme)
    with platform_context():
        TenantSettings.objects.filter(tenant_id=w.tenant.pk).update(tagline="Ghar jaisa khana", address="12 Test Road")
    for path in ("/", "/login/customer", "/login/staff"):
        html = client.get(u + path).content.decode()
        assert f'data-theme="{theme}"' in html, path
        assert 'data-testid="auth-visual"' in html and "Powered by Mealtally" in html
        assert "Ghar jaisa khana" in html and "12 Test Road" in html
        assert 'class="sr-only focus:not-sr-only' in html  # skip link
        assert re.search(r"<h1[^>]*>", html) and html.count("<h1") == 1
        assert not re.search(r"\sstyle=", html) and not re.search(
            r"<script(?![^>]*\bsrc=)", html
        )  # CSP: nothing inline
        assert 'data-testid="lang"' in html and html.count("<main") == 1
    entry = client.get(u + "/").content.decode()
    assert entry.count("auth-tile") >= 2 and "I'm a customer" in entry.replace("&#x27;", "'") and "Staff login" in entry
    cust = client.get(u + "/login/customer").content.decode()
    assert (
        "data-pin" in cust
        and 'autocomplete="tel-national"' in cust
        and 'inputmode="numeric"' in cust
        and ">+91<" in cust
    )
    assert "Forgot your PIN? Ask at the counter" in cust and "data-submit-once" in cust
    staff = client.get(u + "/login/staff").content.decode()
    assert (
        'autocomplete="username"' in staff
        and 'autocomplete="current-password"' in staff
        and "/accounts/password/reset/" in staff
    )


def test_platform_login_is_tally_with_no_tenant_branding(w, client):
    html = client.get("/login").content.decode()
    assert 'data-theme="tally"' in html and "Mealtally" in html and "Prepaid meals, simplified." in html
    assert w.tenant.name not in html


def test_errors_show_in_a_danger_alert_and_login_behaviour_is_unchanged(w, client, u):
    r = client.post(u + "/login/staff", {"login": "nobody@example.com", "password": "wrong-password"})
    assert r.status_code == 400 and 'role="alert"' in r.content.decode() and "auth-alert" in r.content.decode()
    r = client.post(u + "/login/customer", {"phone": "9000000000", "pin": "000000"})
    assert r.status_code == 400 and 'role="alert"' in r.content.decode()


def test_tagline_is_editable_in_business_profile(w):
    from mealtally.tenancy import services as tenancy
    from mealtally.tenancy.context import tenant_context

    with tenant_context(w.tenant.pk):
        tenancy.update_settings(actor=w.owner, tagline="Fresh daily")
        assert TenantSettings.objects.get(tenant_id=w.tenant.pk).tagline == "Fresh daily"


def test_reset_pages_and_logout_confirmation_use_the_same_shell(w, client):
    for path in ("/accounts/password/reset/", "/accounts/password/reset/done/", "/accounts/logout/"):
        r = client.get(path)
        assert r.status_code in (200, 302), path
        if r.status_code == 200:
            html = r.content.decode()
            assert 'data-testid="auth-visual"' in html and 'data-theme="tally"' in html, path
    html = client.get("/accounts/password/reset/").content.decode()
    assert 'name="email"' in html and 'autocomplete="email"' in html


def test_lockout_copy_and_forced_password_change_in_the_shell(w, client, u):
    from mealtally.web.copy import FRIENDLY

    assert "ask the owner" in str(FRIENDLY["ACCOUNT_LOCKED"]) and "15 minutes" in str(FRIENDLY["ACCOUNT_LOCKED"])
    from django.test import Client

    from mealtally.accounts.models import User
    from mealtally.testing import PASSWORD

    with platform_context():
        User.objects.filter(pk=w.owner.user.pk).update(must_change_password=True)
    c = Client()
    c.post(u + "/login/staff", {"login": w.owner.user.email, "password": PASSWORD})
    r = c.get(u + "/password", follow=True)
    html = r.content.decode()
    assert 'data-testid="auth-visual"' in html and "choose your own password" in html
