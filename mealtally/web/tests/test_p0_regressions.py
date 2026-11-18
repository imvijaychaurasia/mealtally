# SPDX-License-Identifier: AGPL-3.0-only
"""Regressions: money x100, fee totals vs lines, audit-log 500, unbranded error pages."""

from __future__ import annotations

import pathlib
import re
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from mealtally.billing import fees
from mealtally.billing import services as billing
from mealtally.common.country import mask_phone
from mealtally.common.money import format_money
from mealtally.common.money import per_meal as per_meal_price
from mealtally.reports import services as reports
from mealtally.tenancy.context import platform_context
from mealtally.testing import World
from mealtally.testing import buy
from mealtally.testing import make_customer

from .conftest import client_for

pytestmark = pytest.mark.django_db
ROOT = pathlib.Path(__file__).resolve().parents[2]


# ---- money ------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("minor", "text"),
    [
        (0, "₹0.00"),
        (99, "₹0.99"),
        (150000, "₹1,500.00"),
        (9999999, "₹99,999.99"),
        (15000000, "₹1,50,000.00"),
        (123456789, "₹12,34,567.89"),
        (100000000, "₹10,00,000.00"),
        (-250000, "-₹2,500.00"),
    ],
)
def test_format_money_uses_indian_grouping(minor, text):
    assert format_money(minor) == text


def test_per_meal_and_masking_helpers():
    assert per_meal_price(150000, 30) == "₹50" and per_meal_price(100000, 30) == "₹33.33" and per_meal_price(5, 0) == ""
    assert mask_phone("+919000000002") == "••••• 0002"


def test_no_template_renders_a_minor_value_without_the_inr_filter():
    """The x100 bug class: every `*_minor` in a template must be piped through |money."""
    offenders = []
    for path in ROOT.rglob("*.html"):
        text = path.read_text()
        for m in re.finditer(r"[\w.]*minor\w*", text):
            if (
                not text[m.end() :].lstrip().startswith(("|money", "|money_class", "|signed_inr", "|raw_amount"))
            ):  # money_class -> a CSS class only
                offenders.append(f"{path.relative_to(ROOT)}: {m.group(0)}")
    assert offenders == []


def test_1500_rupee_plan_reads_1500_everywhere_not_150000():
    w = World(slug="p01money")
    u = f"/t/{w.tenant.slug}"
    owner, staff = client_for(w.owner.user), client_for(w.staff.user)
    cust = client_for(w.customer.user, "mealtally.accounts.backends.CustomerPinBackend")
    with w.ctx():
        w.customer.must_change_pin = False
        w.customer.save()
    pages = {
        "plans": owner.get(u + "/admin/plans"),
        "customer detail": owner.get(f"{u}/admin/customers/{w.customer.public_id}"),
        "sell picker": staff.get(u + "/staff/sell"),
        "customer payments": cust.get(u + "/me/payments"),
        "receipt": owner.get(f"{u}/receipt/{w.recorded.payment.public_id}"),
        "dashboard": owner.get(u + "/admin/"),
    }
    for name, resp in pages.items():
        body = resp.content.decode()
        assert resp.status_code == 200, name
        assert "150,000" not in body and "1,50,000" not in body, f"x100 amount on {name}"
        if name != "dashboard":
            assert "₹1,500.00" in body, name


# ---- fee totals == lines -------------------------------------------------------------------------------
def _months_back(tenant, n):
    y, m = fees.local_month(tenant)
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return y, m


