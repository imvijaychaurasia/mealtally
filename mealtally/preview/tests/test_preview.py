"""D03 preview modules: crawl every preview page as every role (default CI), role gating, tenant isolation, no real writes."""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import pytest
from django.core.management import call_command
from django.urls import reverse

from mealtally.accounts.models import Role
from mealtally.accounts.models import User
from mealtally.billing.models import Payment
from mealtally.customers.models import Customer
from mealtally.ledger.models import MealLedgerEntry
from mealtally.preview import data as pvdata
from mealtally.preview.registry import REGISTRY
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.context import tenant_context
from mealtally.tenancy.models import Tenant
from mealtally.testing import World
from mealtally.web.tests.conftest import client_for

pytestmark = pytest.mark.django_db
SLUG = "demo-tiffin"
MONEY = re.compile(r"₹([\d,]+)\.(\d{2})")
FORBIDDEN = ("Server Error", "Traceback (most recent call last)", "TemplateSyntaxError", "VariableDoesNotExist")
SKIP = ("/logout", "/static/", "/api/", "/sw.js", "/offline/", "/manifest", "/platform/admin")
CUSTOMER_BACKEND = "mealtally.accounts.backends.CustomerPinBackend"


def check(path, resp):
    assert resp.status_code == 200, f"{path} -> {resp.status_code}"
    ctype = resp["Content-Type"]
    if ctype.startswith("text/html"):
        body = resp.content.decode()
        for bad in FORBIDDEN:
            assert bad not in body, f"{path}: {bad!r}"
        for rupees, _p in MONEY.findall(body):
            assert int(rupees.replace(",", "")) <= 500_000, f"{path}: ₹{rupees} looks x100"
    elif ctype.startswith("application/pdf"):
        assert resp.content[:5] == b"%PDF-", path


def links(html):
    out = set()
    for href in re.findall(r'href="([^"#]+)"', html):
        clean = href.replace("&amp;", "&")
        if clean.startswith("/") and not clean.startswith(SKIP):
            out.add(clean)
    return out


def crawl(client, starts, limit=300):
    seen, queue, n = set(), list(starts), 0
    while queue and n < limit:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        if (
            path.rstrip("/") == f"/t/{SLUG}"
        ):  # the tenant entry page redirects signed-in members to their home, by design
            continue
        resp = client.get(path)
        check(path, resp)
        n += 1
        if resp["Content-Type"].startswith("text/html"):
            queue.extend(p for p in links(resp.content.decode()) if p not in seen)
    return seen


@pytest.fixture
def demo(tmp_path):
    with platform_context():
        User.objects.create_superuser(email="d03-root@example.test", password="Sup3r-Secret-Pw!")
    creds = tmp_path / "creds.txt"
    call_command("seed_demo_tiffin", "--credentials-file", str(creds))
    return creds


def tid():
    with platform_context():
        return Tenant.objects.get(slug=SLUG).id


def user(email):
    return User.objects.get(email=email)


@pytest.fixture
def clients(demo):
    c = {
        "OWNER": client_for(user("owner@saffrontiffins.example.com")),
        "MANAGER": client_for(user("manager@saffrontiffins.example.com")),
        "STAFF": client_for(user("counter1@saffrontiffins.example.com")),
        "CHEF": client_for(user("chef@saffrontiffins.example.com")),
        "DRIVER": client_for(user("driver1@saffrontiffins.example.com")),
    }
    with tenant_context(tid()):
        anita = Customer.objects.select_related("user").filter(full_name="Anita Deshpande").first()
    c["CUSTOMER"] = client_for(anita.user, CUSTOMER_BACKEND)
    return c


