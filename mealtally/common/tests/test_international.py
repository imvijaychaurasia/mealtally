# SPDX-License-Identifier: AGPL-3.0-only
"""Money, phones, tax and licence labels and payment methods for India, the US, the UK, the UAE and Japan."""

from __future__ import annotations

import pytest
from django.utils import translation

from mealtally.common import country
from mealtally.common import money
from mealtally.common.errors import ValidationFailed


@pytest.fixture
def restaurant():
    """Run a block as if the current request belonged to a restaurant with this currency and country."""
    tokens = []

    def use(currency, ctry, language="en"):
        tokens.append(money.use(currency, ctry))
        translation.activate(language)

    yield use
    for t in reversed(tokens):
        money.reset(t)
    translation.deactivate()


@pytest.mark.parametrize(
    ("currency", "ctry", "language", "minor", "full", "consumer", "compact_minor", "compact"),
    [
        ("INR", "IN", "en", 15000050, "₹1,50,000.50", "₹1,50,000.50", 1243250000, "₹1.24Cr"),
        ("INR", "IN", "hi", 17000, "₹170.00", "₹170", 12432500, "₹1.24\xa0लाख"),
        ("USD", "US", "en", 15000050, "$150,000.50", "$150,000.50", 1243250000, "$12.43M"),
        ("EUR", "DE", "de", 17000, "170,00\xa0€", "170\xa0€", 17000, "170\xa0€"),
        ("GBP", "GB", "en", 17000, "£170.00", "£170", 12432500, "£124.3K"),
        ("AED", "AE", "en", 17050, "AED170.50", "AED170.50", 12432500, "AED124.3K"),
        ("JPY", "JP", "ja", 1500, "￥1,500", "￥1,500", 12432500, "￥1243万"),
    ],
)
def test_money_formats(restaurant, currency, ctry, language, minor, full, consumer, compact_minor, compact):
    restaurant(currency, ctry, language)
    assert money.format_money(minor) == full
    assert money.format_money_consumer(minor) == consumer
    assert money.format_money_compact(compact_minor) == compact


def test_minor_units_follow_the_currency(restaurant):
    restaurant("JPY", "JP")
    assert money.exponent() == 0 and money.to_minor("1500") == 1500
    with pytest.raises(money.MoneyInputError):
        money.to_minor("1500.5")  # yen have no decimals
    restaurant("INR", "IN")
    assert money.to_minor("1500.50") == 150050 and money.to_minor("1,500") == 150000
    assert str(money.to_major(150050)) == "1500.50"
    with pytest.raises(money.MoneyInputError):
        money.to_minor("10.555")
    with pytest.raises(money.MoneyInputError):
        money.to_minor("ten")
    restaurant("KWD", "KW")
    assert money.to_minor("1.234") == 1234  # three decimals


@pytest.mark.parametrize(
    ("ctry", "raw", "e164", "shown"),
    [
        ("IN", "98765 43210", "+919876543210", "098765 43210"),
        ("US", "(202) 555-0123", "+12025550123", "(202) 555-0123"),
        ("GB", "07911 123456", "+447911123456", "07911 123456"),
        ("AE", "050 123 4567", "+971501234567", "050 123 4567"),
        ("JP", "090-1234-5678", "+819012345678", "090-1234-5678"),
    ],
)
def test_phones_are_stored_as_e164_and_shown_in_national_format(restaurant, ctry, raw, e164, shown):
    restaurant("USD", ctry)
    assert country.normalize_phone(raw) == e164
    assert country.format_phone(e164) == shown
    assert country.mask_phone(e164).endswith(e164[-4:])


def test_foreign_numbers_are_shown_internationally_and_bad_ones_rejected(restaurant):
    restaurant("INR", "IN")
    assert country.format_phone("+447911123456") == "+44 7911 123456"
    assert country.normalize_phone("0044 7911 123456") == "+447911123456"
    with pytest.raises(ValidationFailed):
        country.normalize_phone("123")
    with pytest.raises(ValidationFailed):
        country.normalize_phone("not a phone")
    assert country.format_phone("garbage") == "garbage" and country.format_phone("") == ""


