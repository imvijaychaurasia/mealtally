# SPDX-License-Identifier: AGPL-3.0-only
"""Base settings for Mealtally. Everything configurable comes from the environment; see docs/configuration.md."""

import os
import ssl
from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab
from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve(strict=True).parent.parent.parent
# mealtally/
APPS_DIR = BASE_DIR / "mealtally"
env = environ.Env()

READ_DOT_ENV_FILE = env.bool("DJANGO_READ_DOT_ENV_FILE", default=False)
if READ_DOT_ENV_FILE:
    # OS environment variables take precedence over variables from .env
    env.read_env(str(BASE_DIR / ".env"))

# GENERAL
# ------------------------------------------------------------------------------
DEBUG = env.bool("DJANGO_DEBUG", False)
TIME_ZONE = "UTC"
LANGUAGE_CODE = env.str("MEALTALLY_DEFAULT_LANGUAGE", default="en")
# Each language by its own name. A language is shown as "Beta" in the picker until a native speaker has reviewed
# it (LANGUAGE_REVIEW). Hindi is fully translated but not yet reviewed; the others are machine-drafted core sets
# (fuzzy in the .po files). See TRANSLATING.md and REVIEW-hi.md.
LANGUAGES = [
    ("en", "English"),
    ("hi", "हिन्दी"),
    ("mr", "मराठी"),
    ("ta", "தமிழ்"),
    ("te", "తెలుగు"),
    ("bn", "বাংলা"),
    ("gu", "ગુજરાતી"),
    ("kn", "ಕನ್ನಡ"),
    ("es", "Español"),
    ("fr", "Français"),
    ("pt-br", "Português (Brasil)"),
    ("ar", "العربية"),
    ("id", "Bahasa Indonesia"),
]
# code -> reviewed by a native speaker? English is the source language.
LANGUAGE_REVIEW = {code: code == "en" for code, _name in LANGUAGES}
MEALTALLY_BETA_LANGUAGES = frozenset(code for code, reviewed in LANGUAGE_REVIEW.items() if not reviewed)
LANGUAGE_COOKIE_NAME = "mealtally-language"
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_I18N = True
WHATSAPP_SUPPORT_NUMBER = env("MEALTALLY_WHATSAPP_SUPPORT_NUMBER", default="")  # blank = link hidden
USE_TZ = True

# DATABASES
# ------------------------------------------------------------------------------
# The application connects as a NON-superuser role (`mealtally_app`) so that
# Postgres row-level security is enforced. Migrations / provisioning commands
# run as the table-owner role (`mealtally_owner`, also non-superuser, FORCE RLS
# applies to it) with an explicit platform context -- see docs/architecture.md.
# DATABASE_URL / DATABASE_OWNER_URL override the role-based defaults (for a managed database, for example).
_OWNER_MODE = env.bool("MEALTALLY_DB_OWNER_MODE", default=False)
if _OWNER_MODE and os.getenv("DATABASE_OWNER_URL"):
    DATABASES = {"default": env.db("DATABASE_OWNER_URL")}
elif not _OWNER_MODE and os.getenv("DATABASE_URL"):
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env.str("POSTGRES_DB", default="mealtally"),
            "USER": "mealtally_owner" if _OWNER_MODE else "mealtally_app",
            "PASSWORD": env.str(
                "MEALTALLY_DB_OWNER_PASSWORD" if _OWNER_MODE else "MEALTALLY_DB_APP_PASSWORD", default=""
            ),
            "HOST": env.str("POSTGRES_HOST", default="postgres"),
            "PORT": env.str("POSTGRES_PORT", default="5432"),
        },
    }
if _OWNER_MODE:
    DATABASES["default"].setdefault("OPTIONS", {})["options"] = "-c app.platform=on"

# One transaction per request: required so `SET LOCAL` tenant context is
# transaction-scoped and can never leak across pooled connections.
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# URLS
# ------------------------------------------------------------------------------
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# APPS
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "mealtally.accounts.admin_config.PlatformAdminConfig",  # replaces django.contrib.admin
]
THIRD_PARTY_APPS = [
    "allauth",
    "allauth.account",
    "axes",
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
    "drf_spectacular_sidecar",
]
LOCAL_APPS = [
    "mealtally.tenancy",
    "mealtally.accounts",
    "mealtally.plans",
    "mealtally.customers",
    "mealtally.billing",
    "mealtally.passes",
    "mealtally.ledger",
    "mealtally.audit",
    "mealtally.api",
    "mealtally.web",
    "mealtally.reports",
    "mealtally.preview",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# AUTHENTICATION
# ------------------------------------------------------------------------------
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",  # must be first
    "mealtally.accounts.backends.CustomerPinBackend",
    "mealtally.accounts.backends.IdentifierPasswordBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "/platform/admin/"

# PASSWORDS
# ------------------------------------------------------------------------------
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# MIDDLEWARE
# ------------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "mealtally.web.middleware.ScopedCSPMiddleware",  # must sit ABOVE the CSP middleware to see its header
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "mealtally.web.middleware.PermissionsPolicyMiddleware",
    "mealtally.web.middleware.CanonicalSlashMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "mealtally.audit.middleware.RequestMetaMiddleware",
]

