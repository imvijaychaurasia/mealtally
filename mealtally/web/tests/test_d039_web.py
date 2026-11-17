# SPDX-License-Identifier: AGPL-3.0-only
"""D03.9 web layer: §A1 reversal policy, §B screens (meal times, plan rule, counter card, override, refused report,
banner, customer rule line) and the QA-01 P1-5/P1-6/P2 fixes. Time-dependent cases run on a frozen clock."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import time_machine
from django.utils import timezone

from mealtally.audit.models import AuditEvent
from mealtally.common.country import format_phone
from mealtally.common.errors import NotAllowed
from mealtally.customers import services as customers
from mealtally.ledger import services as ledger
from mealtally.plans import services as plans
from mealtally.plans.models import MealSlot
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.models import TenantSettings
from mealtally.testing import make_actor

pytestmark = pytest.mark.django_db
IST = ZoneInfo("Asia/Kolkata")


def tomorrow_at(hh, mm=0):
    day = timezone.now().astimezone(IST).date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=IST)


def lunch_only(w):
    """Give w's plan AND its sold pass the 'Lunch only, 1 meal per day' rule."""
    with w.ctx():
        lunch = MealSlot.objects.get(name="Lunch")
        plans.set_allowed_slots(w.plan, [lunch])
        type(w.pass_).objects.filter(pk=w.pass_.pk).update(allowed_slot_ids=[lunch.id], max_meals_per_slot=1)
    return lunch


# --- §B screens -------------------------------------------------------------------------------------------------------
def test_owner_edits_meal_times_and_it_is_audited(w, owner_c, manager_c, u):
    page = owner_c.get(u + "/admin/settings/meal-times").content.decode()
    assert page.count('data-testid="meal-slot"') == 3 and "Lunch" in page
    with w.ctx():
        lunch = MealSlot.objects.get(name="Lunch")
    resp = owner_c.post(
        u + "/admin/settings/meal-times",
        {
            "slot": lunch.public_id,
            "name": "Lunch",
            "start_time": "12:30",
            "end_time": "15:30",
            "grace_minutes": "10",
            "is_active": "on",
        },
    )
    assert 'data-testid="notice"' in resp.content.decode()
    with w.ctx():
        lunch.refresh_from_db()
        assert (lunch.start_time.hour, lunch.start_time.minute, lunch.grace_minutes) == (12, 30, 10)
        assert AuditEvent.objects.filter(action="meal_slot.update").exists()
    bad = owner_c.post(u + "/admin/settings/meal-times", {"name": "Snacks", "start_time": "25:00", "end_time": "18:00"})
    assert 'data-testid="error"' in bad.content.decode()
    assert manager_c.get(u + "/admin/settings/meal-times").status_code in (302, 403, 404)