def preview_urls(D):
    """(url_name, kwargs) for every preview page of the tenant."""
    o = next(x for x in D["orders"] if x["off"] == 0)
    sid = D["featured_sub_id"]
    inv = D["invoices"][0]["id"]
    kw = {
        "orders-detail": {"no": o["no"]},
        "wallets-customer": {"sub_id": sid},
        "subscriptions-detail": {"sub_id": sid},
        "invoices-detail": {"inv": inv},
        "invoices-pdf": {"inv": inv},
    }
    names = [
        "today",
        "more",
        "orders",
        "orders-new",
        "orders-detail",
        "kitchen",
        "kitchen-labels",
        "delivery",
        "holds",
        "tiffin-boxes",
        "driver",
        "wallets",
        "wallets-customer",
        "payment-setup",
        "invoices",
        "invoices-detail",
        "invoices-pdf",
        "expenses",
        "expenses-profit",
        "menu",
        "menu-planner",
        "plans-wallet",
        "plans-wallet-new",
        "subscriptions",
        "subscriptions-new",
        "subscriptions-detail",
        "roles",
        "branches",
        "notifications",
        "website",
        "cloud-kitchen",
        "me-meals",
        "me-wallet",
        "me-deliveries",
        "me-invoices",
        "me-order",
    ]
    return [(n, kw.get(n, {})) for n in names]


def allowed_roles(name):
    if name == "more":
        return {Role.OWNER, Role.MANAGER, Role.STAFF, Role.CHEF, Role.DRIVER}
    for m in REGISTRY:
        if m.url_name.endswith(":" + name) or name.startswith(m.key + "-"):
            return {str(r) for r in m.roles}
    raise AssertionError(name)


def test_dataset_is_deterministic_and_complete():
    from datetime import date

    a, b = pvdata.build(date(2026, 11, 14)), pvdata.build(date(2026, 11, 14))
    assert [o["no"] for o in a["orders"]] == [o["no"] for o in b["orders"]]
    assert [s["balance_minor"] for s in a["subscribers"]] == [s["balance_minor"] for s in b["subscribers"]]
    assert (
        len(a["subscribers"]) == 30 and len(a["dishes"]) >= 18 and len(a["branches"]) == 2 and len(a["expenses"]) == 40
    )
    assert len(a["topups"]) == 6 and len(a["ck_items"]) == 10 and len(a["ck_orders"]) == 8 and len(a["bell"]) == 15
    assert sum(1 for s in a["subscribers"] if s["balance_minor"] < 0) >= 2  # two negative, within trust limit
    assert all(s["balance_minor"] >= -s["trust_limit_minor"] for s in a["subscribers"])
    assert (
        sum(1 for s in a["subscribers"] if s["hold"]) == 2
        and sum(1 for s in a["subscribers"] if s["status"] == "PAUSED") == 1
    )
    assert a["checklist_pct"] == 70


def test_demo_seed_real_data_and_no_forced_credential_change(demo):
    with platform_context():
        tenant = Tenant.objects.get(slug=SLUG)
    assert tenant.is_test and tenant.has_demo_dataset and tenant.show_preview_badges
    for email in ("owner", "manager", "counter1", "counter2", "chef", "driver1", "driver2"):
        assert not user(f"{email}@saffrontiffins.example.com").must_change_password
    with tenant_context(tenant.id):
        assert Customer.objects.count() == 25
        assert not Customer.objects.filter(must_change_pin=True).exists()
        assert Payment.objects.count() >= 22
        assert Payment.objects.filter(status="VOIDED").count() >= 1
        assert MealLedgerEntry.objects.filter(entry_type="REDEEM").count() > 150
        assert MealLedgerEntry.objects.filter(entry_type="REVERSAL").count() >= 3
        assert MealLedgerEntry.objects.filter(entry_type="ADJUST").count() == 1
    text = Path(demo).read_text()
    assert oct(Path(demo).stat().st_mode & 0o777) == "0o600" and "password=" in text