# STATIC / MEDIA
# ------------------------------------------------------------------------------
STATIC_ROOT = str(BASE_DIR / "staticfiles")
STATIC_URL = "/static/"
# assets/brand (logo, icons) is served as /static/brand/: one copy of every brand file
STATICFILES_DIRS = [str(APPS_DIR / "static"), ("brand", str(BASE_DIR / "assets" / "brand"))]
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]
MEDIA_ROOT = str(APPS_DIR / "media")
MEDIA_URL = "/media/"

# TEMPLATES
# ------------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(APPS_DIR / "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "builtins": ["mealtally.web.templatetags.mealtally_extras", "mealtally.preview.templatetags.pv"],
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",  # LANGUAGE_CODE: <html lang> and the EN/हिन्दी toggle
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "mealtally.web.context.web",
            ],
        },
    },
]

CSRF_FAILURE_VIEW = "mealtally.web.errors.csrf_failure"

# SECURITY
# ------------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # SPA/HTMX clients read the token cookie
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
# Django 6 built-in Content-Security-Policy.
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF],
    "style-src": [
        CSP.SELF
    ],  # strict everywhere; admin & docs get a scoped relaxation (mealtally.web.middleware.ScopedCSPMiddleware)
    "img-src": [CSP.SELF, "data:"],
    "font-src": [CSP.SELF],
    "connect-src": [CSP.SELF],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
}
# Peers allowed to supply X-Forwarded-For, honoured only when MEALTALLY_TRUST_PROXY=true.
MEALTALLY_TRUSTED_PROXY_CIDRS = env.list(
    "MEALTALLY_TRUSTED_PROXY_CIDRS",
    default=["127.0.0.1/32", "172.16.0.0/12", "10.0.0.0/8", "192.168.0.0/16"],
)

# EMAIL
# ------------------------------------------------------------------------------
EMAIL_BACKEND = env("DJANGO_EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_TIMEOUT = 5

# ADMIN
# ------------------------------------------------------------------------------
# The Django admin is the PLATFORM admin (platform-wide, cross-tenant).
ADMIN_URL = "platform/admin/"
ADMINS = [a for a in [env("MEALTALLY_ADMIN_EMAIL", default="")] if a]
MANAGERS = ADMINS

# CACHE / VALKEY
# ------------------------------------------------------------------------------
# Valkey speaks the Redis protocol; the setting keeps its historical name.
REDIS_URL = env("REDIS_URL", default="redis://valkey:6379/0")
REDIS_SSL = REDIS_URL.startswith("rediss://")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            # Fail closed: single-use QR tokens and lockouts must not silently
            # stop working if Valkey is down.
            "IGNORE_EXCEPTIONS": False,
        },
    },
}

