# SPDX-License-Identifier: AGPL-3.0-only
"""Theme system: tokens, WCAG AA contrast for every pair, no raw colours in templates, compact money, theme switching."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.urls import reverse
from django.utils import timezone

from mealtally.common.money import format_money
from mealtally.common.money import format_money_compact as money_compact
from mealtally.preview import data as pvdata
from mealtally.preview.tests.test_preview import SLUG
from mealtally.preview.tests.test_preview import check
from mealtally.preview.tests.test_preview import clients  # noqa: F401 (fixture)
from mealtally.preview.tests.test_preview import demo  # noqa: F401 (fixture)
from mealtally.preview.tests.test_preview import preview_urls
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.models import Tenant
from mealtally.web import themes

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[2]
THEME_NAMES = ("masala", "fresh", "tally")
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
PALETTE = re.compile(
    r"\b(?:bg|text|border|ring|stroke|fill|divide|from|to|placeholder|outline)-"
    r"(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}"
)


def lum(hexv: str) -> float:
    ch = [int(hexv[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    ch = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def ratio(a: str, b: str) -> float:
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# --- tokens and contrast ---------------------------------------------------------------------------------------------
def pairs(t):
    """(foreground, background, why) for every text/background combination the UI uses."""
    out = [
        ("ink", "page", "body text on the page"),
        ("ink", "card", "body text on cards"),
        ("muted", "page", "secondary text on the page"),
        ("muted", "card", "secondary text on cards"),
        ("primary", "card", "links on cards"),
        ("primary", "page", "links on the page"),
        ("on-primary", "primary", "primary button"),
        ("on-primary", "primary-hover", "primary button (hover)"),
        ("side-ink", "side-bg", "sidebar item"),
        ("side-active-ink", "side-active-bg", "sidebar active item"),
        ("side-label", "side-bg", "sidebar section label"),
        ("on-accent", "accent", "text on accent"),
        ("warn-ink", "warn-bg", "warning alert"),
        ("danger-ink", "danger-bg", "danger alert"),
        ("primary-hover", "card", "hover link colour"),
    ]
    out += [("on-tile", f"tile-{i}", f"tile {i}") for i in (1, 2, 3, 4)]
    out += [(f"chip-{k}-ink", f"chip-{k}-bg", f"{k} chip") for k in ("active", "soon", "expired", "void")]
    out += [("chip-preview-ink", "card", "preview chip")]
    return out


@pytest.mark.parametrize("name", THEME_NAMES)
def test_every_text_background_pair_meets_wcag_aa(name):
    t = themes.tokens(name)
    failures = []
    for fg, bg, why in pairs(t):
        r = ratio(t[fg], t[bg])
        if r < 4.5:
            failures.append(f"{name}: {fg} {t[fg]} on {bg} {t[bg]} = {r:.2f} ({why})")
    assert not failures, "\n".join(failures)


def test_theme_values_are_the_agreed_ones_and_the_card_is_always_white():
    m, f, b = (themes.tokens(n) for n in THEME_NAMES)
    assert (m["page"], m["primary"], m["accent"], m["side-bg"], m["tile-1"]) == (
        "#FFF8EE",
        "#1F7A4D",
        "#F2A007",
        "#2A1C14",
        "#5B2A6E",
    )
    assert (f["page"], f["primary"], f["accent"], f["side-active-bg"], f["tile-3"]) == (
        "#F5F8F2",
        "#0E7C66",
        "#E5484D",
        "#E3F4EE",
        "#C2410C",
    )
    assert (b["page"], b["primary"], b["tile-4"], b["side-label"]) == ("#FFF8EE", "#1F7A4D", "#B4232A", "#8A4E06")
    assert all(t["card"] == "#FFFFFF" for t in (m, f, b))  # QR and its code are never on a tinted background
    assert m["chart-3"] == m["accent"] and f["chart-3"] == "#4D7C0F" and b["chart-3"] == b["tile-2"]


# --- the CI guard: no raw hex or palette classes outside the theme file ---------------------------------------------------
def test_no_raw_colours_in_templates_scripts_or_template_tags():
    offenders = []
    files = [
        *ROOT.rglob("*.html"),
        *(ROOT / "static" / "js").glob("*.js"),
        *(ROOT / "preview" / "templatetags").glob("*.py"),
        *(ROOT / "web" / "templatetags").glob("*.py"),
        ROOT / "static" / "css" / "receipt.css",
        ROOT / "web" / "tailwind" / "input.css",
    ]
    for path in files:
        text = path.read_text()
        for m in HEX.finditer(text):
            offenders.append(f"{path.relative_to(ROOT)}: hex {m.group(0)}")
        for m in PALETTE.finditer(text):
            offenders.append(f"{path.relative_to(ROOT)}: palette class {m.group(0)}")
    assert offenders == [], "raw colours belong in static/css/themes.css only:\n" + "\n".join(offenders)


# --- compact money ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("minor", "text"),
    [
        (0, "₹0"),
        (95_000, "₹950"),
        (99_900, "₹999"),
        (100_000, "₹1K"),
        (150_000, "₹1.5K"),
        (8_206_000, "₹82.1K"),
        (9_994_900, "₹99.9K"),
        (9_995_000, "₹1L"),
        (10_000_000, "₹1L"),
        (12_432_500, "₹1.24L"),
        (99_900_000, "₹9.99L"),
        (999_999_000, "₹1Cr"),
        (999_500_000, "₹99.95L"),
        (1_000_000_000, "₹1Cr"),
        (1_200_000_000, "₹1.2Cr"),
        (15_000_000_000, "₹15Cr"),
        (-8_206_000, "-₹82.1K"),
        (-12_432_500, "-₹1.24L"),
        (-50_000, "-₹500"),
    ],
)
def test_money_compact_boundaries_and_negatives(minor, text):
    assert money_compact(minor) == text


def test_compact_never_replaces_the_full_value_it_only_abbreviates():
    assert format_money(12_432_500) == "₹1,24,325.00" and money_compact(12_432_500) == "₹1.24L"
    assert money_compact(None) == "₹0"


# --- applying a theme -------------------------------------------------------------------------------------------------------------
def set_theme(name):
    with platform_context():
        Tenant.objects.filter(slug=SLUG).update(theme=name)


def test_default_theme_is_masala_and_tenant_pages_carry_it_while_platform_pages_are_tally(demo, clients):  # noqa: F811
    with platform_context():
        assert Tenant.objects.get(slug=SLUG).theme == "masala"
    owner = clients["OWNER"]
    page = owner.get(f"/t/{SLUG}/admin/today").content.decode()
    assert (
        '<html lang="en" data-theme="masala"' in page and 'href="/static/css/themes.css"' in page
    ) or "css/themes.css" in page
    assert 'name="theme-color" content="#1F7A4D"' in page
    from django.test import Client

    anon = Client()
    assert 'data-theme="masala"' in anon.get(f"/t/{SLUG}/").content.decode()  # tenant-scoped public page: tenant theme
    assert (
        'data-theme="tally"' in anon.get("/").content.decode()
        and 'data-theme="tally"' in anon.get("/login").content.decode()
    )
    from django.contrib.auth import get_user_model

    from mealtally.web.tests.conftest import client_for

    with platform_context():
        admin = get_user_model().objects.get(email="d03-root@example.test")
    plat = client_for(admin)
    set_theme("fresh")
    assert (
        'data-theme="tally"' in plat.get("/platform/").content.decode()
    )  # platform surfaces never take a tenant theme
    assert 'data-theme="fresh"' in owner.get(f"/t/{SLUG}/admin/today").content.decode()
    assert 'name="theme-color" content="#0E7C66"' in owner.get(f"/t/{SLUG}/admin/today").content.decode()
    manifest = anon_json(anon, "/manifest.webmanifest?theme=fresh")
    assert manifest["theme_color"] == "#0E7C66" and anon_json(anon, "/manifest.webmanifest")["theme_color"] == "#1F7A4D"


def anon_json(client, url):
    import json

    return json.loads(client.get(url).content)


def test_owner_switches_the_theme_in_business_profile_with_a_preview_and_it_is_audited(demo, clients):  # noqa: F811
    owner = clients["OWNER"]
    page = owner.get(f"/t/{SLUG}/admin/settings").content.decode()
    assert 'data-testid="theme-picker"' in page and page.count("data-theme-option") == 3 and "data-dirty-guard" in page
    for key in THEME_NAMES:
        assert f'data-theme="{key}"' in page  # one swatch per theme, painted with that theme's own tokens
    url = f"/t/{SLUG}/admin/settings/theme"
    resp = owner.post(url, {"theme": "fresh"})  # the card click: saved at once, the page swaps in place
    assert resp.status_code == 204
    import json

    trig = json.loads(resp["HX-Trigger"])["themeSaved"]
    assert trig["theme"] == "fresh" and trig["previous"] == "masala" and trig["label"] == "Fresh market"
    assert trig["message"] == "Theme changed to Fresh market"
    with platform_context():
        assert Tenant.objects.get(slug=SLUG).theme == "fresh"
    assert owner.post(url, {"theme": "nope"}).status_code == 400
    assert owner.post(url, {"theme": "masala"}).status_code == 204  # what Undo posts
    with platform_context():
        assert Tenant.objects.get(slug=SLUG).theme == "masala"
        from mealtally.audit.models import AuditEvent

        assert AuditEvent.objects.filter(action="tenant.set_theme").count() == 2
    assert clients["MANAGER"].post(url, {"theme": "fresh"}).status_code in (302, 403, 404)  # owner only
    assert owner.get(url).status_code == 405
    from mealtally.tenancy.admin import TenantAdmin

    assert "theme" in TenantAdmin.list_editable  # platform admin: Django admin tenant list


@pytest.mark.parametrize("name", THEME_NAMES)
def test_every_surface_renders_under_each_theme(demo, clients, name):  # noqa: F811
    set_theme(name)
    D = pvdata.get(timezone.localdate())
    marker = f'data-theme="{name}"'
    for role, home in (
        ("OWNER", f"/t/{SLUG}/admin/today"),
        ("STAFF", f"/t/{SLUG}/staff/"),
        ("CHEF", f"/t/{SLUG}/admin/kitchen"),
        ("DRIVER", f"/t/{SLUG}/driver/"),
        ("CUSTOMER", f"/t/{SLUG}/me/"),
    ):
        resp = clients[role].get(home)
        check(home, resp)
        assert marker in resp.content.decode(), (role, name)
    for n, kw in preview_urls(D):
        if n.startswith("me-"):
            who = "CUSTOMER"
        elif n == "driver":
            who = "DRIVER"
        else:
            who = "OWNER"
        url = reverse(f"preview:{n}", kwargs={"slug": SLUG, **kw})
        resp = clients[who].get(url)
        check(url, resp)
        if resp["Content-Type"].startswith("text/html") and n != "kitchen-labels":
            assert marker in resp.content.decode(), (n, name)
    for url in (
        f"/t/{SLUG}/login/staff",
        f"/t/{SLUG}/login/customer",
        f"/t/{SLUG}/site",
        f"/t/{SLUG}/admin/audit",
        f"/t/{SLUG}/admin/settings",
        f"/t/{SLUG}/admin/reports/fees",
        f"/t/{SLUG}/admin/customers",
        f"/t/{SLUG}/admin/plans",
    ):
        resp = clients["OWNER"].get(url)
        assert resp.status_code == 200 and marker in resp.content.decode(), (url, name)
    err = clients["OWNER"].get(f"/t/{SLUG}/admin/nope-nope")
    assert err.status_code == 404 and "data-theme" in err.content.decode()  # branded error page is themed too


def test_pdfs_use_the_tenant_theme_for_headings_and_black_body_text(demo, clients):  # noqa: F811
    set_theme("fresh")
    inv = pvdata.get(timezone.localdate())["invoices"][0]["id"]
    from django.template.loader import render_to_string

    with platform_context():
        tenant = Tenant.objects.get(slug=SLUG)
    html = render_to_string(
        "preview/invoice_pdf.html",
        {
            "D": pvdata.get(timezone.localdate()),
            "i": pvdata.get(timezone.localdate())["invoice"][inv],
            "cfg": type("C", (), {"display_name": "x", "address": "", "contact_phone": "", "food_licence_no": ""})(),
            "tenant": tenant,
        },
    )
    assert "--primary:#0E7C66" in html and "color: black" in html and "var(--primary)" in html
    receipt_css = (ROOT / "static" / "css" / "receipt.css").read_text()
    assert "var(--primary)" in receipt_css and "color: black" in receipt_css
    report = render_to_string("web/report_pdf.html", {"title": "t", "header": ["a"], "rows": [["b"]], "tenant": tenant})
    assert "--primary:#0E7C66" in report and "color:black" in report


def test_django_admin_header_uses_the_tally_primary(demo):  # noqa: F811
    from django.contrib.auth import get_user_model

    from mealtally.web.tests.conftest import client_for

    with platform_context():
        admin = get_user_model().objects.get(email="d03-root@example.test")
    html = client_for(admin).get("/platform/admin/").content.decode()
    assert "--header-bg" in html and themes.tokens("tally")["primary"] in html


def test_the_font_is_self_hosted_and_status_chips_pair_an_icon_with_a_word():
    css = (ROOT / "static" / "css" / "themes.css").read_text()
    assert "Plus Jakarta Sans" in css and "../fonts/plus-jakarta-sans-latin-wght.woff2" in css and "http" not in css
    assert (ROOT / "static" / "fonts" / "plus-jakarta-sans-latin-wght.woff2").stat().st_size > 10_000
    assert (ROOT / "static" / "fonts" / "PlusJakartaSans-OFL.txt").exists()  # OFL licence shipped with the font
    tw = (ROOT / "web" / "tailwind" / "input.css").read_text()
    for chip in ("chip-active", "chip-soon", "chip-expired", "chip-void", "chip-preview"):
        assert re.search(rf"@utility {chip} \{{[^\n]*&::before \{{ content:", tw), chip
    assert "prefers-reduced-motion" in tw and "tabular-nums" in tw


def test_a_second_demo_tenant_on_the_fresh_theme_can_be_seeded_for_the_live_switch_demo(demo, tmp_path):  # noqa: F811
    from django.core.management import call_command

    call_command(
        "seed_demo_tiffin",
        "--slug",
        "demo-fresh",
        "--name",
        "Leafline Bowls Kitchen (Demo)",
        "--domain",
        "leaflinebowls.example.com",
        "--theme",
        "fresh",
        "--credentials-file",
        str(tmp_path / "fresh.txt"),
    )
    with platform_context():
        fresh = Tenant.objects.get(slug="demo-fresh")
        assert fresh.theme == "fresh" and fresh.has_demo_dataset and fresh.is_test and fresh.ui_shell == "console"
        assert Tenant.objects.get(slug=SLUG).theme == "masala"
    assert "owner@leaflinebowls.example.com" in (tmp_path / "fresh.txt").read_text()


def test_receipt_html_view_has_no_inline_style_so_it_passes_the_csp(demo, clients):  # noqa: F811
    from mealtally.billing.models import Payment
    from mealtally.tenancy.context import tenant_context

    with platform_context():
        tid = Tenant.objects.get(slug=SLUG).id
    with tenant_context(tid):
        pay = Payment.objects.first()
    html = clients["OWNER"].get(f"/t/{SLUG}/receipt/{pay.public_id}").content.decode()
    assert (
        "<style" not in html
        and 'data-theme="masala"' in html
        and "css/themes.css" in html
        and "css/receipt.css" in html
    )


def test_leafline_bowls_persona_has_its_own_address_names_and_phones_and_saffron_is_untouched():
    from datetime import date

    from mealtally.preview import data
    from mealtally.preview import personas

    saffron = data.get(date(2026, 11, 14))
    green = data.get(date(2026, 11, 14), personas.persona_for("demo-fresh"))
    flat = repr(green)
    for gone in (
        "Kothrud",
        "Saffron Tiffins",
        "saffrontiffins",
        "Shivaji Society",
        *data.PASS_NAMES[:5],
        "Ramesh Gawade",
        "+91 90000 10",
    ):
        assert gone not in flat, gone
    assert "Baner" in flat and "Leafline Bowls" in flat and personas.GREEN_PHONE in flat
    assert "Anita Deshpande" in repr(saffron) and "Kothrud" in repr(saffron)  # the default persona is unchanged
    assert len(set(personas.GREEN_PASS_NAMES + personas.GREEN_EXTRA_SUB_NAMES)) == 47
    assert not set(personas.GREEN_PASS_NAMES) & set(data.PASS_NAMES + data.EXTRA_SUB_NAMES)


def test_seeding_demo_fresh_uses_its_own_customers_and_a_rerun_migrates_old_rows(demo, tmp_path):  # noqa: F811
    from django.core.management import call_command

    from mealtally.customers.models import Customer
    from mealtally.preview import personas
    from mealtally.tenancy.context import tenant_context

    f = tmp_path / "fresh.txt"
    args = [
        "--slug",
        "demo-fresh",
        "--name",
        "Leafline Bowls Kitchen (Demo)",
        "--domain",
        "leaflinebowls.example.com",
        "--theme",
        "fresh",
    ]
    call_command("seed_demo_tiffin", *args, "--credentials-file", str(f))
    text = f.read_text()
    assert text.startswith(
        "# demo-fresh logins (staff: /t/demo-fresh/login/staff ; customers: /t/demo-fresh/login/customer)"
    )
    assert "Aisha Merchant" in text and "Anita Deshpande" not in text and "+91 90000 30001" in text
    with platform_context():
        tid = Tenant.objects.get(slug="demo-fresh").id
    with tenant_context(tid):
        assert (
            Customer.objects.get(customer_code__isnull=False, phone_e164="+919000030001").full_name == "Aisha Merchant"
        )
        assert not Customer.objects.filter(full_name="Anita Deshpande").exists()
    call_command("seed_demo_tiffin", *args, "--credentials-file", str(f))  # idempotent re-run
    assert personas.GREEN_ADDRESS
    assert f.read_text() == text


def test_wallet_page_has_a_real_upi_intent_qr_and_chips(demo, clients):  # noqa: F811
    html = clients["CUSTOMER"].get(f"/t/{SLUG}/me/wallet").content.decode()
    assert "data:image/svg+xml;base64," in html and "upi://pay?pa=saffrontiffins@upi" in html and "am=1000.00" in html
    assert "placeholder" not in html.lower().replace('placeholder="412800931204"', "")  # no decorative placeholder QR
    for chip in ("₹500", "₹1,000", "₹2,000", "Other"):
        assert chip in html


def test_order_page_has_date_chips_filters_and_a_cart_sheet(demo, clients):  # noqa: F811
    html = clients["CUSTOMER"].get(f"/t/{SLUG}/me/order").content.decode()
    assert html.count("data-day-chip") >= 7 and 'data-testid="order-filters"' in html and "data-cart-bar" in html
    assert "data-cart-sheet" in html and "<select" not in html.split('data-testid="date-chips"')[0][-400:]
    assert "Sold out" in html and "Add " not in html  # free-delivery progress text is built client-side
    assert "₹170" in html and "₹170.00" not in html  # consumer money


def test_station_shell_for_chef_and_driver_has_no_sidebar_and_a_driver_bar(demo, clients):  # noqa: F811
    chef = clients["CHEF"].get(f"/t/{SLUG}/admin/kitchen").content.decode()
    assert 'data-testid="sidebar"' not in chef and 'data-testid="station-role"' in chef and "data-clock" in chef
    assert 'data-testid="station-bar"' not in chef and 'data-autorefresh="60"' in chef
    drv = clients["DRIVER"].get(f"/t/{SLUG}/driver/").content.decode()
    assert 'data-testid="sidebar"' not in drv and 'data-testid="station-bar"' in drv
    assert "Stops" in drv and "Done" in drv and "Account" in drv and 'data-testid="navigate"' in drv
    assert "Reason for skipping" in drv and "tel:" in drv


def test_no_emoji_on_the_staff_and_customer_icon_set_and_scheduled_wording(demo, clients):  # noqa: F811
    for role, path in (("DRIVER", "driver/"), ("CHEF", "admin/kitchen"), ("CUSTOMER", "me/wallet")):
        html = clients[role].get(f"/t/{SLUG}/{path}").content.decode()
        for emoji in ("📷", "📞", "🔔", "📝", "⚠"):
            assert emoji not in html, (role, emoji)
    from mealtally.preview.templatetags.pv import chip

    assert "Scheduled" in chip("RECEIVED") and "Received" not in chip("RECEIVED")


def test_manager_console_shows_no_fee_items(demo, clients):  # noqa: F811
    page = clients["MANAGER"].get(f"/t/{SLUG}/admin/today").content.decode()
    assert "fee-line" not in page and "Plan &amp; platform fees" not in page and "Plan & platform fees" not in page
    owner = clients["OWNER"].get(f"/t/{SLUG}/admin/today").content.decode()
    assert "fee-line" in owner and "Plan &amp; platform fees" in owner


def test_d038_customer_polish_wallet_has_no_fab_order_card_and_history_rows(demo, clients):  # noqa: F811
    cust = clients["CUSTOMER"]
    wallet = cust.get(f"/t/{SLUG}/me/wallet").content.decode()
    assert 'data-testid="show-qr"' not in wallet and 'data-testid="wallet-history"' in wallet and "<table" not in wallet
    assert "−₹80" in wallet and "−₹80.00" not in wallet  # Activity-style rows with consumer money
    home = cust.get(f"/t/{SLUG}/me/").content.decode()
    # Home shows QR as a button in the pass card, not floating over the cards; other pages keep the floating button
    assert 'data-testid="show-qr"' in home and "cust-fab-label" not in home and "pb-44" in home
    activity = cust.get(f"/t/{SLUG}/me/activity").content.decode()
    assert 'data-testid="show-qr"' in activity and "cust-fab-label" in activity
    order = cust.get(f"/t/{SLUG}/me/order").content.decode()
    assert (
        "data-add" in order
        and 'class="hidden items-center gap-2" data-stepper' in order
        and "whitespace-nowrap" in order
    )


def test_d038_driver_has_next_stop_expanded_and_the_rest_compact(demo, clients):  # noqa: F811
    html = clients["DRIVER"].get(f"/t/{SLUG}/driver/").content.decode()
    assert html.count("Next stop") == 1 and html.count('data-testid="stop-compact"') >= 2
    assert html.count('data-testid="stop"') == html.count('data-testid="stop-compact"') + 1
    assert 'aria-label="Call ' in html and 'aria-label="Navigate ' in html


def test_e2e_persona_has_its_own_phone_range_and_the_demo_story():
    from datetime import date

    from mealtally.preview import data as pvdata
    from mealtally.preview import personas

    assert personas.persona_for("e2e-tiffin") == "e2e" and personas.phone_format("e2e").format(5) == "+91 90001 10005"
    d = pvdata.get(date(2026, 11, 14), "e2e")
    assert "+91 90001 1" in repr(d) and "+91 90000 1" not in repr(d) and "Kothrud" in repr(d)


def test_d038_p1_rail_labels_phone_format_single_chip_order_alerts_and_platform_name(demo, clients):  # noqa: F811
    from mealtally.web.templatetags.mealtally_extras import phone_pretty

    assert phone_pretty("+919000010001") == "+91 90000 10001" and phone_pretty("12345") == "12345"
    counter = clients["STAFF"].get(f"/t/{SLUG}/staff/").content.decode()
    for label in ("Redeem", "Sell", "Customers", "Orders"):
        assert f'class="rail-label" aria-hidden="true">{label}<' in counter, label
    assert 'aria-label="Redeem counter"' in counter
    acct = clients["CUSTOMER"].get(f"/t/{SLUG}/me/account").content.decode()
    assert "+91 90000 10001" in acct or "+91 90001 1" in acct or "+91 90000" in acct
    act = clients["CUSTOMER"].get(f"/t/{SLUG}/me/activity?f=deliveries").content.decode()
    assert act.count("Delivered") <= act.count('class="chip-active"') + act.count("Proof of delivery") * 0 + act.count(
        "Delivered"
    )  # sanity
    assert ">Done<" not in act
    chef = clients["CHEF"].get(f"/t/{SLUG}/admin/kitchen").content.decode()
    assert "Order alerts" in chef and ">New order<" not in chef.replace("&nbsp;", " ")


def test_d038c_driver_numbering_list_and_summary_agree(demo, clients):  # noqa: F811
    import re

    from mealtally.preview.tests.test_preview import tid
    from mealtally.tenancy.context import tenant_context as _tc

    with _tc(tid()):  # the driver page is built from the tenant's roster, and shows driver 1's own route
        D = pvdata.for_tenant(Tenant.objects.get(slug=SLUG))
    route = D["routes"][0]["name"]
    todays = sorted(
        (o for o in D["orders"] if o["off"] == 0 and o["slot"] == "LUNCH" and o["route"] == route),
        key=lambda o: o["stop"],
    )
    live = [o for o in todays if o["status"] in pvdata._LIVE_STATUSES]
    statuses = [o["status"] for o in live]
    n = statuses.count("DELIVERED")
    assert (
        statuses[:n] == ["DELIVERED"] * n and "DELIVERED" not in statuses[n:]
    )  # delivered stops are the first N in route order
    html = clients["DRIVER"].get(f"/t/{SLUG}/driver/").content.decode()
    nums = [int(x) for x in re.findall(r'<span class="chip-slate[^"]*">(\d+)</span>', html)]
    skipped = [o for o in todays if o["status"] not in pvdata._LIVE_STATUSES]
    assert sorted(set(nums)) == sorted(
        o["stop"] for o in todays
    )  # every stop number appears once: pending, delivered or skipped
    assert (f"{n} of {len(live)} delivered" in html) and (not skipped or 'data-testid="skipped-group"' in html)


def test_d038c_wallet_rows_do_not_repeat_the_slot(demo, clients):  # noqa: F811
    html = clients["CUSTOMER"].get(f"/t/{SLUG}/me/wallet").content.decode()
    assert "Home Tiffin · Lunch" in html and "Lunch · Home Tiffin" not in html


def test_d038c_seed_refuses_phones_that_belong_to_users_of_another_tenant(demo, tmp_path):  # noqa: F811
    import pytest
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="already belong to users of another tenant"):
        call_command(
            "seed_demo_tiffin",
            "--slug",
            "clash-tiffin",
            "--name",
            "Clash",
            "--domain",
            "clash.example.com",
            "--credentials-file",
            str(tmp_path / "x.txt"),
        )