def test_plan_form_sets_the_meal_time_rule_and_the_list_says_it_in_words(w, owner_c, u):
    with w.ctx():
        lunch = MealSlot.objects.get(name="Lunch")
    resp = owner_c.post(
        f"{u}/admin/plans/{w.plan.public_id}",
        {
            "name": w.plan.name,
            "price_major": "1500",
            "meals_per_cycle": "30",
            "validity_mode": "ROLLING_DAYS",
            "validity_days": "30",
            "allowed_slots": [str(lunch.id)],
            "max_meals_per_slot": "1",
            "max_meals_per_day": "",
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    listing = owner_c.get(u + "/admin/plans").content.decode()
    assert "Lunch only, 1 meal per day" in listing
    form = owner_c.get(f"{u}/admin/plans/{w.plan.public_id}").content.decode()
    assert 'data-testid="plan-rule-summary"' in form


def test_counter_sees_ask_a_manager_and_a_manager_can_override(w, staff_c, manager_c, u):
    lunch_only(w)
    with time_machine.travel(tomorrow_at(10, 0), tick=False):
        card = staff_c.get(f"{u}/staff/card/{w.customer.public_id}").content.decode()
        assert "Lunch is served 12:00–15:00. Next: today 12:00." in card
        assert 'data-testid="ask-manager"' in card and 'data-testid="override-form"' not in card
        mcard = manager_c.get(f"{u}/staff/card/{w.customer.public_id}").content.decode()
        assert 'data-testid="override-form"' in mcard
        key = re.search(r'name="idempotency_key" value="([^"]+)"', mcard.split('data-testid="override-form"')[1]).group(
            1
        )
        done = manager_c.post(
            u + "/staff/redeem",
            {
                "customer": w.customer.public_id,
                "idempotency_key": key,
                "confirm_additional": "1",
                "override_reason": "Late shift, approved",
            },
        ).content.decode()
        assert "29" in done
    with w.ctx():
        assert AuditEvent.objects.filter(action="redeem.override").count() == 1


def test_a_refused_redeem_is_shown_and_audited_and_the_owner_report_lists_it(w, staff_c, owner_c, manager_c, u):
    lunch_only(w)
    with time_machine.travel(tomorrow_at(16, 0), tick=False):
        resp = staff_c.post(
            u + "/staff/redeem", {"customer": w.customer.public_id, "idempotency_key": str(uuid.uuid4())}
        )
        assert "Lunch is served 12:00–15:00. Next: tomorrow 12:00." in resp.content.decode()
        report = owner_c.get(u + "/admin/reports/refused").content.decode()
    assert w.customer.full_name in report and "Outside meal time" in report
    with w.ctx():
        e = AuditEvent.objects.get(action="redeem.denied")
        assert e.after["code"] == "MEAL_SLOT_CLOSED" and e.after["channel"] == "STAFF_SEARCH"
    assert manager_c.get(u + "/admin/reports/refused").status_code in (302, 403, 404)


def test_the_api_keeps_the_refusal_audit_row(w, u):
    from rest_framework.test import APIClient

    lunch_only(w)
    api = APIClient()
    api.force_authenticate(w.staff.user)
    with time_machine.travel(tomorrow_at(9, 0), tick=False):
        resp = api.post(
            f"/api/v1/t/{w.tenant.slug}/redeem",
            {"customer": str(w.customer.public_id), "idempotency_key": str(uuid.uuid4())},
            format="json",
        )
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "MEAL_SLOT_CLOSED"
    with w.ctx():
        assert AuditEvent.objects.filter(action="redeem.denied").count() == 1


def test_owner_banner_until_rules_are_set_or_dismissed(w, owner_c, staff_c, u):
    home = owner_c.get(u + "/admin/").content.decode()
    assert 'data-testid="meal-rules-banner"' in home
    resp = owner_c.post(u + "/admin/settings/meal-rules-banner", {"next": u + "/admin/plans"})
    assert resp.status_code == 302 and resp["Location"] == u + "/admin/plans"
    assert 'data-testid="meal-rules-banner"' not in owner_c.get(u + "/admin/").content.decode()
    assert 'data-testid="meal-rules-banner"' not in staff_c.get(u + "/staff/").content.decode()


def test_customer_home_shows_the_rule_and_the_next_opening(w, cust_c, u):
    lunch_only(w)
    with w.ctx():
        w.customer.must_change_pin = False
        w.customer.save()
    with time_machine.travel(tomorrow_at(9, 30), tick=False):
        home = cust_c.get(u + "/me/").content.decode()
    assert "Lunch only · 1 meal a day · Next: today 12:00" in home
    with time_machine.travel(tomorrow_at(12, 30), tick=False):
        assert "Now: Lunch until 15:00" in cust_c.get(u + "/me/").content.decode()


# --- §A1 --------------------------------------------------------------------------------------------------------------
def test_counter_reversal_of_another_staff_members_meal_follows_the_setting(w):
    other = make_actor(w.tenant, "STAFF")
    with w.ctx():
        res = ledger.redeem(actor=other, customer=w.customer, idempotency_key=str(uuid.uuid4()), source="STAFF_SEARCH")
        ledger.reverse_redemption(actor=w.staff, entry_public_id=res.entry.public_id, reason="default: yes")
        res2 = ledger.redeem(
            actor=other,
            customer=w.customer,
            idempotency_key=str(uuid.uuid4()),
            source="STAFF_SEARCH",
            confirm_additional=True,
        )
    with platform_context():
        TenantSettings.objects.filter(tenant_id=w.tenant.id).update(counter_can_reverse_others=False)
    with w.ctx(), pytest.raises(NotAllowed) as exc:
        ledger.reverse_redemption(actor=w.staff, entry_public_id=res2.entry.public_id, reason="not mine")
    assert exc.value.code == "REVERSE_OTHERS_NOT_ALLOWED"
    with w.ctx():
        ledger.reverse_redemption(actor=w.manager, entry_public_id=res2.entry.public_id, reason="manager may")


def test_policies_section_saves_reversal_policy_and_topup_bounds(w, owner_c, u):
    page = owner_c.get(u + "/admin/settings").content.decode()
    assert 'data-testid="policies"' in page and 'data-testid="counter-can-reverse-others"' in page
    base = {
        "timezone": "Asia/Kolkata",
        "brand_color": "#0f766e",
        "redeem_cooldown_seconds": "120",
        "staff_reversal_window_hours": "12",
        "max_queued_passes": "1",
        "topup_min_major": "200",
        "topup_max_major": "20000",
    }
    owner_c.post(u + "/admin/settings", base)
    with platform_context():
        row = TenantSettings.objects.get(tenant_id=w.tenant.id)
    assert row.counter_can_reverse_others is False and (row.topup_min_minor, row.topup_max_minor) == (20000, 2000000)
    bad = owner_c.post(u + "/admin/settings", {**base, "topup_min_major": "500", "topup_max_major": "100"})
    assert "largest top-up" in bad.content.decode()


# --- QA-01 P1-5 / P1-6 ------------------------------------------------------------------------------------------------
def test_staff_and_the_customer_can_edit_the_delivery_address(w, staff_c, cust_c, u):
    with w.ctx():
        w.customer.must_change_pin = False
        w.customer.save()
        customers.update_customer(
            actor=w.staff, customer=w.customer, full_name=w.customer.full_name, address="  12, Lane 3,\n Kothrud  "
        )
        w.customer.refresh_from_db()
    assert w.customer.address == "12, Lane 3, Kothrud"
    cust_c.post(u + "/me/account", {"full_name": w.customer.full_name, "address": "Flat 4, Sky Vista, Baner"})
    with w.ctx():
        w.customer.refresh_from_db()
    assert w.customer.address == "Flat 4, Sky Vista, Baner"
    assert 'data-testid="account-address"' in cust_c.get(u + "/me/account").content.decode()


@pytest.mark.parametrize(
    ("amount", "utr", "ok"),
    [
        ("1000", "412800931204", True),
        ("1000", "123", False),
        ("50", "412800931204", False),
        ("60000", "412800931204", False),
        ("abc", "412800931204", False),
    ],
)
def test_topup_is_checked_on_the_server(w, cust_c, u, amount, utr, ok):
    with w.ctx():
        w.customer.must_change_pin = False
        w.customer.save()
    html = cust_c.post(u + "/me/wallet/topup", {"amount": amount, "utr": utr}).content.decode()
    assert ('data-testid="topup-ok"' in html) is ok and ('data-testid="topup-errors"' in html) is (not ok)


# --- QA-01 P2 ---------------------------------------------------------------------------------------------------------
def test_back_onto_a_sell_step_goes_to_the_sell_form_with_a_note(w, staff_c, u):
    assert staff_c.get(u + "/staff/sell/confirm")["Location"] == u + "/staff/sell"
    from mealtally.testing import buy

    buy(w.tenant, w.staff, w.customer, w.plan)
    loc = staff_c.get(u + "/staff/sell/preview")["Location"]
    assert loc.startswith(u + "/staff/sell?recorded=R-")
    assert 'data-testid="sell-recorded"' in staff_c.get(loc).content.decode()


def test_the_service_worker_never_turns_a_server_response_into_offline(client):
    js = client.get("/sw.js").content.decode()
    assert "r.method!=='GET'" in js and "mealtally-offline-v2" in js


def test_receipt_reads_upi_hides_a_placeholder_fssai_and_formats_phones(w, owner_c, u):
    with platform_context():
        TenantSettings.objects.filter(tenant_id=w.tenant.id).update(
            food_licence_no="00000000000000", contact_phone="+912040001101"
        )
    from mealtally.testing import buy

    rec = buy(w.tenant, w.owner, w.customer, w.plan, method="UPI_MANUAL")
    html = owner_c.get(f"{u}/receipt/{rec.payment.public_id}").content.decode()
    assert ">UPI<" in html.replace("<br>", "<") or "UPI\n" in html or "UPI<br>" in html
    assert "Upi Manual" not in html and "FSSAI" not in html
    assert format_phone(w.customer.phone_e164) in html and w.customer.phone_e164 not in html


def test_one_masking_rule_on_staff_screens_and_full_number_on_the_detail_page(w, staff_c, owner_c, u):
    masked = f"••••• {w.customer.phone_e164[-4:]}"
    sell = staff_c.get(u + "/staff/sell/search", {"sq": w.customer.customer_code}).content.decode()
    assert masked in sell and w.customer.phone_e164 not in sell
    lst = owner_c.get(u + "/admin/customers").content.decode()
    assert masked in lst and w.customer.phone_e164 not in lst
    detail = owner_c.get(f"{u}/admin/customers/{w.customer.public_id}").content.decode()
    assert format_phone(w.customer.phone_e164) in detail


def test_repeat_scan_message_uses_the_cooldown_setting(w, staff_c, u):
    with w.ctx():
        ledger.redeem(actor=w.staff, customer=w.customer, idempotency_key=str(uuid.uuid4()), source="STAFF_SEARCH")
    html = staff_c.post(
        u + "/staff/redeem", {"customer": w.customer.public_id, "idempotency_key": str(uuid.uuid4())}
    ).content.decode()
    assert "Already redeemed less than a minute ago (limit 2 minutes)" in html


def test_blocked_card_shows_real_meals_left_and_the_owner_reason(w, staff_c, u):
    with w.ctx():
        customers.set_status(actor=w.owner, customer=w.customer, status="BLOCKED", reason="Unpaid dues")
    card = staff_c.get(f"{u}/staff/card/{w.customer.public_id}").content.decode()
    assert "Blocked by the owner: Unpaid dues" in card and "?" not in card.split('data-testid="card-error"')[1][:120]
    assert '<p class="text-4xl font-extrabold" data-testid="remaining">30</p>' in card


def test_audit_log_reads_as_sentences_with_raw_data_behind_details(w, owner_c, u):
    with w.ctx():
        res = ledger.redeem(
            actor=w.staff, customer=w.customer, idempotency_key=str(uuid.uuid4()), source="STAFF_SEARCH"
        )
        ledger.reverse_redemption(actor=w.manager, entry_public_id=res.entry.public_id, reason="wrong customer")
    html = owner_c.get(u + "/admin/audit").content.decode()
    who = w.manager.user.name or w.manager.user.email
    assert f"{who} reversed {w.customer.full_name}&#x27;s" in html and "reason: wrong customer" in html
    assert "₹1,500.00" in html  # the sale, in rupees (never 150000 minor)
    assert 'data-testid="audit-raw"' in html and "<details" in html


def test_customer_login_tab_order_is_phone_pin_show_login(w, client, u):
    html = client.get(u + "/login/customer").content.decode()
    order = [
        html.index(x) for x in ('name="phone"', 'id="pin"', 'data-testid="pin-show"', 'data-testid="login-submit"')
    ]
    assert order == sorted(order)


def test_landing_header_says_dashboard_and_never_wraps(w, owner_c):
    html = owner_c.get("/").content.decode()
    m = re.search(r'<a class="([^"]+)"[^>]*data-testid="go-dashboard">([^<]+)</a>', html)
    if m:
        assert "whitespace-nowrap" in m.group(1) and m.group(2).strip() == "Dashboard"


def test_no_chart_series_uses_the_danger_colour():
    """QA-01 P2-17: charts use data colours; danger/red is only for errors."""
    root = Path(__file__).resolve().parents[2]
    tags = (root / "preview" / "templatetags" / "pv.py").read_text()
    for fn in re.findall(r"def (\w*(?:chart|donut|bar|line)\w*)\(", tags):
        body = tags.split(f"def {fn}(")[1].split("\ndef ")[0]
        assert "danger" not in body, fn
    css = (root / "static" / "css" / "themes.css").read_text()
    fresh = css.split('[data-theme="fresh"]')[1].split("}")[0]
    pending = re.search(r"--chart-pending:\s*(#[0-9A-Fa-f]{6})", fresh).group(1)
    r, g, b = (int(pending[i : i + 2], 16) for i in (1, 3, 5))
    assert not (r > 180 and g < 110 and b < 110), f"fresh pending {pending} reads as red"


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("+919000030002", "090000 30002"),
        ("+447911123456", "+44 7911 123456"),
        ("+12025550123", "+1 202-555-0123"),
        ("", ""),
    ],
)
def test_format_phone(raw, shown):
    assert format_phone(raw) == shown


