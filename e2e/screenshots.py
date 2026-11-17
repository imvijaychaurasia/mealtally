# SPDX-License-Identifier: AGPL-3.0-only
"""Render docs/screenshots/<role>/<page>-<desktop|mobile>.webp from a `make demo` instance (run by `make screenshots`).

Only the demo restaurants are used. The counter screenshots redeem real meals there, which is fine on a demo.
"""

from __future__ import annotations

import io
import os
import re
import secrets
from pathlib import Path

from PIL import Image
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from e2e.conftest import BASE
from e2e.conftest import DESKTOP
from e2e.conftest import MOBILE
from e2e.conftest import logins

OUT = Path(os.environ.get("SHOTS_DIR", "docs/screenshots"))
DEVICE = {"timezone_id": "Asia/Kolkata", "locale": "en-IN"}  # a phone at the demo restaurants, for the station clocks
SLUG, SLUG2 = "demo-tiffin", "demo-fresh"
PREVIEW = {"wallet", "order", "kitchen-plan", "kitchen-packing", "route"}  # captioned "Preview" in the gallery
TITLES = {
    "owner": "Owner",
    "manager": "Manager",
    "counter": "Counter",
    "chef": "Chef (Preview)",
    "driver": "Driver (Preview)",
    "platform": "Platform admin",
    "customer": "Customer",
    "sign-in": "Sign-in screens",
}
taken: list[tuple[str, str]] = []


def save(page, role: str, name: str, *, sizes=("desktop", "mobile")):
    folder = OUT / role
    folder.mkdir(parents=True, exist_ok=True)
    for size in sizes:
        page.set_viewport_size(DESKTOP if size == "desktop" else MOBILE)
        page.wait_for_timeout(250)
        png = page.screenshot()  # the viewport: fixed bars would float mid-page in a full-page capture
        img = Image.open(io.BytesIO(png))
        img.save(folder / f"{name}-{size}.webp", "WEBP", quality=82, method=6)
    taken.append((role, name))


def go(page, path: str):
    page.goto(BASE + path)
    page.wait_for_load_state("networkidle")


def staff_session(browser, login: str, password: str, slug: str = SLUG):
    ctx = browser.new_context(viewport=DESKTOP, **DEVICE)
    page = ctx.new_page()
    go(page, f"/t/{slug}/login/staff")
    page.fill("#login", login)
    page.fill("#password", password)
    page.click("[data-testid=login-submit]")
    page.wait_for_load_state("networkidle")
    return ctx, page


def customer_session(browser, phone: str, pin: str):
    ctx = browser.new_context(viewport=MOBILE, **DEVICE)
    page = ctx.new_page()
    go(page, f"/t/{SLUG}/login/customer")
    page.fill("#phone", phone)
    page.fill("#pin", pin)
    page.click("[data-testid=login-submit]")
    page.wait_for_load_state("networkidle")
    return ctx, page


def owner(browser, creds):
    ctx, page = staff_session(browser, *creds["staff"]["owner"])
    for name, path in (
        ("dashboard", f"/t/{SLUG}/admin/"),
        ("customers", f"/t/{SLUG}/admin/customers"),
        ("plans", f"/t/{SLUG}/admin/plans"),
        ("meal-times", f"/t/{SLUG}/admin/settings/meal-times"),
        ("reports", f"/t/{SLUG}/admin/reports"),
        ("refused-redemptions", f"/t/{SLUG}/admin/reports/refused"),
        ("audit-log", f"/t/{SLUG}/admin/audit"),
        ("business-profile-and-theme", f"/t/{SLUG}/admin/settings"),
    ):
        go(page, path)
        save(page, "owner", name)
    go(page, f"/t/{SLUG}/admin/customers")
    links = [a.get_attribute("href") for a in page.locator("a[href*='/admin/customers/']").all()]
    for i, href in enumerate(dict.fromkeys(links)):
        go(page, href)
        if i == 0:
            save(page, "owner", "customer")
        receipt = page.locator("a[href*='/receipt/']:not([href$='.pdf'])")
        if receipt.count():
            go(page, receipt.first.get_attribute("href"))
            save(page, "counter", "receipt")
            break
    ctx.close()


def manager(browser, creds):
    ctx, page = staff_session(browser, *creds["staff"]["manager"])
    go(page, f"/t/{SLUG}/admin/")
    save(page, "manager", "dashboard")
    ctx.close()


def counter(browser, creds):
    ctx, page = staff_session(browser, *creds["staff"]["counter"])
    got = set()
    # the counter finds customers by code: try all 25 demo customers, so one is still due a meal in any meal time
    for code in (f"C{n:04d}" for n in range(1, 26)):
        go(page, f"/t/{SLUG}/staff/")
        page.fill("#q", code)
        try:
            page.locator("#results button").first.click(timeout=5000)
            page.locator("[data-testid=customer-card]").wait_for(timeout=5000)
        except PlaywrightTimeout:
            continue
        if "search" not in got:
            save(page, "counter", "redeem-search")
            got.add("search")
        redeem = page.locator("[data-testid=redeem]")
        if not redeem.count() or not redeem.first.is_enabled():
            # outside this plan's meal times the card explains the rule instead of offering a redeem button
            card = page.locator("[data-testid=customer-card]").inner_text()
            if "blocked" not in got and re.search(r"is served|are served|already had", card, re.I):
                save(page, "counter", "redeem-blocked-by-meal-rule")
                got.add("blocked")
            continue
        redeem.first.click()
        page.wait_for_timeout(800)
        error = page.locator("[data-testid=card-error]")
        if page.get_by_text(re.compile("Meal redeemed")).count():
            if "success" not in got:
                save(page, "counter", "redeem-success", sizes=("desktop",))
                got.add("success")
        elif error.count() and re.search(r"meal time|served|already had|daily", error.first.inner_text(), re.I):
            if "blocked" not in got:
                save(page, "counter", "redeem-blocked-by-meal-rule")
                got.add("blocked")
        if {"search", "success", "blocked"} <= got:
            break
    go(page, f"/t/{SLUG}/staff/sell")
    save(page, "counter", "sell-pass")
    ctx.close()


