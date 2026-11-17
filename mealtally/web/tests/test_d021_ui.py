# SPDX-License-Identifier: AGPL-3.0-only
"""D02.1 P1: navigation, console, sell, detail/list, customer app, QR code, platform pages."""

from __future__ import annotations

import re
import time
import uuid
from datetime import timedelta

import pytest
import segno
from django.test import Client
from django.utils import timezone
from django_redis import get_redis_connection

from mealtally.accounts.models import User
from mealtally.audit.models import AuditEvent
from mealtally.customers import qr
from mealtally.ledger import services as ledger
from mealtally.passes.models import Pass
from mealtally.tenancy.context import platform_context
from mealtally.testing import World
from mealtally.testing import buy
from mealtally.testing import make_customer

from .conftest import client_for

pytestmark = pytest.mark.django_db


def settle(w):
    with w.ctx():
        w.customer.must_change_pin = False
        w.customer.save()


# --- 1-3 navigation ------------------------------------------------------------------------------------------
def test_one_role_based_nav_with_active_state_identity_and_bottom_tabs(w, owner_c, manager_c, staff_c, u):
    html = owner_c.get(u + "/admin/customers").content.decode()
    top = html.split('aria-label="Main"')[1].split("</nav>")[0]
    for label in ("Redeem", "Sell pass", "Customers", "Reports", "More"):
        assert label in top
    assert "Plans" in top and "Staff" in top and "Settings" in top and "Audit log" in top  # inside More
    assert (
        "Redeem console" not in html and html.count('aria-current="page"') >= 2
    )  # no duplicate entries; active tab marked
    assert "Customers</a>" in html and 'data-testid="tabbar"' in html
    assert re.search(r'data-testid="who">[^<]*Owner', html)
    tabs = html.split('data-testid="tabbar"')[1].split("</nav>")[0]
    assert tabs.count("<li>") == 5
    mgr = manager_c.get(u + "/admin/").content.decode().split('aria-label="Main"')[1].split("</nav>")[0]
    assert "Staff" not in mgr and "Settings" not in mgr and "Plans" in mgr
    stf = staff_c.get(u + "/staff/").content.decode()
    nav = stf.split('aria-label="Main"')[1].split("</nav>")[0]
    assert "Customers" in nav and "Reports" not in nav and "More" not in nav
    assert stf.split('data-testid="tabbar"')[1].split("</nav>")[0].count("<li>") == 3


def test_customer_app_has_a_fixed_bottom_bar_and_no_duplicate_home(w, cust_c, u):
    settle(w)
    html = cust_c.get(u + "/me/").content.decode()
    # D03.7: one consumer shell: no wallet or ordering means Home · Activity · Account, plus a Show QR action.
    assert html.split('data-testid="tabbar"')[1].split("</nav>")[0].count("<li>") == 3
    for label in ("Home", "Activity", "Account"):
        assert label in html
    assert 'data-testid="show-qr"' in html and "Order" not in html.split('data-testid="tabbar"')[1].split("</nav>")[0]
    assert re.search(r'data-testid="who">[^<]*Asha Customer', html)


def test_more_page_and_staff_lookup_only_customers(w, owner_c, manager_c, staff_c, u):
    assert (
        b"Audit log" in owner_c.get(u + "/admin/more").content and b"Settings" in owner_c.get(u + "/admin/more").content
    )
    assert b"Settings" not in manager_c.get(u + "/admin/more").content
    assert staff_c.get(u + "/admin/more").status_code == 302
    page = staff_c.get(u + "/staff/customers").content.decode()
    assert (
        w.customer.full_name in page
        and w.customer.phone_e164 not in page
        and f"••••• {w.customer.phone_e164[-4:]}" in page
    )
    assert "/admin/customers/" not in page  # lookup only: no detail links
    part = staff_c.get(u + "/staff/customers", {"q": w.customer.customer_code}, HTTP_HX_REQUEST="true").content.decode()
    assert w.customer.full_name in part and "<html" not in part


# --- 4-8 redeem console ---------------------------------------------------------------------------------------
def test_search_results_mask_phone_show_status_and_collapse_after_pick(w, staff_c, u):
    r = staff_c.get(u + "/staff/search", {"q": w.customer.customer_code}).content.decode()
    assert "Active · 30 left" in r and f"••••• {w.customer.phone_e164[-4:]}" in r and w.customer.phone_e164 not in r
    nopass = World(slug="d021np", buy_pass=False)
    c = client_for(nopass.staff.user)
    assert "No pass" in c.get("/t/d021np/staff/search", {"q": nopass.customer.customer_code}).content.decode()
    card = staff_c.get(f"{u}/staff/card/{w.customer.public_id}").content.decode()
    assert 'id="results" hx-swap-oob="innerHTML"' in card  # results list collapses when a customer is picked


