# SPDX-License-Identifier: AGPL-3.0-only
"""Smoke: the instance is up, every role can sign in and do its main job, and right-to-left works."""

from __future__ import annotations

import os
import re

import pytest
from playwright.sync_api import expect

from .conftest import BASE
from .conftest import DESKTOP
from .conftest import SLUG
from .conftest import customer_login
from .conftest import staff_login


def test_health_and_root(page):
    assert page.request.get(BASE + "/healthz").ok
    page.goto("/")
    expect(page.locator("h1").first).to_be_visible()
    page.assert_clean()


def test_platform_admin_signs_in(page, creds):
    """The admin from `make demo`, or the one from `make init` given as E2E_ADMIN_LOGIN / E2E_ADMIN_PASSWORD."""
    login, password = creds.get("admin") or (os.environ.get("E2E_ADMIN_LOGIN"), os.environ.get("E2E_ADMIN_PASSWORD"))
    if not (login and password):
        pytest.skip("no platform admin password: set E2E_ADMIN_LOGIN and E2E_ADMIN_PASSWORD")
    page.goto("/login")
    page.fill("#login", login)
    page.fill("#password", password)
    page.click("#login-submit")
    page.wait_for_load_state("networkidle")
    assert "/login" not in page.url
    expect(page.locator("h1").first).to_be_visible()
    page.assert_clean()


def test_owner_dashboard_and_staff_list(page, creds):
    page.set_viewport_size(DESKTOP)
    staff_login(page, *creds["staff"]["owner"])
    assert f"/t/{SLUG}/" in page.url and "/login" not in page.url
    page.goto(f"/t/{SLUG}/admin/staff")
    roles = page.locator("[data-testid=staff-role]").all_inner_texts()
    assert "Counter" in roles and "STAFF" not in roles
    page.assert_clean()


def test_counter_finds_a_customer_and_redeems(page, creds):
    staff_login(page, *creds["staff"]["counter"])
    page.goto(f"/t/{SLUG}/staff/")
    page.fill("#q", creds["customers"][0][0][-4:])
    page.locator("#results button").first.click()
    card = page.locator("[data-testid=customer-card]")
    expect(card).to_be_visible()
    redeem = page.locator("[data-testid=redeem]")
    if redeem.count() and redeem.first.is_enabled():
        redeem.first.click()
        # served, or refused by a meal rule (outside meal time, daily limit): either way the counter answered
        expect(page.locator("[data-testid=remaining], [data-testid=card-error], [role=status]").first).to_be_visible()
    page.assert_clean()


def test_customer_home_and_qr(page, creds):
    customer_login(page, *creds["customers"][1])
    expect(page.locator("[data-testid=cust-home]")).to_be_visible()
    page.goto(f"/t/{SLUG}/me/qr")
    expect(page.locator("svg, img, canvas").first).to_be_visible()
    page.assert_clean()


def test_arabic_is_right_to_left(page):
    page.goto(f"/t/{SLUG}/login/customer")
    page.select_option("[data-testid=lang] >> nth=0", "ar")
    page.wait_for_load_state("networkidle")
    html = page.locator("html")
    expect(html).to_have_attribute("dir", "rtl")
    expect(html).to_have_attribute("lang", re.compile("^ar"))
    page.select_option("[data-testid=lang] >> nth=0", "en")
    page.wait_for_load_state("networkidle")
    expect(html).to_have_attribute("dir", "ltr")
    page.assert_clean()