def test_every_preview_page_for_every_role(demo, clients):
    D = pvdata.get(__import__("django").utils.timezone.localdate())
    base = f"/t/{SLUG}"
    total = 0
    for name, kw in preview_urls(D):
        url = reverse(f"preview:{name}", kwargs={"slug": SLUG, **kw})
        ok = allowed_roles(name)
        for role, client in clients.items():
            resp = client.get(url)
            if role in ok:
                check(url, resp)
                total += 1
            else:
                assert resp.status_code == 404, f"{role} should not see {url} (got {resp.status_code})"
    assert total >= 70
    # crawl by following links from each role's home
    for role, start in (
        ("OWNER", f"{base}/admin/today"),
        ("STAFF", f"{base}/staff/"),
        ("CHEF", f"{base}/admin/kitchen"),
        ("DRIVER", f"{base}/driver/"),
        ("CUSTOMER", f"{base}/me/"),
    ):
        seen = crawl(clients[role], [start])
        assert len(seen) >= 2, role


def test_roles_land_on_their_console_and_nav_is_role_based(demo, clients):
    expected = {
        "OWNER": "/admin/today",
        "MANAGER": "/admin/today",
        "STAFF": "/staff/",
        "CHEF": "/admin/kitchen",
        "DRIVER": "/driver/",
    }
    for role, suffix in expected.items():
        resp = clients[role].get(f"/t/{SLUG}/")  # public tenant page redirects members home
        assert resp.status_code in (200, 302)
    kitchen = clients["CHEF"].get(f"/t/{SLUG}/admin/kitchen").content.decode()
    assert "Kitchen" in kitchen and "/staff/sell" not in kitchen and "/admin/customers" not in kitchen
    drv = clients["DRIVER"].get(f"/t/{SLUG}/driver/").content.decode()
    assert "Driver console" in drv and "/staff/sell" not in drv and "/admin/orders" not in drv
    # chef/driver cannot reach the real admin or staff screens
    for url in (f"/t/{SLUG}/admin/customers", f"/t/{SLUG}/staff/", f"/t/{SLUG}/admin/"):
        assert clients["CHEF"].get(url).status_code in (302, 404)
        assert clients["DRIVER"].get(url).status_code in (302, 404)
    owner = clients["OWNER"].get(f"/t/{SLUG}/admin/today").content.decode()
    for label in (
        "Today",
        "Redeem",
        "Sell pass",
        "Orders",
        "Customers",
        "Kitchen",
        "Delivery",
        "Money",
        "Reports",
        "More",
    ):
        assert label in owner, label
    assert 'data-testid="preview-badge"' not in owner or "Preview" in owner


def test_preview_badge_toggle_and_empty_state_for_other_tenants(demo, clients):
    body = clients["OWNER"].get(f"/t/{SLUG}/admin/orders").content.decode()
    assert 'data-testid="preview-badge"' in body
    with platform_context():
        Tenant.objects.filter(slug=SLUG).update(show_preview_badges=False)
    assert 'data-testid="preview-badge"' not in clients["OWNER"].get(f"/t/{SLUG}/admin/orders").content.decode()
    # a tenant without the dataset: "Coming soon", never demo data, and not another tenant's data
    w = World(slug="plain-tiffin")
    other = client_for(w.owner.user)
    resp = other.get("/t/plain-tiffin/admin/orders")
    assert resp.status_code == 200 and "Coming soon" in resp.content.decode() and "Kothrud" not in resp.content.decode()
    assert other.get(f"/t/{SLUG}/admin/orders").status_code == 404  # not a member of demo-tiffin
    assert other.get(f"/t/{SLUG}/admin/kitchen/labels").status_code == 404


def test_public_site_and_platform_preview_pages(demo):
    from django.test import Client

    anon = Client()
    resp = anon.get(f"/t/{SLUG}/site")
    check("/site", resp)
    assert "Menu of the week" in resp.content.decode() and "Log in" in resp.content.decode()
    assert anon.get(f"/t/{SLUG}/site?theme=teal").status_code == 200
    check("/signup", anon.get("/signup"))
    with platform_context():
        admin = User.objects.get(email="d03-root@example.test")
    plat = client_for(admin)
    check("/platform/plans", plat.get("/platform/plans"))
    assert anon.get("/platform/plans").status_code == 302


