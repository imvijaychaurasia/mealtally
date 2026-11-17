# SPDX-License-Identifier: AGPL-3.0-only
"""`make demo`: development only, two restaurants, fresh logins every run, nothing fixed in the code."""

import io
import re

import pytest
from django.core.management import CommandError
from django.core.management import call_command

from mealtally.accounts.models import User
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.models import Tenant

pytestmark = pytest.mark.django_db(transaction=True)


def _works(login, password):
    with platform_context():
        return User.objects.get(email=login).check_password(password)


def _run():
    out = io.StringIO()
    call_command("mealtally_demo", stdout=out)
    return out.getvalue()


def test_refuses_outside_development(settings):
    settings.DEBUG = False
    settings.MEALTALLY_ENV = "production"
    with pytest.raises(CommandError, match="only runs in development"):
        _run()


def test_creates_two_restaurants_and_prints_working_logins(settings):
    settings.MEALTALLY_ENV = "development"
    first = _run()
    assert first.count("## ") == 2
    assert "PLATFORM ADMIN  login=admin@example.com  password=" in first
    with platform_context():
        demos = {t.slug: t for t in Tenant.objects.filter(slug__in=["demo-tiffin", "demo-fresh"])}
    assert set(demos) == {"demo-tiffin", "demo-fresh"}
    assert all(t.has_demo_dataset and not t.is_test for t in demos.values())
    owner = re.search(r"Owner\s+login=(\S+)  password=(\S+)", first)
    assert owner and _works(owner[1], owner[2])
    assert len(re.findall(r"^CUSTOMER .* pin=\d+$", first, re.M)) == 16  # noqa: PLR2004

    # a second run refreshes the data and rotates every login: the old password stops working
    second = _run()
    assert "the account you created" in second  # the admin from the first run is kept, not reset
    new_owner = re.search(r"Owner\s+login=(\S+)  password=(\S+)", second)
    assert new_owner[1] == owner[1] and new_owner[2] != owner[2]
    assert not _works(owner[1], owner[2])
    assert _works(new_owner[1], new_owner[2])