def test_red_card_offers_sell_pass_with_customer_preselected():
    w = World(slug="d021red", buy_pass=False)
    c = client_for(w.staff.user)
    card = c.get(f"/t/d021red/staff/card/{w.customer.public_id}").content.decode()
    assert 'data-testid="sell-from-card"' in card and f"/t/d021red/staff/sell?customer={w.customer.public_id}" in card
    form = c.get("/t/d021red/staff/sell", {"customer": w.customer.public_id}).content.decode()
    assert w.customer.full_name in form and "checked" in form


def test_success_card_has_inline_undo_and_undone_banner_dismisses_itself(w, staff_c, u):
    ok = staff_c.post(u + "/staff/redeem", {"customer": w.customer.public_id, "idempotency_key": str(uuid.uuid4())})
    html = ok.content.decode()
    assert 'data-testid="redeem-success"' in html and 'data-testid="undo"' in html and "undoBar" in html
    assert (
        'id="undo-bar"' not in html and "delay:4s" not in html
    )  # undo lives in the card; no 4 s reset that would kill it
    entry = re.search(r'name="entry" value="([^"]+)"', html).group(1)
    undone = staff_c.post(u + "/staff/undo", {"entry": entry}).content.decode()
    assert 'data-testid="undo-done"' in undone and 'hx-trigger="load delay:4s"' in undone  # auto-dismisses after 4 s
    assert 'id="undo-bar"' not in staff_c.get(u + "/staff/").content.decode()


def test_typing_a_new_search_clears_the_previous_card(w, staff_c, u):
    r = staff_c.get(u + "/staff/search", {"q": w.customer.customer_code}).content.decode()
    assert 'id="console-card" hx-swap-oob="innerHTML"' in r


# --- 9-11 sell -------------------------------------------------------------------------------------------------
def test_sell_form_preselects_single_plan_shows_per_meal_and_preview_shows_payment(w, staff_c, u):
    page = staff_c.get(u + "/staff/sell").content.decode()
    assert "₹50 per meal" in page and re.search(r'name="plan"[^>]*checked', page)
    pv = staff_c.post(
        u + "/staff/sell/preview",
        {"customer": w.customer.public_id, "plan": w.plan.public_id, "method": "UPI_MANUAL", "reference": "UTR998877"},
    )
    html = pv.content.decode()
    assert 'data-testid="preview-payment"' in html and "UPI" in html and "UTR998877" in html
    cash = staff_c.post(
        u + "/staff/sell/preview", {"customer": w.customer.public_id, "plan": w.plan.public_id, "method": "CASH"}
    ).content.decode()
    assert "Cash" in cash
    from mealtally.testing import make_plan

    make_plan(w.tenant, name="Second", price_minor=100000)
    assert not re.search(
        r'name="plan"[^>]*checked', staff_c.get(u + "/staff/sell").content.decode()
    )  # two plans: no preselection


# --- 12-15 customer detail & list -------------------------------------------------------------------------------
def test_void_is_disabled_with_a_reason_when_meals_were_redeemed(w, owner_c, u):
    with w.ctx():
        ledger.redeem(actor=w.staff, customer=w.customer, idempotency_key="v1", source="QR_SCAN")
    html = owner_c.get(f"{u}/admin/customers/{w.customer.public_id}").content.decode()
    assert 'data-testid="void-blocked"' in html and "Meals already redeemed — use Adjust credits" in html
    assert 'action="' + f"{u}/admin/customers/{w.customer.public_id}/void" not in html  # no void form offered


def test_passes_ordered_active_queued_past_with_queued_wording_and_ledger_evidence(w, owner_c, u):
    q = buy(w.tenant, w.owner, w.customer, w.plan).pass_
    with w.ctx():
        ledger.redeem(actor=w.staff, customer=w.customer, idempotency_key="l1", source="QR_SCAN")
        ledger.redeem(
            actor=w.manager, customer=w.customer, idempotency_key="l2", source="STAFF_SEARCH", confirm_additional=True
        )
    html = owner_c.get(f"{u}/admin/customers/{w.customer.public_id}").content.decode()
    assert html.index("ACTIVE") < html.index("QUEUED")
    assert re.search(r"Starts \d+ \w+ · 30 meals · ends \d+ \w+", html) and "0/30" not in html
    ledger_html = html.split('data-testid="ledger"')[1]
    for needle in (
        "Meal redeemed",
        "Credits issued",
        "QR",
        "Counter search",
        "System",
        w.staff.user.email,
        w.manager.user.email,
    ):
        assert needle in ledger_html, needle
    assert (
        '<th class="th">Pass</th>' in ledger_html and q.plan_name in ledger_html
    )  # pass column appears with several passes


