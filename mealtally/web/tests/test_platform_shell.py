# SPDX-License-Identifier: AGPL-3.0-only
"""Platform admin pages: Mealtally theme, brand mark and the console layout; fee screens only with platform fees on;
the Django admin only for Django superusers."""

import uuid

import pytest

from mealtally.accounts.models import User
from mealtally.tenancy.context import platform_context
from mealtally.web.tests.conftest import client_for

pytestmark = pytest.mark.django_db


def _platform_admin(*, superuser: bool):
    with platform_context():
        email = f"platform-{uuid.uuid4().hex[:6]}@example.test"
        if superuser:
            return User.objects.create_superuser(email=email, password="Platform-Pass-123")
        user = User.objects.create_user(email=email, password="Platform-Pass-123")
        User.objects.filter(pk=user.pk).update(is_platform_admin=True)
        user.refresh_from_db()
        return user


def test_platform_pages_use_the_console_shell_and_tally_theme(w):
    html = client_for(_platform_admin(superuser=True)).get("/platform/").content.decode()
    assert 'data-theme="tally"' in html
    assert 'data-testid="sidebar"' in html and "brand/icon.svg" in html
    assert 'data-testid="platform-logout"' in html
    assert 'href="/platform/admin/"' in html and 'data-testid="django-admin"' in html  # superuser


def test_django_admin_is_only_offered_to_superusers(w):
    html = client_for(_platform_admin(superuser=False)).get("/platform/").content.decode()
    assert 'data-testid="sidebar"' in html
    assert "/platform/admin/" not in html


def test_fee_screens_hidden_when_platform_fees_are_off(w, settings):
    c = client_for(_platform_admin(superuser=True))
    settings.MEALTALLY_PLATFORM_FEES = True
    on = c.get("/platform/").content.decode()
    assert "Fees (month)" in on and "/platform/plans" in on
    settings.MEALTALLY_PLATFORM_FEES = False
    off = c.get("/platform/").content.decode()
    assert "Fees (month)" not in off and "Fees this month" not in off and "/platform/plans" not in off
    assert c.get("/platform/plans").status_code == 404
