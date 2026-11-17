# SPDX-License-Identifier: AGPL-3.0-only
"""Money: integer minor units of the restaurant's ISO 4217 currency, formatted with CLDR data (Babel).

Amounts are never floats and never divided anywhere else. The display locale is the active language plus the
restaurant's country (``en`` + ``IN`` -> ``en_IN``, which groups as 1,24,325 and abbreviates as L / Cr; ``en`` + ``US``
groups as 124,325 and abbreviates as K / M). JPY and other zero-decimal currencies have no minor unit.

The current restaurant's currency and country are set per request (``use``); outside a request the instance
defaults (MEALTALLY_DEFAULT_CURRENCY / MEALTALLY_DEFAULT_COUNTRY) apply.
"""

from __future__ import annotations

from contextvars import ContextVar
from decimal import Decimal
from decimal import InvalidOperation

from babel import Locale
from babel import UnknownLocaleError
from babel.numbers import format_compact_currency
from babel.numbers import format_currency
from babel.numbers import get_currency_precision
from django.conf import settings
from django.utils import translation

_current: ContextVar[tuple[str, str] | None] = ContextVar("mealtally_money", default=None)


class MoneyInputError(ValueError):
    """An amount that isn't a valid number of this currency's units (for example 10.555 INR or 10.5 JPY)."""


def use(currency: str | None, country: str | None = None):
    """Make ``currency``/``country`` current (None clears it); returns a token for ``reset``."""
    value = (currency.upper(), (country or settings.MEALTALLY_DEFAULT_COUNTRY).upper()) if currency else None
    return _current.set(value)


def reset(token) -> None:
    _current.reset(token)


def current_currency() -> str:
    value = _current.get()
    return value[0] if value else settings.MEALTALLY_DEFAULT_CURRENCY


def current_country() -> str:
    value = _current.get()
    return value[1] if value else settings.MEALTALLY_DEFAULT_COUNTRY


def locale_for(language: str | None = None, country: str | None = None) -> str:
    """Babel locale for a language and a country: ``en`` + ``IN`` -> ``en_IN``; falls back to the language alone."""
    language = (language or translation.get_language() or settings.LANGUAGE_CODE).replace("-", "_")
    base = language.split("_")[0]
    country = (country or current_country()).upper()
    for candidate in (f"{base}_{country}", language, base):
        try:
            return str(Locale.parse(candidate))
        except UnknownLocaleError, ValueError:
            continue
    return "en"


def exponent(currency: str | None = None) -> int:
    """Decimal places of the currency's minor unit (INR 2, JPY 0, KWD 3)."""
    return get_currency_precision(currency or current_currency())


def to_major(minor: int, currency: str | None = None) -> Decimal:
    return Decimal(int(minor)).scaleb(-exponent(currency))


def to_minor(amount, currency: str | None = None) -> int:
    """'1500' or '1500.50' (major units) -> integer minor units. Rejects more decimals than the currency has."""
    try:
        value = Decimal(str(amount).strip().replace(",", ""))
    except InvalidOperation as exc:
        raise MoneyInputError(str(amount)) from exc
    if not value.is_finite():
        raise MoneyInputError(str(amount))
    scaled = value.scaleb(exponent(currency))
    if scaled != scaled.to_integral_value():
        raise MoneyInputError(str(amount))
    return int(scaled)


def format_money(minor, currency: str | None = None, *, locale: str | None = None) -> str:
    """``₹1,500.00`` / ``$1,500.00`` / ``￥1,500`` -- every screen, CSV and PDF goes through this (``|money``)."""
    currency = currency or current_currency()
    return format_currency(to_major(minor or 0, currency), currency, locale=locale or locale_for())


def format_money_consumer(minor, currency: str | None = None, *, locale: str | None = None) -> str:
    """Customer screens: whole amounts without the zero decimals (``₹170``), others in full (``₹170.50``)."""
    currency = currency or current_currency()
    loc = locale or locale_for()
    places = exponent(currency)
    text = format_currency(to_major(minor or 0, currency), currency, locale=loc)
    if places and int(minor or 0) % (10**places) == 0:
        from babel.numbers import get_decimal_symbol  # noqa: PLC0415

        text = text.replace(get_decimal_symbol(loc) + "0" * places, "", 1)
    return text


def format_money_compact(minor, currency: str | None = None, *, locale: str | None = None) -> str:
    """Tiles and chart axes: ``₹1.24L`` / ``₹1.2Cr`` in Indian locales, ``$124.3K`` / ``$1.2M`` elsewhere."""
    currency = currency or current_currency()
    value = to_major(minor or 0, currency)
    if abs(value) < 1000:  # noqa: PLR2004
        return format_money_consumer(minor, currency, locale=locale)
    # round first so 99,99,990 shows as 1Cr (not 100L): three significant figures below 100,000 (82.1K), four above
    # (99.95L, 1.24Cr)
    value = Decimal(f"{value:.3g}") if abs(value) < 100_000 else Decimal(f"{value:.4g}")  # noqa: PLR2004
    return format_compact_currency(value, currency, locale=locale or locale_for(), fraction_digits=2)


def per_meal(price_minor: int, meals: int, currency: str | None = None) -> str:
    """Price per meal, rounded to the minor unit (``₹50`` per meal)."""
    if not meals:
        return ""
    return format_money_consumer(round(int(price_minor) / meals), currency)


def currency_symbol(currency: str | None = None, *, locale: str | None = None) -> str:
    from babel.numbers import get_currency_symbol  # noqa: PLC0415

    return get_currency_symbol(currency or current_currency(), locale=locale or locale_for())
