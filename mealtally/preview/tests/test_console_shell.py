# SPDX-License-Identifier: AGPL-3.0-only
"""Console shell: the sidebar is behind a per-tenant switch, every sidebar link works for every role in BOTH shells."""

from __future__ import annotations

import html as htmllib
import re
from pathlib import Path

import pytest
from django.urls import reverse
from django.utils import timezone

from mealtally.preview import data as pvdata
from mealtally.preview.tests.test_preview import SLUG
from mealtally.preview.tests.test_preview import check
from mealtally.preview.tests.test_preview import clients  # noqa: F401 (fixture)
from mealtally.preview.tests.test_preview import demo  # noqa: F401 (fixture)
from mealtally.preview.tests.test_preview import preview_urls
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.models import Tenant

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[2]
STAFF_ROLES = ("OWNER", "MANAGER", "STAFF", "CHEF", "DRIVER")
HOMES = {"STAFF": "/staff/", "CHEF": "/admin/kitchen", "DRIVER": "/driver/"}


def set_shell(value):
    with platform_context():
        Tenant.objects.filter(slug=SLUG).update(ui_shell=value)


def hrefs(html, shell):
    """Navigation links of a page: sidebar anchors (console) or the top nav (classic)."""
    if shell == "console":
        return sorted(set(re.findall(r'<a [^>]*href="([^"]+)"[^>]*data-sb-link', html)))
    nav = html[html.index('aria-label="Main"') :]
    return sorted(set(re.findall(r'href="(/t/[^"]+)"', nav[: nav.index("</nav>")])))


def sidebar_labels(html):
    aside = html[html.index('data-testid="sidebar"') : html.index("</aside>")]
    items = re.findall(r'class="sb-label min-w-0 flex-1 truncate">([^<]+)<', aside)
    sections = re.findall(r'class="sb-section [^"]*">([^<]+)<', aside)
    return [htmllib.unescape(i) for i in items], sections


def home(role):
    return f"/t/{SLUG}{HOMES.get(role, '/admin/today')}"


def test_console_is_the_default_and_flipping_the_setting_restores_the_old_shell(demo, clients):  # noqa: F811
    owner = clients["OWNER"]
    console = owner.get(f"/t/{SLUG}/admin/today").content.decode()  # console is the default for every tenant
    assert (
        'data-testid="sidebar"' in console
        and 'data-testid="tile-customers"' in console
        and 'aria-label="Tabs"' not in console
    )
    set_shell("classic")  # the Django admin flip: same URL, the old UI is back, no deploy
    page = owner.get(f"/t/{SLUG}/admin/today").content.decode()
    assert 'data-testid="sidebar"' not in page and 'data-testid="tile-customers"' not in page
    assert 'aria-label="Main"' in page and 'aria-label="Tabs"' in page
    from mealtally.tenancy.admin import TenantAdmin

    assert "ui_shell" in TenantAdmin.list_editable and "ui_shell" in TenantAdmin.list_display
    assert Tenant._meta.get_field("ui_shell").default == "console"


@pytest.mark.parametrize("shell", ["classic", "console"])
def test_every_navigation_link_works_for_every_role_in_both_shells(demo, clients, shell):  # noqa: F811
    set_shell(shell)
    total = 0
    for role in STAFF_ROLES:
        resp = clients[role].get(home(role))
        assert resp.status_code == 200, (role, shell)
        links = hrefs(resp.content.decode(), shell)
        if shell == "console" and role in ("CHEF", "DRIVER"):  # station shell: no sidebar by design
            assert 'data-testid="sidebar"' not in resp.content.decode(), role
            links = (
                re.findall(r'href="(/t/[^"#]+)', resp.content.decode().split('data-testid="station-bar"')[-1])
                if role == "DRIVER"
                else []
            )
            total += 1
            if not links:
                continue
        assert links, (role, shell)
        for url in links:
            got = clients[role].get(url)
            assert got.status_code < 400, f"{shell}/{role}: {url} -> {got.status_code}"
            total += 1
    assert total >= 20