# LOGGING
# ------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(name)s %(process)d %(message)s",
        },
        "json": {"()": "mealtally.common.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}

# CELERY
# ------------------------------------------------------------------------------
CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_URL = REDIS_URL
CELERY_BROKER_USE_SSL = {"ssl_cert_reqs": ssl.CERT_NONE} if REDIS_SSL else None
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_REDIS_BACKEND_USE_SSL = CELERY_BROKER_USE_SSL
CELERY_RESULT_EXTENDED = True
CELERY_RESULT_BACKEND_ALWAYS_RETRY = True
CELERY_RESULT_BACKEND_MAX_RETRIES = 10
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_TIME_LIMIT = 5 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 4 * 60
CELERY_WORKER_SEND_TASK_EVENTS = True
CELERY_TASK_SEND_SENT_EVENT = True
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
# Static schedule (django-celery-beat 2.9 does not support Django 6.1).
CELERY_BEAT_SCHEDULE = {
    "expire-and-activate-passes": {
        "task": "mealtally.passes.tasks.expire_and_activate_passes",
        "schedule": crontab(minute="*/5"),
    },
    "nightly-ledger-reconciliation": {
        "task": "mealtally.ledger.tasks.reconcile_ledgers",
        # 21:00 UTC == 02:30 IST
        "schedule": crontab(hour=21, minute=0),
    },
}

# DJANGO-ALLAUTH
# ------------------------------------------------------------------------------
# Staff/owners sign in with e-mail (allauth) or phone (custom backend) + password.
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_MODEL_EMAIL_FIELD = "email"
ACCOUNT_EMAIL_VERIFICATION = "none"  # staff are admin-created
ACCOUNT_ALLOW_REGISTRATION = False  # no tenant/user self-signup in v1
ACCOUNT_ADAPTER = "mealtally.accounts.adapters.ClosedAccountAdapter"

# DJANGO-AXES (brute-force lockout)
# ------------------------------------------------------------------------------
AXES_HANDLER = "axes.handlers.cache.AxesCacheHandler"
AXES_CACHE = "default"
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_LOCKOUT_PARAMETERS = ["username"]
AXES_RESET_ON_SUCCESS = True
AXES_USERNAME_CALLABLE = "mealtally.accounts.axes.get_username"
AXES_ENABLED = env.bool("AXES_ENABLED", default=True)
# W002: we call AxesProxyHandler explicitly in the JSON login views (no form middleware needed).
# W006: lockout is per identity (not per IP) on purpose: rotating IPs can't bypass it.
SILENCED_SYSTEM_CHECKS = ["axes.W002", "axes.W006"]

# DJANGO REST FRAMEWORK
# ------------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework.authentication.SessionAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "mealtally.api.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "EXCEPTION_HANDLER": "mealtally.api.errors.exception_handler",
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_THROTTLE_RATES": {
        "login": env("MEALTALLY_THROTTLE_LOGIN", default="30/10min"),
        "redeem_user": env("MEALTALLY_THROTTLE_REDEEM_USER", default="60/min"),
        "redeem_tenant": env("MEALTALLY_THROTTLE_REDEEM_TENANT", default="300/min"),
    },
    # Behind a reverse proxy (MEALTALLY_TRUST_PROXY=true) the proxy appends the real client address.
    "NUM_PROXIES": 1 if env.str("MEALTALLY_TRUST_PROXY", default="false").lower() in ("on", "true", "1", "yes") else 0,
}
CORS_URLS_REGEX = r"^/api/.*$"
CORS_ALLOWED_ORIGINS = env.list("DJANGO_CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True

SPECTACULAR_SETTINGS = {
    "TITLE": "Mealtally API",
    "DESCRIPTION": "Prepaid meal-pass platform API (v1).",
    "VERSION": "1.0.0",
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "SERVE_PERMISSIONS": ["mealtally.api.permissions.IsPlatformAdmin"],
    "SERVE_INCLUDE_SCHEMA": False,
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    "COMPONENT_SPLIT_REQUEST": True,
}


# Mealtally
# ------------------------------------------------------------------------------
def _flag(name: str, default: str = "off") -> bool:
    return env.str(name, default=default).strip().lower() in ("on", "true", "1", "yes")


# single: one restaurant on one box (the default). multi: a SaaS operator hosting many restaurants.
MEALTALLY_MODE = env.str("MEALTALLY_MODE", default="single").strip().lower()
if MEALTALLY_MODE not in ("single", "multi"):
    raise ValueError("MEALTALLY_MODE must be 'single' or 'multi'")
MEALTALLY_ENV = env.str("MEALTALLY_ENV", default="production").strip().lower()  # development enables `make demo`
MEALTALLY_BASE_URL = env.str("MEALTALLY_BASE_URL", default="http://localhost:8000").rstrip("/")
# Operator-only features: each is off unless switched on.
MEALTALLY_PLATFORM_FEES = _flag("MEALTALLY_PLATFORM_FEES")
MEALTALLY_MARKETING_SITE = _flag("MEALTALLY_MARKETING_SITE")
MEALTALLY_DEMO_DATASET = _flag("MEALTALLY_DEMO_DATASET")
MEALTALLY_LEGAL_PAGES = _flag("MEALTALLY_LEGAL_PAGES")
MEALTALLY_TRUST_PROXY = _flag("MEALTALLY_TRUST_PROXY", "false")
# Defaults for the first restaurant (all editable later in Business profile).
MEALTALLY_DEFAULT_COUNTRY = env.str("MEALTALLY_DEFAULT_COUNTRY", default="IN").upper()
MEALTALLY_DEFAULT_CURRENCY = env.str("MEALTALLY_DEFAULT_CURRENCY", default="INR").upper()
MEALTALLY_DEFAULT_TIMEZONE = env.str("MEALTALLY_DEFAULT_TIMEZONE", default="Asia/Kolkata")
MEALTALLY_DEFAULT_LANGUAGE = env.str("MEALTALLY_DEFAULT_LANGUAGE", default="en")

# landing-page pricing moved to PlatformSettings (platform admin, no restart); no environment variable.
