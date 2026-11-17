# SPDX-License-Identifier: AGPL-3.0-only
"""The customer app shell, unified Home, Activity, Account, old URLs, themed controls and consumer money."""

from __future__ import annotations

import pytest

from mealtally.web.templatetags.mealtally_extras import money_consumer
from mealtally.web.templatetags.mealtally_extras import role_label

from .conftest import client_for  # noqa: F401

pytestmark = pytest.mark.django_db


def test_money_consumer_drops_zero_minor_but_keeps_real_ones():
    assert money_consumer(17000) == "₹170" and money_consumer(17050) == "₹170.50" and money_consumer(0) == "₹0"
    assert money_consumer(-32000) == "-₹320" and money_consumer(150000) == "₹1,500"
    from mealtally.web.templatetags.mealtally_extras import money

    assert money(17000) == "₹170.00"  # ledgers, receipts and invoices keep full minor


def test_one_set_of_role_names():
    assert [str(role_label(r)) for r in ("OWNER", "MANAGER", "STAFF", "CHEF", "DRIVER", "CUSTOMER")] == [
        "Owner",
        "Manager",
        "Counter",
        "Chef",
        "Driver",
        "Customer",
    ]


def test_customer_shell_old_urls_still_resolve_and_share_one_navigation(w, cust_c, u):
    from .test_d021_ui import settle

    settle(w)
    for path in (
        "/me/",
        "/me/qr",
        "/me/history",
        "/me/payments",
        "/me/profile",
        "/me/pin",
        "/me/activity",
        "/me/account",
    ):
        r = cust_c.get(u + path)
        assert r.status_code in (200, 302), path
        if r.status_code == 200:
            html = r.content.decode()
            assert 'data-testid="tabbar"' in html and 'class="shell-customer' in html, path
            assert 'data-testid="cust-top"' in html and "console" not in html.split("<body")[1][:200], path


def test_activity_filters_and_account(w, cust_c, u):
    from .test_d021_ui import settle

    settle(w)
    for f in ("", "?f=meals", "?f=payments", "?f=bogus"):
        assert cust_c.get(u + "/me/activity" + f).status_code == 200
    html = cust_c.get(u + "/me/account").content.decode()
    assert "Change PIN" in html and w.customer.customer_code in html and "Log out" in html
    r = cust_c.post(u + "/me/account", {"full_name": "Asha K"})
    assert r.status_code == 200 and "Saved." in r.content.decode()


def test_themed_controls_have_no_browser_default_accent():
    from pathlib import Path

    css = (Path(__file__).resolve().parents[1] / "tailwind" / "input.css").read_text()
    assert 'input[type="radio"]' in css and "accent-color: var(--primary)" in css


def test_business_profile_title_matches_the_nav_label(w, owner_c, u):
    html = owner_c.get(u + "/admin/settings").content.decode()
    assert "<h1" in html and "Business profile" in html.split("<h1")[1].split("</h1>")[0]


def test_counter_role_shows_as_counter_not_staff(w, staff_c, u):
    html = staff_c.get(u + "/staff/").content.decode()
    assert "Counter" in html


def test_platform_login_is_titled_sign_in_and_still_explains_staff_can_use_it(client):
    html = client.get("/login").content.decode()
    assert "<h1" in html and "Sign in" in html.split("<h1")[1].split("</h1>")[0]
    assert "restaurant staff" in html


def test_manager_gets_403_on_the_fee_statement_page_csv_and_pdf_but_the_owner_does_not(w, owner_c, manager_c, u):
    for q in ({}, {"format": "csv"}, {"format": "pdf"}):
        assert manager_c.get(u + "/admin/reports/fees", q).status_code == 403, q
        assert owner_c.get(u + "/admin/reports/fees", q).status_code == 200, q


def test_counter_reversal_toggle_is_only_rendered_when_there_are_reversals(w, staff_c, owner_c, u):
    from mealtally.ledger import services as ledger

    assert "toggle-reversals" not in staff_c.get(u + "/staff/today").content.decode()
    with w.ctx():
        e = ledger.redeem(actor=w.staff, customer=w.customer, idempotency_key="tg", source="STAFF_SEARCH").entry
    assert (
        "toggle-reversals" not in owner_c.get(u + "/staff/today").content.decode()
    )  # a live redemption is not a reversal
    owner_c.post(u + "/staff/reverse", {"entry": e.public_id, "reason": "oops"})
    html = owner_c.get(u + "/staff/today").content.decode()
    assert html.count("toggle-reversals") == 1 and "Show reversals" in html and "Show 1 undone" not in html
