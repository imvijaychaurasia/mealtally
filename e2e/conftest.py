# SPDX-License-Identifier: AGPL-3.0-only
"""Playwright smoke suite: a few minutes, headless Chromium, against a running instance seeded by `make demo`.

    make smoke                                   # uses http://localhost:$MEALTALLY_PORT and ./.demo-credentials
    E2E_BASE_URL=http://localhost:18080 E2E_CREDENTIALS=.demo-credentials pytest e2e

It only reads from the demo restaurants, apart from redeeming one meal at the counter. Every page it opens is checked
for JavaScript errors and Content-Security-Policy violations.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000").rstrip("/")
CREDENTIALS = Path(os.environ.get("E2E_CREDENTIALS", ".demo-credentials"))
SLUG = "demo-tiffin"
MOBILE = {"width": 390, "height": 844}
DESKTOP = {"width": 1440, "height": 900}
CSP_HOOK = """
window.__csp = [];
document.addEventListener('securitypolicyviolation', e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));
"""


def logins() -> dict:
    """Parse ./.demo-credentials: the first restaurant's staff by role, its customers, and the platform admin."""
    if not CREDENTIALS.exists():
        pytest.exit(f"{CREDENTIALS} not found: run `make demo` first", returncode=2)
    out: dict = {"staff": {}, "customers": []}
    section = None
    for line in CREDENTIALS.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line.split("/t/")[-1].strip("/ ")
        elif m := re.match(r"PLATFORM ADMIN\s+login=(\S+)\s+password=(\S+)", line):
            out["admin"] = (m[1], m[2])
        elif section == SLUG and (m := re.match(r"(\w+)\s+login=(\S+)\s+password=(\S+)", line)):
            out["staff"].setdefault(m[1].lower(), (m[2], m[3]))
        elif section == SLUG and (m := re.match(r"CUSTOMER\s+.+?\s+phone=(\S+)\s+pin=(\d+)", line)):
            out["customers"].append((m[1], m[2]))
    return out


class Tracked:
    """A page that collects console errors and CSP violations."""

    def __init__(self, page):
        self.page = page
        self.errors: list[str] = []
        page.on("console", lambda m: self.errors.append(f"console: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))

    def __getattr__(self, name):
        return getattr(self.page, name)

    def goto(self, path: str, **kw):
        return self.page.goto(BASE + path, **kw)

    def assert_clean(self):
        csp = self.page.evaluate("window.__csp || []")
        assert not csp, f"CSP violations on {self.page.url}: {csp}"
        assert not self.errors, f"JavaScript errors on {self.page.url}: {self.errors}"


@pytest.fixture(scope="session")
def creds():
    return logins()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport=MOBILE)
    ctx.add_init_script(CSP_HOOK)
    yield Tracked(ctx.new_page())
    ctx.close()


def staff_login(page, login: str, password: str, slug: str = SLUG):
    page.goto(f"/t/{slug}/login/staff")
    page.fill("#login", login)
    page.fill("#password", password)
    page.click("[data-testid=login-submit]")
    page.wait_for_load_state("networkidle")


def customer_login(page, phone: str, pin: str, slug: str = SLUG):
    page.goto(f"/t/{slug}/login/customer")
    page.fill("#phone", phone)
    page.fill("#pin", pin)
    page.click("[data-testid=login-submit]")
    page.wait_for_load_state("networkidle")
