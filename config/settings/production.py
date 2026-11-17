# SPDX-License-Identifier: AGPL-3.0-only
"""Production settings. Plain HTTP by default; HTTPS behaviour follows MEALTALLY_BASE_URL (docs/deploy.md)."""

import logging
from urllib.parse import urlparse

from .base import *  # noqa: F403
from .base import DATABASES
from .base import LOGGING
from .base import MEALTALLY_BASE_URL
from .base import MEALTALLY_TRUST_PROXY
from .base import SPECTACULAR_SETTINGS
from .base import env

SECRET_KEY = env("DJANGO_SECRET_KEY")

# One URL setting drives hosts, CSRF origins, cookie security and HSTS.
_url = urlparse(MEALTALLY_BASE_URL)
if _url.scheme not in ("http", "https") or not _url.hostname:
    raise ValueError("MEALTALLY_BASE_URL must look like http://192.168.1.20:8000 or https://meals.example.com")
HTTPS = _url.scheme == "https"
_origin = f"{_url.scheme}://{_url.netloc}"
ALLOWED_HOSTS = list(
    dict.fromkeys([_url.hostname, "localhost", "127.0.0.1", *env.list("MEALTALLY_EXTRA_HOSTS", default=[])])
)
CSRF_TRUSTED_ORIGINS = [_origin, *env.list("MEALTALLY_EXTRA_ORIGINS", default=[])]

DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

# Mealtally never terminates TLS itself. On http:// (the default) secure cookies, the HTTPS redirect and HSTS are off;
# on https:// they are on. Behind a proxy, MEALTALLY_TRUST_PROXY=true lets it declare the request HTTPS.
if MEALTALLY_TRUST_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = HTTPS
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SESSION_COOKIE_SECURE = HTTPS
CSRF_COOKIE_SECURE = HTTPS
SESSION_COOKIE_NAME = "__Secure-mealtally-session" if HTTPS else "mealtally-session"
CSRF_COOKIE_NAME = "__Secure-mealtally-csrf" if HTTPS else "mealtally-csrf"
SECURE_HSTS_SECONDS = env.int("MEALTALLY_HSTS_SECONDS", default=31536000) if HTTPS else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("MEALTALLY_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env.bool("MEALTALLY_HSTS_PRELOAD", default=False)  # irreversible; opt in deliberately

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_FROM_EMAIL = env("MEALTALLY_FROM_EMAIL", default=f"Mealtally <noreply@{_url.hostname}>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_SUBJECT_PREFIX = env("MEALTALLY_EMAIL_SUBJECT_PREFIX", default="[Mealtally] ")

LOGGING = {
    **LOGGING,
    "handlers": {"console": {"level": "INFO", "class": "logging.StreamHandler", "formatter": "json"}},
    "loggers": {
        "django.db.backends": {"level": "ERROR", "handlers": ["console"], "propagate": False},
        "sentry_sdk": {"level": "ERROR", "handlers": ["console"], "propagate": False},
        "django.security.DisallowedHost": {"level": "ERROR", "handlers": ["console"], "propagate": False},
    },
}

# Optional error reporting (Sentry or a compatible service such as GlitchTip).
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.redis import RedisIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            DjangoIntegration(),
            CeleryIntegration(),
            RedisIntegration(),
        ],
        environment=env("SENTRY_ENVIRONMENT", default="production"),
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0),
        send_default_pii=False,
    )

SPECTACULAR_SETTINGS["SERVERS"] = [{"url": MEALTALLY_BASE_URL}]
