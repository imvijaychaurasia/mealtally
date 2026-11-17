"""Pytest wiring.

* pytest-django builds the test database with the *superuser* from POSTGRES_* ...
* ... then (``django_db_setup`` below) every connection is switched to a plain
  non-superuser role, exactly like production, so row-level security is really enforced.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import time_machine
from django.conf import settings
from django.core.cache import cache
from django.db import connections

from mealtally.tenancy.db import ensure_login_role
from mealtally.tenancy.db import grant_app_privileges
from mealtally.tenancy.rls import APPEND_ONLY_TABLES

_ADMIN: dict = {}

# D03.9 §D1: every test runs on a frozen clock (the 14 Nov Hindi-toggle failure only happened after 11:00 IST).
# Monday 16 Nov 2026, 10:00 IST; the clock ticks from there, so durations still work. Tests that need another moment
# nest their own ``time_machine.travel``; ``@pytest.mark.real_clock`` opts out (none needs it today).
FROZEN_AT = datetime(2026, 11, 16, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture(autouse=True)
def _frozen_clock(request):
    if request.node.get_closest_marker("real_clock"):
        yield
        return
    with time_machine.travel(FROZEN_AT, tick=True):
        yield


@pytest.fixture
def admin_connection(django_db_setup):
    """A superuser connection to the test database (for tests that must alter triggers)."""
    import psycopg  # noqa: PLC0415

    with psycopg.connect(**_ADMIN, autocommit=True) as c:
        yield c


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):  # noqa: F811
    with django_db_blocker.unblock():
        conn = connections["default"]
        admin_user, admin_password = conn.settings_dict["USER"], conn.settings_dict["PASSWORD"]
        ensure_login_role(settings.MEALTALLY_TEST_APP_ROLE, settings.MEALTALLY_TEST_APP_PASSWORD)
        # Test DB only: let the app role TRUNCATE (TransactionTestCase flush) and keep UPDATE/DELETE on
        # the append-only tables so the *triggers* (not missing GRANTs) are what the tests exercise.
        grant_app_privileges(settings.MEALTALLY_TEST_APP_ROLE, harden_append_only=False, allow_truncate=True)
        # TransactionTestCase flushes with TRUNCATE; the guard triggers are switched off for the suite
        # (test_truncate_guard switches them on again explicitly). Production keeps them on.
        with conn.cursor() as cur:
            for table in APPEND_ONLY_TABLES:
                cur.execute(f'ALTER TABLE "{table}" DISABLE TRIGGER "{table}_no_truncate"')
        _ADMIN.update(
            user=admin_user,
            password=admin_password,
            dbname=conn.settings_dict["NAME"],
            host=conn.settings_dict["HOST"],
            port=conn.settings_dict["PORT"],
        )
        conn.close()
        conn.settings_dict["USER"] = settings.MEALTALLY_TEST_APP_ROLE
        conn.settings_dict["PASSWORD"] = settings.MEALTALLY_TEST_APP_PASSWORD
    yield
    with django_db_blocker.unblock():
        conn.close()
        conn.settings_dict["USER"], conn.settings_dict["PASSWORD"] = admin_user, admin_password


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _media_storage(settings, tmpdir) -> None:
    settings.MEDIA_ROOT = tmpdir.strpath