def test_sidebar_shows_each_role_only_what_it_may_use(demo, clients):  # noqa: F811
    set_shell("console")
    items, sections = sidebar_labels(clients["OWNER"].get(home("OWNER")).content.decode())
    expected = (
        "Dashboard",
        "Business profile",
        "Plan & platform fees",
        "Staff & roles",
        "Meal categories",
        "Meal plans",
        "Customers",
        "Subscriptions",
        "Redeem counter",
        "Orders",
        "Kitchen",
        "Delivery routes",
        "Driver",
        "Expenses",
        "Receipts & payments",
        "Wallet top-ups",
        "Invoices",
        "Reports",
        "Audit log",
        "Settings",
        "Customer portal",
    )
    for want in expected:
        assert want in items, want
    assert sections == ["Menu", "Operations", "Finance", "Insights", "Settings"]
    ops = items[items.index("Meal plans") + 1 :]
    assert ops[0] == "Redeem counter"  # the differentiator sits at the top of OPERATIONS
    mgr, _ = sidebar_labels(clients["MANAGER"].get(home("MANAGER")).content.decode())
    assert (
        not {"Staff & roles", "Business profile", "Settings"} & set(mgr)
        and "Orders" in mgr
        and "Customer portal" in mgr
    )
    staff, _ = sidebar_labels(clients["STAFF"].get(home("STAFF")).content.decode())
    assert staff == ["Redeem counter", "Sell pass", "Customers", "Orders"]
    for role in (
        "CHEF",
        "DRIVER",
    ):  # the station shell has no sidebar, only a slim top bar (and a bar for drivers)
        page = clients[role].get(home(role)).content.decode()
        assert 'data-testid="sidebar"' not in page and 'data-testid="station-role"' in page


def test_console_dashboard_content_and_numbers_agree_with_the_profit_screen(demo, clients):  # noqa: F811
    set_shell("console")
    resp = clients["OWNER"].get(home("OWNER"))
    check("dashboard", resp)
    html = resp.content.decode()
    for tid in (
        "tile-customers",
        "tile-meals",
        "tile-revenue",
        "tile-expenses",
        "fee-line",
        "alerts",
        "chart",
        "deliveries",
        "portal",
        "low-wallets",
        "shortcuts",
    ):
        assert f'data-testid="{tid}"' in html, tid
    assert "Platform fee this month" in html and "View statement" in html
    assert "data-alert>" in html and "data-dismiss" in html and "data-alerts-empty" in html
    assert (
        "<svg" in html[html.index('data-testid="chart"') :]
        and "Home delivery" in html
        and "Pick-up" in html
        and "Dine-in" in html
    )
    assert 'data-copy="http' in html and "data:image/svg+xml;base64," in html and "Remind" in html
    for shortcut in ("Redeem meal", "New customer", "Sell pass", "Record top-up", "Kitchen sheet", "Packing list"):
        assert shortcut in html, shortcut
    full = {
        k: re.search(rf'data-testid="tile-{k}"[^>]*title="([^"]+)"', html).group(1) for k in ("revenue", "expenses")
    }
    compact = {k: re.search(rf'data-testid="tile-{k}-value">([^<]+)<', html).group(1) for k in ("revenue", "expenses")}
    assert all(re.fullmatch(r"₹[\d.]+(K|L|Cr)", v) for v in compact.values()), (
        compact
    )  # compact on the tile, full in the tooltip
    profit = clients["OWNER"].get(f"/t/{SLUG}/admin/expenses/profit").content.decode()
    assert f">{full['revenue']}<" in profit and f">{full['expenses']}<" in profit  # one number, on every screen
    rev = int(re.sub(r"\D", "", full["revenue"].split(".")[0]))
    exp = int(re.sub(r"\D", "", full["expenses"].split(".")[0]))
    assert 0.62 <= exp / rev <= 0.70


def test_console_renders_every_preview_page_for_the_owner_without_errors(demo, clients):  # noqa: F811
    set_shell("console")
    D = pvdata.get(timezone.localdate())
    for name, kw in preview_urls(D):
        if name.startswith("me-") or name == "driver":
            continue
        url = reverse(f"preview:{name}", kwargs={"slug": SLUG, **kw})
        resp = clients["OWNER"].get(url)
        check(url, resp)
        if resp["Content-Type"].startswith("text/html"):
            assert name == "kitchen-labels" or 'data-testid="sidebar"' in resp.content.decode(), url


def test_scanner_page_still_loads_zxing_and_the_camera_header_in_the_console_shell(demo, clients):  # noqa: F811
    set_shell("console")
    resp = clients["STAFF"].get(f"/t/{SLUG}/staff/")
    html = resp.content.decode()
    assert "vendor/zxing-library.min.js" in html and html.index("zxing-library") < html.index("zxing-browser")
    assert "<video" in html and "playsinline" in html and "autoplay" in html and "scan-open" in html
    assert resp["Permissions-Policy"].startswith("camera=(self)")
    assert (
        html.index('data-testid="scan-open"') > html.index("<main")
        and html.index('data-testid="scan-open"') - html.index("<main") < 1500
    )