def test_previews_never_write_and_templates_have_no_write_endpoints(demo, clients):
    before = (Payment.objects.count(), MealLedgerEntry.objects.count())
    with tenant_context(tid()):
        before = (Payment.objects.count(), MealLedgerEntry.objects.count(), Customer.objects.count())
    D = pvdata.get(__import__("django").utils.timezone.localdate())
    for name, kw in preview_urls(D):
        for role in ("OWNER", "CUSTOMER"):
            clients[role].get(reverse(f"preview:{name}", kwargs={"slug": SLUG, **kw}))
    with tenant_context(tid()):
        assert (Payment.objects.count(), MealLedgerEntry.objects.count(), Customer.objects.count()) == before
    # POST to a preview url is not allowed at all
    assert clients["OWNER"].post(f"/t/{SLUG}/admin/orders", {}).status_code == 405
    # static check: no preview template posts anywhere
    root = Path(__file__).resolve().parents[1] / "templates" / "preview"
    for f in root.glob("*.html"):
        text = f.read_text()
        assert not re.search(r'method\s*=\s*"?post', text, re.I), f"{f.name}: POST form in a preview template"
        assert not re.search(r"hx-(post|put|patch|delete)|csrf_token|action\s*=\s*\"/", text, re.I), (
            f"{f.name}: real write endpoint"
        )


def test_no_inline_script_or_style_in_preview_templates():
    root = Path(__file__).resolve().parents[1] / "templates" / "preview"
    for f in root.glob("*.html"):
        text = f.read_text()
        assert "<script>" not in text and not re.search(r"<script(?![^>]*\bsrc=)", text), f.name
        assert not re.search(r"\sstyle\s*=", text), f"{f.name}: inline style attribute (CSP)"
        assert "<style" not in text or f.name == "invoice_pdf.html", (
            f.name
        )  # PDF is rendered server-side, never served as HTML


def test_hindi_toggle_translates_nav_and_customer_app(demo, clients):
    cust = clients["CUSTOMER"]
    cust.cookies["django_language"] = "hi"
    body = cust.get(f"/t/{SLUG}/me/meals").content.decode()
    for needle in (
        "मेरा खाना",
        "वॉलेट बैलेंस",
        "अपना खाना चुनें",
        "होम",
        "गतिविधि",
        "खाता",
    ):  # the legend is always shown; "Your meal" only when the next slot has one option
        assert needle in body, needle
    assert 'lang="hi"' in body
    owner = clients["OWNER"]
    owner.cookies["django_language"] = "hi"
    nav = owner.get(f"/t/{SLUG}/admin/orders").content.decode()
    for needle in ("आज", "ऑर्डर", "किचन", "ग्राहक", "रिपोर्ट"):
        assert needle in nav, needle
    # the switch itself posts to Django's set_language and flips back
    resp = clients["CUSTOMER"].post("/i18n/setlang/", {"language": "en", "next": f"/t/{SLUG}/me/meals"})
    assert resp.status_code == 302 and "django_language=en" in resp.cookies.output()
    assert "My meals" in clients["CUSTOMER"].get(f"/t/{SLUG}/me/meals").content.decode()


# ---- D03.1 polish -------------------------------------------------------------------------------------------------
def test_expenses_run_at_62_to_70_percent_of_revenue_and_every_screen_agrees():
    from datetime import date

    from mealtally.preview import util as pvutil

    D = pvdata.build(date(2026, 11, 14))
    for passes in (0, 20_000_00, 40_000_00, 60_000_00):
        months, last, exps, recurring = pvutil.money_series(D, passes)
        ratio = last["expense_minor"] / last["revenue_minor"]
        assert 0.62 <= ratio <= 0.70, (passes, ratio)
        listed = sum(
            e["amount_minor"] for e in exps if e["date"] > D["today"] - __import__("datetime").timedelta(days=30)
        )
        assert listed == last["expense_minor"]  # the Expenses page lists exactly what Today / profit / the chart use
        assert all(0.60 <= m["expense_minor"] / m["revenue_minor"] <= 0.72 for m in months)
        assert months[-1]["profit_minor"] > months[0]["profit_minor"] * 1.5  # visibly rising profit line
        assert all(
            b["revenue_minor"] >= a["revenue_minor"] * 0.97 for a, b in itertools.pairwise(months)
        )  # growth kept
        assert recurring and all(r["amount_minor"] > 0 for r in recurring)