def test_customers_list_shows_meals_valid_until_and_queued_hint(w, owner_c, u):
    buy(w.tenant, w.owner, w.customer, w.plan)
    html = owner_c.get(u + "/admin/customers").content.decode()
    assert (
        "Meals left" in html
        and "Valid until" in html
        and 'data-testid="queued-hint"' in html
        and "+1 queued" in re.sub(r"\s+", " ", html)
    )
    other, _ = make_customer(w.tenant, w.owner, name="Plain")
    assert "—" in owner_c.get(u + "/admin/customers", {"q": "Plain"}).content.decode()
    assert other


# --- 16-19 customer app -------------------------------------------------------------------------------------------
def test_pluralisation_and_expiry_vs_low_messaging(w, cust_c, u):
    settle(w)
    with w.ctx():
        Pass.objects.filter(pk=w.pass_.pk).update(ends_at=timezone.now() + timedelta(days=1), meals_remaining=18)
    html = cust_c.get(u + "/me/").content.decode()
    assert re.search(r"\b1 day left", html) and "1 days" not in html  # singular
    assert 'data-testid="expiry-warning"' in html and re.search(
        r"18 meals will expire on \d+ \w+ — renew at the counter", html
    )
    assert "top up" not in html.lower() and "Running low" not in html
    with w.ctx():
        Pass.objects.filter(pk=w.pass_.pk).update(ends_at=timezone.now() + timedelta(days=20), meals_remaining=2)
    low = cust_c.get(u + "/me/").content.decode()
    assert 'data-testid="low-warning"' in low and "Running low — 2 meals left" in low and "will expire" not in low
    with w.ctx():
        Pass.objects.filter(pk=w.pass_.pk).update(ends_at=timezone.now() + timedelta(days=20), meals_remaining=1)
    assert "Running low — 1 meal left" in cust_c.get(u + "/me/").content.decode()


def test_qr_screen_shows_meals_and_validity(w, cust_c, u):
    settle(w)
    assert re.search(r"30 meals left · valid until \d+ \w+ \d{4}", cust_c.get(u + "/me/qr").content.decode())
    assert 'data-testid="qr-meals"' in cust_c.get(u + "/me/qr/fragment").content.decode()


def test_forced_pin_change_skips_current_pin_right_after_login_but_not_otherwise(w, u):
    c = Client()
    c.post(u + "/login/customer", {"phone": w.customer.phone_e164, "pin": w.pin})
    page = c.get(u + "/me/pin").content.decode()
    assert 'id="old_pin"' not in page  # fresh PIN login: not asked again
    assert c.post(u + "/me/pin", {"new_pin": "482916", "confirm_pin": "482916"}).status_code == 302
    after = c.get(u + "/me/pin").content.decode()
    assert 'id="old_pin"' in after  # voluntary change: current PIN required
    assert c.post(u + "/me/pin", {"old_pin": "000000", "new_pin": "573920", "confirm_pin": "573920"}).status_code == 400
    # stale session (> 10 minutes since the PIN login) on a forced account: ask again
    w2 = World(slug="d021pin", buy_pass=False)
    c2 = Client()
    c2.post("/t/d021pin/login/customer", {"phone": w2.customer.phone_e164, "pin": w2.pin})
    s = c2.session
    s["pin_login_at"] = time.time() - 3600
    s.save()
    assert 'id="old_pin"' in c2.get("/t/d021pin/me/pin").content.decode()
    # the temporary PIN itself cannot be re-used as the new one
    c3 = Client()
    c3.post("/t/d021pin/login/customer", {"phone": w2.customer.phone_e164, "pin": w2.pin})
    assert c3.post("/t/d021pin/me/pin", {"new_pin": w2.pin, "confirm_pin": w2.pin}).status_code == 400


# --- 20 QR short code ----------------------------------------------------------------------------------------------
def test_qr_carries_a_short_code_version_at_most_3_error_correction_m(w, cust_c, u):
    settle(w)
    code = qr.issue_code(customer=w.customer, tenant=w.tenant)
    assert re.fullmatch(r"[A-Z2-7]{12}", code)
    sym = segno.make(code, error="m", micro=False, boost_error=False)
    assert sym.version <= 3 and sym.error == "M"
    signed = qr.issue_token(customer=w.customer, tenant=w.tenant)
    assert (
        segno.make(signed, error="m", micro=False, boost_error=False).version > sym.version
    )  # old payload was a much denser symbol
    svg = cust_c.get(f"/api/v1/t/{w.tenant.slug}/me/qr.svg")
    assert svg.status_code == 200 and b"<svg" in svg.content


