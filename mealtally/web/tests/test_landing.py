"""D03.6 Part B: the public landing page, honest feature badges, the demo request form, SEO files and the legal drafts."""

from __future__ import annotations

import re

import pytest
from django.core.cache import cache

from mealtally.preview.registry import BY_KEY
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.models import DemoRequest
from mealtally.web import marketing

pytestmark = pytest.mark.django_db
GOOD = {
    "name": "Asha Rao",
    "business_name": "Rao Tiffins",
    "city": "Pune",
    "phone": "98765 43210",
    "business_type": "tiffin",
    "message": "We run 80 tiffins a day.",
}


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()


def test_landing_renders_every_section_in_tally_with_one_h1_and_nothing_inline(client):
    r = client.get("/")
    html = r.content.decode()
    assert r.status_code == 200 and 'data-theme="tally"' in html and html.count("<h1") == 1
    for anchor in ("who-its-for", "features", "how-it-works", "pricing", "faq", "book-a-demo"):
        assert f'id="{anchor}"' in html, anchor
    assert not re.search(r"\sstyle=", html)
    assert not re.search(
        r"<script(?![^>]*(\bsrc=|application/ld\+json))", html
    )  # CSP: no inline scripts (JSON-LD is data)
    assert "Prepaid meal passes for restaurants" in html and "Restaurant login" in html and 'rel="canonical"' in html
    assert 'name="description"' in html and 'property="og:title"' in html and "twitter:card" in html
    assert "ratingValue" not in html and "aggregateRating" not in html  # honesty: no rating fields in the JSON-LD
    assert "SoftwareApplication" in html and "Organization" in html


def test_feature_badges_come_from_the_registry_and_never_overclaim():
    rows = {f["title"]: f for f in marketing.features()}
    assert len(rows) == 15
    for keys, _icon, title, _text in marketing.FEATURES:
        expect = "live" if all(BY_KEY[k].status == "real" for k in keys) else "soon"
        assert rows[title]["status"] == expect, title
    assert rows["QR meal redemption"]["status"] == "live" and rows["₹ wallet and top-ups"]["status"] == "soon"
    assert marketing.status_for("no-such-module") == "soon" and marketing.status_for() == "soon"
    html = marketing.features.__module__  # sanity: module import works
    assert html


def test_rendered_badges_match_the_registry(client):
    html = client.get("/").content.decode()
    live = len(re.findall(r'data-status="live"', html))
    soon = len(re.findall(r'data-status="soon"', html))
    assert live == sum(1 for f in marketing.features() if f["status"] == "live") and soon > 0 and live > 0


def test_pricing_is_a_platform_setting_and_follows_the_fee_policy(client):
    """D03.9 §A2: percentage by default, switchable to 'contact' in platform admin (no restart); the numbers are the
    default platform fee policy billing applies, so the page can't drift from what is charged."""
    from mealtally.billing import services as billing
    from mealtally.tenancy.models import PlatformSettings

    html = client.get("/").content.decode()
    pct, gw = f"{billing.DEFAULT_PLATFORM_PCT.normalize():f}", f"{billing.DEFAULT_GATEWAY_PCT.normalize():f}"
    assert 'data-pricing-mode="percentage"' in html and f"{pct}% of subscription revenue" in html and f"+{gw}%" in html
    assert (pct, gw) == ("12", "10")
    PlatformSettings(
        marketing_pricing_mode="contact", pricing_headline="Simple pricing", pricing_footnote="GST extra."
    ).save()
    html = client.get("/").content.decode()
    assert 'data-pricing-mode="contact"' in html and "% of subscription" not in html
    assert "Simple pricing" in html and "GST extra." in html


def test_demo_request_valid_stores_a_platform_row_with_no_tenant(client):
    r = client.post("/demo-request", GOOD)
    assert r.status_code == 302 and r["Location"].endswith("?demo=sent#book-a-demo")
    with platform_context():
        row = DemoRequest.objects.get()
    assert row.business_name == "Rao Tiffins" and row.phone == "+919876543210" and not hasattr(row, "tenant_id")
    assert 'data-testid="demo-sent"' in client.get("/?demo=sent").content.decode()


def test_demo_request_validation_errors_keep_the_values(client):
    r = client.post("/demo-request", {**GOOD, "phone": "123", "city": "", "message": "see http://spam.example"})
    html = r.content.decode()
    assert r.status_code == 400 and "valid phone" in html and "your city" in html and "leave links out" in html
    assert "Rao Tiffins" in html
    with platform_context():
        assert DemoRequest.objects.count() == 0


def test_demo_request_honeypot_stores_nothing_but_looks_successful(client):
    r = client.post("/demo-request", {**GOOD, "company_website": "http://bot.example"})
    assert r.status_code == 302 and r["Location"].endswith("?demo=sent#book-a-demo")
    with platform_context():
        assert DemoRequest.objects.count() == 0


def test_demo_request_is_rate_limited_to_five_an_hour_per_ip(client):
    for i in range(5):
        assert client.post("/demo-request", {**GOOD, "name": f"A{i}"}, REMOTE_ADDR="10.0.0.9").status_code == 302
    r = client.post("/demo-request", GOOD, REMOTE_ADDR="10.0.0.9")
    assert r.status_code == 429 and r["Retry-After"] == "3600" and "Too many requests" in r.content.decode()
    assert client.post("/demo-request", GOOD, REMOTE_ADDR="10.0.0.10").status_code == 302  # another network is fine
    with platform_context():
        assert DemoRequest.objects.count() == 6


def test_demo_request_needs_post_and_csrf_is_enforced(client):
    assert client.get("/demo-request").status_code == 405
    from django.test import Client

    assert Client(enforce_csrf_checks=True).post("/demo-request", GOOD).status_code == 403

def test_signed_in_users_get_a_dashboard_button_not_a_redirect(w, client, u):
    from mealtally.testing import PASSWORD

    client.post(u + "/login/staff", {"login": w.owner.user.email, "password": PASSWORD})
    r = client.get("/")
    assert r.status_code == 200 and 'data-testid="go-dashboard"' in r.content.decode()
    assert u + "/admin" in r.content.decode() or u + "/staff" in r.content.decode()


def test_go_with_an_empty_code_shows_the_landing_with_an_error(client):
    r = client.post("/go", {"code": ""})
    assert r.status_code == 400 and 'data-theme="tally"' in r.content.decode()


def test_robots_and_sitemap_list_the_legal_pages_only_once_they_are_live(client):
    from mealtally.tenancy.models import PlatformSettings
    from mealtally.web.tests.test_modes import LEGAL

    robots = client.get("/robots.txt")
    assert "Disallow: /t/" in robots.content.decode() and robots["Content-Type"].startswith("text/plain")
    sm = client.get("/sitemap.xml").content
    assert b"<urlset" in sm and b"/privacy" not in sm
    PlatformSettings(**LEGAL).save()
    sm = client.get("/sitemap.xml").content
    assert b"/privacy" in sm and b"/terms" in sm