def test_fee_headline_equals_sum_of_lines_with_backdated_payments_and_a_void():
    w = World(buy_pass=False)
    now = timezone.now()
    people = [make_customer(w.tenant, w.owner, name=f"P{i}")[0] for i in range(4)]
    last = buy(w.tenant, w.owner, people[0], w.plan, now=now - timedelta(days=40))  # previous month (back-dated)
    older = buy(w.tenant, w.owner, people[1], w.plan, now=now - timedelta(days=70))  # two months ago
    buy(w.tenant, w.owner, people[2], w.plan, now=now - timedelta(hours=2))  # this month
    voided_now = buy(w.tenant, w.owner, people[3], w.plan, now=now - timedelta(hours=1))
    with w.ctx():
        billing.void_payment(actor=w.owner, payment_public_id=voided_now.payment.public_id, reason="dup", now=now)
        # a back-dated payment voided in a LATER month: charge stays in its own month, reversal lands in the void month
        billing.void_payment(actor=w.owner, payment_public_id=last.payment.public_id, reason="late void", now=now)
        total_by_month = {}
        for back in (0, 1, 2, 3):
            y, m = _months_back(w.tenant, back)
            stmt = billing.fee_statement(actor=w.owner, year=y, month=m)
            assert stmt["total_fee_minor"] == sum(line["net_minor"] for line in stmt["lines"]), (y, m)
            assert stmt["platform_fee_minor"] + stmt["gateway_fee_minor"] == stmt["total_fee_minor"]
            for line in stmt["lines"]:
                assert line["net_minor"] == line["fee_minor"] - line["reversed_minor"]
            total_by_month[(y, m)] = stmt
        cur, prev, prev2 = (total_by_month[_months_back(w.tenant, i)] for i in (0, 1, 2))
        assert prev["total_fee_minor"] == 18000  # charge in the payment's month; reversal NOT here
        assert prev2["total_fee_minor"] == 18000
        # this month: 1 charge (people[2]), 1 charge/reversal pair (people[3]), reversal of last month's payment
        assert cur["total_fee_minor"] == 18000 - 18000
        assert {line["receipt_number"] for line in cur["lines"]} >= {last.payment.receipt_number}
        # every charge ever made is accounted for exactly once across months
        assert sum(s["total_fee_minor"] for s in total_by_month.values()) == 18000 * 4 - 18000 * 2
        assert older.payment.receipt_number in {line["receipt_number"] for line in prev2["lines"]}


def test_every_fee_headline_agrees_dashboard_statement_platform():
    w = World(buy_pass=False)
    now = timezone.now()
    for i, days in enumerate((50, 33, 5, 0)):
        buy(
            w.tenant,
            w.owner,
            make_customer(w.tenant, w.owner, name=f"Q{i}")[0],
            w.plan,
            now=now - timedelta(days=days, hours=1),
        )
    with w.ctx():
        y, m = fees.local_month(w.tenant)
        stmt = billing.fee_statement(actor=w.owner, year=y, month=m)
        dash = reports.dashboard(actor=w.owner)
        assert dash["platform_fee_month_minor"] == stmt["total_fee_minor"]
    with platform_context():
        row = next(r for r in reports.platform_dashboard(include_test=True) if r["slug"] == w.tenant.slug)
        assert row["fees_month_minor"] == stmt["total_fee_minor"]
        assert reports.platform_totals([row])["fees_month_minor"] == stmt["total_fee_minor"]


# ---- audit log 500 ----------------------------------------------------------------------------------
def test_audit_log_renders_with_seed_demo_data_including_system_events(capsys):
    w = World(slug="p03audit", buy_pass=False)
    call_command("seed_demo", "--slug", w.tenant.slug)
    capsys.readouterr()
    r = client_for(w.owner.user).get(f"/t/{w.tenant.slug}/admin/audit")
    body = r.content.decode()
    assert r.status_code == 200 and "pass.expire" in body and "System" in body  # automatic expiry has no actor
    assert client_for(w.owner.user).get(f"/t/{w.tenant.slug}/admin/audit", {"action": "pass"}).status_code == 200


# ---- branded error pages + trailing slashes ------------------------------------------------------------
def test_unknown_urls_get_a_branded_404_without_a_tenant(client):
    r = client.get("/definitely/not/here")
    body = r.content.decode()
    assert r.status_code == 404 and "find that page" in body and "Back to start" in body and "Server Error" not in body
    assert "Mealtally" in body and "css/app" in body  # styled, no tenant context needed