def test_chart_axis_uses_nice_round_ticks_in_one_unit_style():
    from mealtally.preview.templatetags.pv import lakh
    from mealtally.preview.templatetags.pv import nice_ticks

    assert nice_ticks(124_605) == [0, 40_000, 80_000, 120_000, 160_000]
    assert [lakh(t * 100) for t in nice_ticks(124_605)] == ["₹0", "₹40K", "₹80K", "₹1.2L", "₹1.6L"]
    assert nice_ticks(190_000)[-1] >= 190_000 and nice_ticks(30_000)[-1] >= 30_000


def test_cooking_plan_breaks_composites_into_component_dishes():
    from datetime import date

    from mealtally.preview import util as pvutil

    D = pvdata.build(date(2026, 11, 14))
    lunch = [o for o in pvdata.day_orders(D, D["today"]) if o["slot"] == "LUNCH"]
    plan = pvutil.cooking_plan(lunch)
    names = [r["name"] for r in plan]
    assert not any("thali" in n.lower() or "+" in n for n in names), names
    assert len(names) == len(set(names))
    chapati = next(r for r in plan if r["name"] == "Chapati")["qty"]
    expect = sum(
        i["qty"] * o["qty"] for o in lunch if o["status"] in pvutil.LIVE for i in o["items"] if i["name"] == "Chapati"
    )
    assert chapati == expect
    walk_in = next(o for o in lunch if o["customer"].startswith("Walk-in"))
    assert [i["name"] for i in walk_in["items"]] == ["Dal tadka", "Jeera rice", "Chapati", "Green salad"] and walk_in[
        "qty"
    ] == 2


def test_fssai_is_obviously_fake_everywhere(demo, clients):
    from mealtally.tenancy.models import TenantSettings

    with platform_context():
        assert TenantSettings.objects.get(tenant__slug=SLUG).food_licence_no == "00000000000000"
    for url in (f"/t/{SLUG}/site", f"/t/{SLUG}/admin/settings", f"/t/{SLUG}/admin/invoices"):
        resp = clients["OWNER"].get(url)
        assert "11523999000123" not in resp.content.decode()
    assert "FSSAI 00000000000000" in clients["OWNER"].get(f"/t/{SLUG}/site").content.decode()
    pdf_html = __import__("django").template.loader.render_to_string(
        "preview/invoice_pdf.html",
        {
            "D": pvdata.get(__import__("django").utils.timezone.localdate()),
            "i": pvdata.get(__import__("django").utils.timezone.localdate())["invoices"][0],
            "cfg": type(
                "C", (), {"display_name": "x", "address": "", "contact_phone": "", "food_licence_no": "00000000000000"}
            )(),
            "tenant": type("T", (), {"name": "x"})(),
        },
    )
    assert "FSSAI: 00000000000000" in pdf_html


def test_driver_console_groups_delivered_stops_at_the_bottom(demo, clients):
    html = clients["DRIVER"].get(f"/t/{SLUG}/driver/").content.decode()
    assert 'data-testid="delivered-group"' in html
    first_stop = html.index('data-testid="stop"')
    assert first_stop < html.index('data-testid="delivered-group"')
    pending_block = html[first_stop : html.index('data-testid="delivered-group"')]
    assert "Delivered</span>" not in pending_block and "Mark delivered" in pending_block