def test_code_resolution_single_use_expiry_wrong_tenant_and_lowercase_entry(w, staff_c, u):
    code = qr.issue_code(customer=w.customer, tenant=w.tenant)
    ttl = get_redis_connection("default").ttl(f"mealtally:qr:code:{code}")
    assert 0 < ttl <= 90
    ok = staff_c.post(
        u + "/staff/scan", {"token": code.lower(), "idempotency_key": "kk-1"}
    ).content.decode()  # typed by hand
    assert "29 left" in ok
    again = staff_c.post(u + "/staff/scan", {"token": code, "idempotency_key": "kk-2"}).content.decode()
    assert "already used" in again
    gone = qr.issue_code(customer=w.customer, tenant=w.tenant)
    get_redis_connection("default").delete(f"mealtally:qr:code:{gone}")
    assert "expired" in staff_c.post(u + "/staff/scan", {"token": gone, "idempotency_key": "kk-3"}).content.decode()
    other = World(slug="d021qr", buy_pass=False)
    foreign = qr.issue_code(customer=w.customer, tenant=w.tenant)
    assert (
        "not valid"
        in client_for(other.staff.user)
        .post("/t/d021qr/staff/scan", {"token": foreign, "idempotency_key": "kk-4"})
        .content.decode()
    )
    assert (
        "not valid"
        in staff_c.post(u + "/staff/scan", {"token": "NOT-A-CODE", "idempotency_key": "kk-5"}).content.decode()
    )


# --- 21-23 plan form / settings / receipt -----------------------------------------------------------------------------
def test_plan_form_wording_and_live_helpers(w, owner_c, u):
    html = owner_c.get(u + "/admin/plans/new").content.decode()
    assert "Fixed days from purchase" in html and "Calendar month (ends on the last day of the month)" in html
    assert 'x-data="planForm"' in html and 'x-show="showDays"' in html and 'data-testid="plan-per-meal"' in html


def test_settings_uses_a_color_input_and_no_fieldset_legends(w, owner_c, u):
    html = owner_c.get(u + "/admin/settings").content.decode()
    assert 'type="color"' in html and "<legend" not in html
    assert "<legend" not in owner_c.get(u + "/staff/sell").content.decode()


def test_receipt_has_back_link_name_and_address(w, owner_c, u):
    with w.ctx():
        from mealtally.tenancy import services as t

        t.update_settings(
            actor=w.owner, display_name="Pilot Tiffin (test)", address="12 MG Road", contact_phone="+91 80 4000 0000"
        )
    html = owner_c.get(f"{u}/receipt/{w.recorded.payment.public_id}").content.decode()
    assert "data-back" in html and "Pilot Tiffin (test)" in html and "12 MG Road" in html and "080 4000 0000" in html


# --- 24-28 platform ----------------------------------------------------------------------------
def _admin():
    with platform_context():
        return User.objects.create_superuser(
            email=f"root-{uuid.uuid4().hex[:6]}@example.test", password="Sup3r-Secret-Pw!"
        )


def test_platform_tenant_detail_has_no_customer_data_and_exports_fees(w):
    c = client_for(_admin())
    r = c.get(f"/platform/tenants/{w.tenant.slug}")
    html = r.content.decode()
    assert r.status_code == 200 and "Fee policy" in html and "Monthly fee statement" in html and "₹180.00" in html
    assert w.customer.full_name not in html and w.customer.phone_e164 not in html  # fees only
    csv = c.get(f"/platform/tenants/{w.tenant.slug}/fees", {"format": "csv"}).content.decode()
    assert "R-000001" in csv and "TOTAL" in csv and w.customer.full_name not in csv
    assert c.get(f"/platform/tenants/{w.tenant.slug}/fees", {"format": "pdf"}).content[:5] == b"%PDF-"
    assert c.get("/platform/tenants/nope").status_code == 404
    assert client_for(w.owner.user).get(f"/platform/tenants/{w.tenant.slug}").status_code == 404


def test_platform_fee_policy_change_is_effective_dated(w):
    c = client_for(_admin())
    r = c.post(
        f"/platform/tenants/{w.tenant.slug}/fee-policy",
        {"platform_pct": "15.00", "gateway_pct": "9", "effective_from": ""},
    )
    assert r.status_code == 302 and "saved" in r["Location"].lower()
    assert b"15.00" in c.get(f"/platform/tenants/{w.tenant.slug}").content
    bad = c.post(f"/platform/tenants/{w.tenant.slug}/fee-policy", {"platform_pct": "150", "gateway_pct": "9"})
    assert (
        (bad.status_code == 302 and "Check" in bad["Location"])
        or "percent" in bad["Location"].lower()
        or "0-100" in bad["Location"]
    )


