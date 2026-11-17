# SPDX-License-Identifier: AGPL-3.0-only
"""System check: new restaurants need a country, a currency and a time zone, and there is no built-in default.

It runs with `migrate` (which the web container runs before it serves anything), so a missing value stops the start
with a clear message, while image builds (`collectstatic` runs only the static-files checks) are not affected.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from babel import Locale
from babel.numbers import list_currencies
from django.conf import settings
from django.core.checks import Error
from django.core.checks import register

HINT = "Set it in .env (make init asks for it), then restart."


@register("mealtally")
def locale_defaults(app_configs=None, **kwargs):
    errors = []
    country = settings.MEALTALLY_DEFAULT_COUNTRY
    if not (len(country) == 2 and country.isalpha() and country in Locale("en").territories):  # noqa: PLR2004
        errors.append(
            Error(
                "MEALTALLY_DEFAULT_COUNTRY is missing or not an ISO 3166 code (such as IN, US, GB, AE, JP).",
                hint=HINT,
                id="mealtally.E001",
            )
        )
    if settings.MEALTALLY_DEFAULT_CURRENCY not in list_currencies():
        errors.append(
            Error(
                "MEALTALLY_DEFAULT_CURRENCY is missing or not an ISO 4217 code (such as INR, USD, GBP, AED, JPY).",
                hint=HINT,
                id="mealtally.E002",
            )
        )
    try:
        ZoneInfo(settings.MEALTALLY_DEFAULT_TIMEZONE)
    except ValueError, KeyError, OSError:
        errors.append(
            Error(
                "MEALTALLY_DEFAULT_TIMEZONE is missing or not a time zone (such as Asia/Kolkata, America/New_York).",
                hint=HINT,
                id="mealtally.E003",
            )
        )
    return errors