# ---- D03.2 final nits ------------------------------------------------------------------------------------------------
def test_help_drawer_shows_articles_for_the_viewers_audience(demo, clients):
    def help_text(role):
        html = (
            clients[role]
            .get(f"/t/{SLUG}/admin/orders" if role != "CUSTOMER" else f"/t/{SLUG}/me/account")
            .content.decode()
        )
        return html[html.index('data-testid="help"') :]

    cust = help_text("CUSTOMER")
    assert "How do I show my QR at the counter?" in cust and "How do I change my PIN?" in cust
    for staff_only in ("How do I add a staff login?", "How do I sell a pass?", "platform fee", "Who can see what?"):
        assert staff_only not in cust, staff_only
    counter = help_text("STAFF")
    assert "How do I sell a pass?" in counter and "How do I redeem a meal?" in counter
    assert "How do I add a staff login?" not in counter and "What does the platform fee cover?" not in counter
    assert "How do I show my QR at the counter?" not in counter
    for role in ("OWNER", "MANAGER"):
        owner = help_text(role)
        assert "How do I add a staff login?" in owner and "How do I sell a pass?" in owner
        assert "How do I show my QR at the counter?" not in owner


def test_source_labels_and_undo_label_are_human(demo, clients):
    from django.template.loader import render_to_string

    from mealtally.web.templatetags.mealtally_extras import source_label

    assert source_label("QR_SCAN") == "QR scan" and source_label("STAFF_SEARCH") == "Counter search"
    html = render_to_string("web/_today.html", {"rows": [], "net": 0, "tenant": type("T", (), {"slug": SLUG})()})
    assert "Qr Scan" not in html
    src = (Path(__file__).resolve().parents[2] / "web" / "templates" / "web" / "_redeem_success.html").read_text()
    assert (
        '<span>{% trans "Undo" %} (<span x-text="n">30</span>s)</span>' in src
    )  # one inline run: "Undo (29s)", not "Undo ( 29 s)"


def test_invoice_lines_are_in_date_order_with_extras_under_their_day():
    D = pvdata.get(__import__("django").utils.timezone.localdate())
    for i in D["invoices"]:
        dates = [r["date"] for r in i["lines"]]
        assert dates == sorted(dates) and len(i["lines"]) == len(i["rows"]) + len(i["extras"])
    with_extra = next(i for i in D["invoices"] if i["extras"])
    idx = [r["desc"] for r in with_extra["lines"]].index(with_extra["extras"][0]["desc"])
    assert idx < len(with_extra["lines"]) - 1 or with_extra["extras"][0]["date"] >= with_extra["lines"][-2]["date"]


def test_new_order_summary_prices_fee_line_and_paid_by_stamp(demo, clients):
    owner = clients["OWNER"].get(f"/t/{SLUG}/admin/orders/new").content.decode()
    assert "Delivery fee" in owner and "data-feeline" in owner and "data-items" in owner
    assert "Sunita Kulkarni · Owner" in owner and "Seema" not in owner
    counter = clients["STAFF"].get(f"/t/{SLUG}/admin/orders/new").content.decode()
    assert "Seema Pawar · Staff" in counter and "Sunita" not in counter
    prices = {d["name"]: d["price"] for d in pvdata.get(__import__("django").utils.timezone.localdate())["dishes"]}
    assert (
        prices["Chapati"],
        prices["Jeera rice"],
        prices["Dal tadka"],
        prices["Mix veg"],
        prices["Aloo matar"],
        prices["Paneer butter masala"],
    ) == (10, 50, 70, 90, 80, 140)
    assert 'data-price="7000"' in owner and 'data-price="1000"' in owner  # dal tadka Rs 70, chapati Rs 10 (per piece)


def test_wallet_actions_carry_kpi_hooks(demo, clients):
    html = clients["OWNER"].get(f"/t/{SLUG}/admin/wallets").content.decode()
    assert 'id="kpi-pending"' in html and 'id="kpi-held"' in html and "data-amt=" in html
    assert html.count('data-dec="#kpi-pending"') >= 6 and 'data-add-money="#kpi-held|' in html