def chef(browser, creds):
    ctx, page = staff_session(browser, *creds["staff"]["chef"])
    go(page, f"/t/{SLUG}/admin/kitchen")
    save(page, "chef", "kitchen-plan")
    page.click("[data-tab=pack]")
    save(page, "chef", "kitchen-packing")
    ctx.close()


def driver(browser, creds):
    ctx, page = staff_session(browser, *creds["staff"]["driver"])
    go(page, f"/t/{SLUG}/driver/")
    save(page, "driver", "route", sizes=("mobile", "desktop"))
    ctx.close()


def platform(browser):
    login, password = os.environ.get("E2E_ADMIN_LOGIN"), os.environ.get("E2E_ADMIN_PASSWORD")
    if not (login and password):
        print("platform: skipped (set E2E_ADMIN_LOGIN and E2E_ADMIN_PASSWORD)")
        return
    ctx = browser.new_context(viewport=DESKTOP, **DEVICE)
    page = ctx.new_page()
    go(page, "/login")
    page.fill("#login", login)
    page.fill("#password", password)
    page.click("[data-testid=login-submit]")
    page.wait_for_load_state("networkidle")
    if page.locator("#old_password").count():  # an admin from `make init` changes the password first
        new = secrets.token_urlsafe(18)
        page.fill("#old_password", password)
        page.fill("#new_password", new)
        page.fill("#confirm_password", new)
        page.locator("main button[type=submit]").first.click()
        page.wait_for_load_state("networkidle")
    go(page, "/platform/")
    if page.locator("[data-slug]").count():  # the tenants table: multi mode
        save(page, "platform", "tenants", sizes=("desktop",))
    else:
        print("platform: skipped (single mode)")
    ctx.close()


def customers(browser, creds):
    kinds = {}
    for phone, pin in creds["customers"]:
        ctx, page = customer_session(browser, phone, pin)
        kind = "wallet" if page.locator("[data-testid=home-wallet]").count() else "pass-only"
        if kind in kinds:
            ctx.close()
            continue
        kinds[kind] = True
        save(page, "customer", f"home-{kind}", sizes=("mobile", "desktop"))
        if kind == "pass-only":
            for name, path in (("qr", "/me/qr"), ("activity", "/me/activity"), ("account", "/me/account")):
                go(page, f"/t/{SLUG}{path}")
                save(page, "customer", name, sizes=("mobile", "desktop"))
        else:
            go(page, f"/t/{SLUG}/me/wallet")
            save(page, "customer", "wallet", sizes=("mobile", "desktop"))
            go(page, f"/t/{SLUG}/me/order")
            add = page.locator("[data-add]")
            for i in range(min(2, add.count())):
                add.nth(i).click()
            save(page, "customer", "order", sizes=("mobile", "desktop"))
        ctx.close()
        if len(kinds) == 2:  # noqa: PLR2004
            break


def sign_in(browser):
    ctx = browser.new_context(viewport=DESKTOP, **DEVICE)
    page = ctx.new_page()
    for slug, theme in ((SLUG, "masala"), (SLUG2, "fresh")):
        go(page, f"/t/{slug}/login/staff")
        actual = page.locator("html").get_attribute("data-theme")
        assert actual == theme, f"{slug} sign-in renders theme {actual}, expected {theme}"
        save(page, "sign-in", f"staff-{theme}")
    ctx.add_cookies([{"name": "mealtally-language", "value": "ar", "url": BASE}])
    go(page, f"/t/{SLUG}/login/customer")
    assert page.locator("html").get_attribute("dir") == "rtl"
    save(page, "sign-in", "customer-arabic-rtl")
    ctx.close()


def gallery():
    lines = [
        "# Screenshots",
        "",
        "Rendered by `make screenshots` from the two `make demo` restaurants (sample data only). Desktop is 1440 px",
        'wide, phone 390 px. Screens marked "Preview" show modules that are not working features yet.',
        "",
    ]
    for role, title in TITLES.items():
        names = [n for r, n in taken if r == role]
        if not names:
            continue
        lines += [f"## {title}", ""]
        for name in names:
            label = name.replace("-", " ").capitalize() + (" (Preview)" if name in PREVIEW else "")
            files = sorted(p.name for p in (OUT / role).glob(f"{name}-*.webp"))
            links = " · ".join(f"[{f.rsplit('-', 1)[1].removesuffix('.webp')}]({role}/{f})" for f in files)
            lines.append(f"- {label}: {links}")
        lines.append("")
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    creds = logins()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for step in (owner, manager, counter, chef, driver, customers):
            step(browser, creds)
        platform(browser)
        sign_in(browser)
        browser.close()
    gallery()
    print(f"{len(taken)} screens written to {OUT}/")


if __name__ == "__main__":
    main()