def test_platform_settings_changes_are_audited():
    from django.test import RequestFactory

    from mealtally.accounts.models import User
    from mealtally.tenancy.admin import PlatformSettingsAdmin
    from mealtally.tenancy.models import PlatformSettings

    with platform_context():
        admin_user = User.objects.create_superuser(email="d039-root@example.test", password="Sup3r-Secret-Pw!")
        req = RequestFactory().post("/platform/admin/")
        req.user = admin_user
        obj = PlatformSettings(marketing_pricing_mode="contact", contact_email="hello@example.test")
        from django.contrib import admin as dj_admin

        PlatformSettingsAdmin(PlatformSettings, dj_admin.site).save_model(req, obj, form=None, change=False)
        event = AuditEvent.objects.get(action="platform_settings.update")
    assert event.tenant_id is None and event.after["marketing_pricing_mode"] == "contact" and event.before is None
    assert PlatformSettings.load().contact_email == "hello@example.test"


def test_rotate_tenant_credentials_resets_staff_and_named_customer_pins(w, tmp_path):
    import stat

    from django.core.management import call_command

    from mealtally.accounts.models import User
    from mealtally.testing import PASSWORD

    with platform_context():
        User.objects.create_superuser(email="d039-rot@example.test", password="Sup3r-Secret-Pw!")
    out = tmp_path / "pilot.txt"
    call_command(
        "rotate_tenant_credentials",
        "--slug",
        w.tenant.slug,
        "--out",
        str(out),
        "--platform-admin",
        "d039-rot@example.test",
        "--customer-code",
        w.customer.customer_code,
    )
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    text = out.read_text()
    assert text.count("password=") == 3 and "pin=" in text  # owner, manager, counter + the customer
    with platform_context():
        owner = User.objects.get(pk=w.owner.user.pk)
    assert owner.must_change_password and not owner.check_password(PASSWORD)
    with w.ctx():
        assert AuditEvent.objects.filter(action="staff.reset_password").count() == 3
        assert AuditEvent.objects.filter(action="customer.reset_pin").count() == 1