def test_api_404_is_json_not_html(client):
    r = client.get("/api/v1/zzz-nothing")
    assert (
        r.status_code == 404
        and r["Content-Type"].startswith("application/json")
        and r.json()["error"]["code"] == "NOT_FOUND"
    )


def test_branded_500_page_html_and_json(monkeypatch):
    import mealtally.web.views_marketing as views  # the landing page lives here

    monkeypatch.setattr(views, "render", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    c = Client(raise_request_exception=False)
    r = c.get("/")
    assert (
        r.status_code == 500 and "Something went wrong" in r.content.decode() and "Traceback" not in r.content.decode()
    )
    assert "Server Error (500)" not in r.content.decode()
    from django.test import RequestFactory

    from mealtally.web import errors

    api = errors.server_error(RequestFactory().get("/api/v1/x"))
    assert api.status_code == 500 and b"SERVER_ERROR" in api.content


def test_403_and_csrf_failure_pages_are_branded():
    from django.test import RequestFactory

    from mealtally.web import errors

    assert (
        b"can&#x27;t open this page" in errors.permission_denied(RequestFactory().get("/x")).content
        or b"open this page" in errors.permission_denied(RequestFactory().get("/x")).content
    )
    assert errors.csrf_failure(RequestFactory().post("/x"), "bad").status_code == 403
    assert errors.bad_request(RequestFactory().get("/x")).status_code == 400
    c = Client(enforce_csrf_checks=True)
    assert c.post("/go", {"code": "x"}).status_code == 403
    assert b"open this page" in c.post("/go", {"code": "x"}).content


def test_trailing_slash_variants_redirect_to_the_canonical_url():
    w = World(slug="p04slash")
    owner = client_for(w.owner.user)
    u = f"/t/{w.tenant.slug}"
    for canonical in ("/admin/customers", "/admin/plans", "/staff/sell", "/admin/reports/daily", "/admin/audit"):
        r = owner.get(u + canonical + "/")
        assert r.status_code == 301 and r["Location"] == u + canonical, canonical
        assert owner.get(u + canonical).status_code == 200
    assert owner.get(u + "/admin/customers/?q=abc").headers["Location"] == u + "/admin/customers?q=abc"
    assert owner.get(u + "/me").status_code == 301  # missing slash on a slash-terminated route (APPEND_SLASH)
    assert owner.get(u + "/admin/nonexistent/").status_code == 404  # truly unknown stays a (branded) 404


# ---- camera hotfix --------------------------------------------------------------------------------------------
def test_permissions_policy_allows_camera_only_on_the_counter_scan_page(w, staff_c, owner_c, u):
    on = staff_c.get(f"{u}/staff/")["Permissions-Policy"]
    assert on == "camera=(self), microphone=(), geolocation=()"  # exactly the directive's value
    assert staff_c.get(f"{u}/staff/sell")["Permissions-Policy"].startswith("camera=()")  # no scanner on sell
    assert staff_c.get(f"{u}/staff/today")["Permissions-Policy"].startswith("camera=()")
    for path in (f"{u}/admin/", f"{u}/staff-not-a-page", "/", "/healthz", f"{u}/driver/"):
        assert owner_c.get(path)["Permissions-Policy"].startswith("camera=()"), path


def test_scanner_video_has_the_attributes_ios_safari_needs_and_error_hooks(w, staff_c, u):
    html = staff_c.get(f"{u}/staff/").content.decode()
    video = html[html.index("<video") : html.index("</video>")]
    for attr in ("playsinline", "muted", "autoplay"):
        assert attr in video, attr
    for hook in ("data-err-denied", "data-err-none", "in your browser settings"):
        assert hook in html, hook
    js = (__import__("pathlib").Path(__file__).resolve().parents[2] / "static" / "js" / "app.js").read_text()
    assert 'facingMode: { ideal: "environment" }' in js and "exact" not in js.split('Alpine.data("scanner"')[1]
    assert "NotAllowedError" in js and "NotFoundError" in js and "openManual" in js