@pytest.mark.parametrize(
    ("ctry", "tax", "licence", "methods"),
    [
        ("IN", "GSTIN", "FSSAI licence number", ["CASH", "UPI_MANUAL", "BANK_TRANSFER"]),
        ("US", "Tax ID", "Food business licence", ["CASH", "BANK_TRANSFER"]),
        ("GB", "VAT number", "Food business licence", ["CASH", "BANK_TRANSFER"]),
        ("DE", "VAT number", "Food business licence", ["CASH", "BANK_TRANSFER"]),
        ("AE", "Tax ID", "Food business licence", ["CASH", "BANK_TRANSFER"]),
        ("JP", "Tax ID", "Food business licence", ["CASH", "BANK_TRANSFER"]),
    ],
)
def test_country_drives_labels_and_payment_methods(ctry, tax, licence, methods):
    assert str(country.tax_id_label(ctry)) == tax
    assert str(country.food_licence_label(ctry)) == licence
    assert [m for m, _ in country.payment_methods(ctry)] == methods
    assert country.upi_enabled(ctry) is (ctry == "IN")


def test_locale_combines_language_and_country():
    assert money.locale_for("en", "IN") == "en_IN"
    assert money.locale_for("hi", "IN") == "hi_IN"
    assert money.locale_for("en", "US") == "en_US"
    assert money.locale_for("hi", "US") == "hi"  # no hi_US: the language alone
    assert money.locale_for("pt-br", "BR") == "pt_BR"


# --- through the app ------------------------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_us_restaurant_sells_in_dollars_without_upi_or_a_gstin_check():
    from mealtally.tenancy import services as tenancy
    from mealtally.testing import World
    from mealtally.testing import buy
    from mealtally.web.tests.conftest import client_for

    w = World(slug="diner", buy_pass=False)
    with w.ctx():
        tenancy.update_settings(actor=w.owner, country="us", currency="usd", tax_id="12-3456789")
        w.tenant.refresh_from_db()
    assert (w.tenant.country, w.tenant.currency) == ("US", "USD")
    staff, owner = client_for(w.staff.user), client_for(w.owner.user)
    u = f"/t/{w.tenant.slug}"
    sell = staff.get(u + "/staff/sell").content.decode()
    assert 'value="UPI_MANUAL"' not in sell and 'value="BANK_TRANSFER"' in sell and "$1,500.00" in sell
    with pytest.raises(ValidationFailed):
        buy(w.tenant, w.staff, w.customer, w.plan, method="UPI_MANUAL")
    rec = buy(w.tenant, w.staff, w.customer, w.plan, method="BANK_TRANSFER")
    receipt = owner.get(f"{u}/receipt/{rec.payment.public_id}").content.decode()
    assert "$1,500.00" in receipt and "Tax ID: 12-3456789" in receipt and "₹" not in receipt
    profile = owner.get(u + "/admin/settings").content.decode()
    assert "Tax ID (optional" in profile and "Food business licence" in profile


@pytest.mark.django_db
def test_an_indian_restaurant_keeps_gstin_validation_and_upi():
    from mealtally.tenancy import services as tenancy
    from mealtally.testing import World

    w = World(slug="mess-in", buy_pass=False)
    with w.ctx(), pytest.raises(ValidationFailed):
        tenancy.update_settings(actor=w.owner, tax_id="12-3456789")  # not a 15-character GSTIN
    with w.ctx(), pytest.raises(ValidationFailed):
        tenancy.update_settings(actor=w.owner, currency="XYZ")
    with w.ctx(), pytest.raises(ValidationFailed):
        tenancy.update_settings(actor=w.owner, country="ZZ")


@pytest.mark.django_db
def test_a_japanese_restaurant_prices_plans_in_whole_yen():
    from mealtally.tenancy import services as tenancy
    from mealtally.testing import World
    from mealtally.web.tests.conftest import client_for

    w = World(slug="teishoku", buy_pass=False)
    with w.ctx():
        tenancy.update_settings(actor=w.owner, country="JP", currency="JPY")
    owner = client_for(w.owner.user)
    u = f"/t/{w.tenant.slug}"
    form = {"name": "Lunch set", "meals_per_cycle": "20", "validity_mode": "ROLLING_DAYS", "validity_days": "30"}
    assert owner.post(u + "/admin/plans/new", {**form, "price_major": "12000"}).status_code == 302
    bad = owner.post(u + "/admin/plans/new", {**form, "price_major": "12000.5"})
    assert bad.status_code == 400
    from mealtally.plans.models import Plan

    with w.ctx():
        assert Plan.objects.get(name="Lunch set").price_minor == 12000
    assert "¥12,000" in owner.get(u + "/admin/plans").content.decode()  # English screens use ¥, Japanese ￥
