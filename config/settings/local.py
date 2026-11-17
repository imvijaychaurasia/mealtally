# SPDX-License-Identifier: AGPL-3.0-only
from .base import *  # noqa: F403
from .base import INSTALLED_APPS
from .base import SPECTACULAR_SETTINGS
from .base import env

DEBUG = True
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="local-dev-only-insecure-key-0Qm9Xf3lB7vA2cR8tHn5Ke1Wy6ZpJd4U",
)
ALLOWED_HOSTS = ["localhost", "0.0.0.0", "127.0.0.1", "django"]  # noqa: S104

INSTALLED_APPS = [*INSTALLED_APPS, "django_extensions"]
EMAIL_BACKEND = env("DJANGO_EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="mailpit")
EMAIL_PORT = 1025

SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"] = ["rest_framework.permissions.AllowAny"]