def test_status_changes_need_confirm_and_reason_and_are_audited(w):
    c = client_for(_admin())
    assert (
        c.get(f"/platform/tenants/{w.tenant.slug}/status/suspend").status_code == 200
    )  # confirm page, nothing changed yet
    assert c.get(f"/platform/tenants/{w.tenant.slug}/status/explode").status_code == 404
    from mealtally.tenancy.models import Tenant

    with platform_context():
        assert Tenant.objects.get(pk=w.tenant.pk).status == "ACTIVE"
    assert c.post(f"/platform/tenants/{w.tenant.slug}/status/deactivate", {"reason": ""}).status_code == 400
    assert (
        c.post(f"/platform/tenants/{w.tenant.slug}/status/deactivate", {"reason": "contract ended"}).status_code == 302
    )
    with platform_context():
        assert Tenant.objects.get(pk=w.tenant.pk).status == "DEACTIVATED"
        ev = AuditEvent.objects.get(action="tenant.set_status", tenant=w.tenant)
        assert ev.after["reason"] == "contract ended" and ev.after["status"] == "DEACTIVATED"


def test_test_tenants_are_hidden_by_default_and_excluded_from_totals():
    admin = client_for(_admin())
    real = World(slug="d021real")
    test = World(slug="d021test", buy_pass=True)
    with platform_context():
        from mealtally.tenancy.models import Tenant

        Tenant.objects.filter(pk=test.tenant.pk).update(is_test=True)
    html = admin.get("/platform/").content.decode()
    assert "d021real" in html and "d021test" not in html
    shown = admin.get("/platform/", {"show_test": "1"}).content.decode()
    assert "d021test" in shown and "Hide test tenants" in shown
    t_hidden = int(re.search(r'data-testid="pt-tenants">(\d+)', html).group(1))
    t_shown = int(re.search(r'data-testid="pt-tenants">(\d+)', shown).group(1))
    assert t_shown == t_hidden + 1 and real
    form = admin.get("/platform/onboard/").content.decode()
    assert 'name="is_test"' in form
    admin.post(
        "/platform/onboard/",
        {
            "name": "T",
            "slug": "d021flag",
            "timezone": "UTC",
            "owner_name": "O",
            "owner_email": "o@flag.example.com",
            "is_test": "on",
        },
    )
    with platform_context():
        assert Tenant.objects.get(slug="d021flag").is_test is True


def test_platform_dashboard_uses_display_names_and_links_to_the_detail_page():
    w = World(slug="d021name", buy_pass=False)
    with w.ctx():
        from mealtally.tenancy import services as t

        t.update_settings(actor=w.owner, display_name="Pilot Tiffin (test)")
    html = client_for(_admin()).get("/platform/").content.decode()
    assert "Pilot Tiffin (test)" in html and "/platform/tenants/d021name" in html and "/t/d021name/" not in html


# --- D03.3 camera hotfix: the typed-in fallback ---------------------------------------------------------------------
def test_qr_screen_shows_the_same_12_char_code_as_the_qr_and_staff_can_type_it(w, cust_c, staff_c, u):
    import base64

    settle(w)
    page = cust_c.get(u + "/me/qr").content.decode()
    m = re.search(r'data-testid="qr-code">([A-Z2-7]{4}) ([A-Z2-7]{4}) ([A-Z2-7]{4})<', page)
    assert m, "the code must be shown as XXXX XXXX XXXX"
    code = "".join(m.groups())
    uri = re.search(r'src="data:image/svg\+xml;base64,([^"]+)"', page).group(1)
    assert base64.b64decode(uri) == qr.render_svg(code)  # the picture encodes exactly the printed code
    assert get_redis_connection("default").ttl(f"mealtally:qr:code:{code}") > 0
    frag = cust_c.get(u + "/me/qr/fragment").content.decode()  # refreshes with the QR: a NEW code each time
    assert re.search(r'data-testid="qr-code">([A-Z2-7 ]{14})<', frag).group(1).replace(" ", "") != code
    typed = f"{m.group(1).lower()} {m.group(2)}  {m.group(3).lower()}"  # spaces + any case
    ok = staff_c.post(u + "/staff/scan", {"token": typed, "idempotency_key": "typed-1"}).content.decode()
    assert "29 left" in ok
