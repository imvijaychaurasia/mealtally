# SPDX-License-Identifier: AGPL-3.0-only
"""Test settings.

Tests create their database with the *superuser* credentials from POSTGRES_*
and then switch every connection to the non-superuser ``mealtally_app`` role (see
``mealtally/conftest.py``) so that row-level security is really enforced.
"""

from .base import *  # noqa: F403
from .base import DATABASES
from .base import SPECTACULAR_SETTINGS
from .base import env

SECRET_KEY = env("DJANGO_SECRET_KEY", default="test-secret-key-not-for-production-0123456789abcdef")
ALLOWED_HOSTS = ["testserver", "localhost"]
DEBUG = False
TEST_RUNNER = "django.test.runner.DiscoverRunner"

# Always build the DB from the superuser POSTGRES_* variables.
DATABASES["default"] = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": env.str("POSTGRES_DB", default="mealtally"),
    "USER": env.str("POSTGRES_USER"),
    "PASSWORD": env.str("POSTGRES_PASSWORD"),
    "HOST": env.str("POSTGRES_HOST", default="postgres"),
    "PORT": env.str("POSTGRES_PORT", default="5432"),
    "ATOMIC_REQUESTS": True,
}
MEALTALLY_TEST_APP_ROLE = env.str("MEALTALLY_TEST_APP_ROLE", default="mealtally_app_test")
MEALTALLY_TEST_APP_PASSWORD = env.str("MEALTALLY_TEST_APP_PASSWORD", default="mealtally_app_test_password")

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"] = ["mealtally.api.permissions.IsPlatformAdmin"]
MEDIA_URL = "http://media.testserver/"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Most tests exercise the operator setup (many restaurants, fees, the marketing site); the defaults of a self-hosted
# single restaurant are covered explicitly in mealtally/web/tests/test_modes.py.
MEALTALLY_MODE = "multi"
MEALTALLY_PLATFORM_FEES = True
MEALTALLY_MARKETING_SITE = True
MEALTALLY_LEGAL_PAGES = True
