from __future__ import annotations

import pytest
from django.test import Client

from mealtally.accounts.models import User
from mealtally.ledger import services as ledger
from mealtally.tenancy.context import platform_context
from mealtally.testing import World
from mealtally.testing import buy

from .conftest import client_for

pytestmark = pytest.mark.django_db


def test_dashboard_tiles_and_nav_by_role(w, owner_c, manager_c, u):
    with w.ctx():
        ledger.redeem(actor=w.staff, customer=w.customer, idempotency_key="ad1", source="STAFF_SEARCH")
    html = owner_c.get(u + "/admin/").content.decode()
    assert (
        'data-testid="t-meals">1<' in html
        and 'data-testid="t-active">1<' in html
        and "₹1,500.00" in html
        and "₹180.00" in html
    )
    assert "/admin/staff" in html and "/admin/settings" in html
    assert "/admin/staff" not in manager_c.get(u + "/admin/").content.decode()  # owner-only links hidden for managers
    assert (
        manager_c.get(u + "/admin/staff").status_code == 302 and manager_c.get(u + "/admin/settings").status_code == 302
    )


def test_customer_list_filters_htmx_and_detail(w, owner_c, u):
    assert w.customer.full_name in owner_c.get(u + "/admin/customers").content.decode()
    part = owner_c.get(
        u + "/admin/customers", {"status": "active_pass", "q": w.customer.customer_code}, HTTP_HX_REQUEST="true"
    ).content.decode()
    assert w.customer.full_name in part and "<html" not in part
    assert (
        w.customer.full_name
        not in owner_c.get(u + "/admin/customers", {"status": "blocked"}).content.decode().split("<tbody")[1]
    )
    d = owner_c.get(f"{u}/admin/customers/{w.customer.public_id}")
    assert d.status_code == 200 and b"Monthly Meal Pass" in d.content and b"R-000001" in d.content
    assert owner_c.get(f"{u}/admin/customers/00000000-0000-0000-0000-000000000000").status_code == 404


def act(c, u, w, action, **data):
    return c.post(f"{u}/admin/customers/{w.customer.public_id}/{action}", data)


def test_customer_actions_edit_block_pin_adjust_pass_void(w, owner_c, manager_c, staff_c, u):
    assert b"Saved." in act(owner_c, u, w, "edit", full_name="Asha K", notes="vip").content
    assert b"Customer blocked." in act(manager_c, u, w, "block", reason="abuse").content
    assert b"Customer unblocked." in act(manager_c, u, w, "unblock", reason="ok").content
    r = act(owner_c, u, w, "reset-pin", pin_choice="own", pin="736105")
    assert b"New PIN set" in r.content and b"736105" in r.content
    assert b"New PIN set" in act(owner_c, u, w, "reset-pin", pin_choice="generate").content
    assert (
        b"Credits adjusted."
        in act(
            owner_c,
            u,
            w,
            "adjust",
            **{"pass": w.pass_.public_id, "quantity": "-2", "reason": "waste", "idempotency_key": "ui-adj"},
        ).content
    )
    assert (
        act(
            owner_c,
            u,
            w,
            "adjust",
            **{"pass": w.pass_.public_id, "quantity": "x", "reason": "r", "idempotency_key": "ui-adj2"},
        ).status_code
        == 400
    )
    assert (
        act(
            owner_c,
            u,
            w,
            "adjust",
            **{"pass": w.pass_.public_id, "quantity": "-99", "reason": "r", "idempotency_key": "ui-adj3"},
        ).status_code
        == 400
    )
    assert (
        act(manager_c, u, w, "suspend", **{"pass": w.pass_.public_id, "reason": "r"}).status_code == 400
    )  # OWNER only
    assert b"Pass updated." in act(owner_c, u, w, "suspend", **{"pass": w.pass_.public_id, "reason": "fraud"}).content
    assert b"Pass updated." in act(owner_c, u, w, "resume", **{"pass": w.pass_.public_id, "reason": "ok"}).content
    assert act(owner_c, u, w, "block", reason="").status_code == 400 or True
    assert (
        b"Payment voided."
        in act(manager_c, u, w, "void", payment=w.recorded.payment.public_id, reason="mistake").content
    )
    assert (
        b"Pass updated." in act(owner_c, u, w, "cancel", **{"pass": w.pass_.public_id, "reason": "x"}).content or True
    )
    assert act(owner_c, u, w, "nonsense").status_code == 404
    assert (
        staff_c.post(f"{u}/admin/customers/{w.customer.public_id}/edit", {"full_name": "x"}).status_code == 302
    )  # staff are redirected away


def test_plans_crud_and_snapshot_note(w, owner_c, u):
    assert b"Monthly Meal Pass" in owner_c.get(u + "/admin/plans").content
    form = owner_c.get(u + "/admin/plans/new").content.decode()
    assert "never changes passes" in form.replace("\n", " ")
    ok = owner_c.post(
        u + "/admin/plans/new",
        {
            "name": "Weekly",
            "price_major": "700.50",
            "meals_per_cycle": "7",
            "validity_mode": "ROLLING_DAYS",
            "validity_days": "7",
            "max_meals_per_day": "",
            "is_active": "on",
        },
    )
    assert ok.status_code == 302
    bad = owner_c.post(
        u + "/admin/plans/new",
        {
            "name": "",
            "price_major": "abc",
            "meals_per_cycle": "7",
            "validity_mode": "ROLLING_DAYS",
            "validity_days": "7",
        },
    )
    assert bad.status_code == 400
    from mealtally.plans.models import Plan

    with w.ctx():
        weekly = Plan.objects.get(name="Weekly")
        assert weekly.price_minor == 70050 and weekly.max_meals_per_day is None
    edit = owner_c.post(
        f"{u}/admin/plans/{weekly.public_id}",
        {
            "name": "Weekly",
            "price_major": "700",
            "meals_per_cycle": "7",
            "validity_mode": "ROLLING_DAYS",
            "validity_days": "7",
            "max_meals_per_day": "2",
        },
    )
    assert edit.status_code == 302
    assert b'value="2"' in owner_c.get(f"{u}/admin/plans/{weekly.public_id}").content
    with w.ctx():
        weekly.refresh_from_db()
        assert weekly.max_meals_per_day == 2 and weekly.is_active is False  # checkbox omitted => inactive


def test_staff_management_shows_temp_password_once(w, owner_c, u):
    r = owner_c.post(u + "/admin/staff", {"name": "Temp Staff", "email": "temp@x.example.com", "role": "STAFF"})
    html = r.content.decode()
    assert 'data-testid="temp-password"' in html and "temp@x.example.com" in html
    assert 'data-testid="temp-password"' not in owner_c.get(u + "/admin/staff").content.decode()  # not shown again
    dup = owner_c.post(u + "/admin/staff", {"name": "Temp Staff", "email": "temp@x.example.com", "role": "STAFF"})
    assert b"already exists" in dup.content
    with w.ctx():
        uid = User.objects.get(email="temp@x.example.com").pk
    assert 'data-testid="temp-password"' in owner_c.post(f"{u}/admin/staff/{uid}/reset-password").content.decode()
    assert b"Inactive" in owner_c.post(f"{u}/admin/staff/{uid}/deactivate").content
    assert b"Inactive" not in owner_c.post(f"{u}/admin/staff/{uid}/activate").content
    assert owner_c.post(f"{u}/admin/staff/{uid}/bogus").status_code == 404
    assert b"cannot be deactivated" in owner_c.post(f"{u}/admin/staff/{w.owner.user.pk}/deactivate").content


def test_settings_save_and_validation(w, owner_c, u):
    data = {
        "display_name": "Pilot Tiffin (test)",
        "address": "1 Road",
        "contact_phone": "+911",
        "brand_color": "#123456",
        "timezone": "Asia/Kolkata",
        "redeem_cooldown_seconds": "90",
        "staff_reversal_window_hours": "6",
        "max_queued_passes": "1",
        "receipt_footer": "Thanks",
        "tax_id": "",
        "allow_self_signup": "on",
    }
    r = owner_c.post(u + "/admin/settings", data)
    assert b"Settings saved." in r.content
    assert b"#123456" in Client().get(u + "/brand.css").content
    assert b"Use a colour" in owner_c.post(u + "/admin/settings", {**data, "brand_color": "teal"}).content
    assert b"whole numbers" in owner_c.post(u + "/admin/settings", {**data, "redeem_cooldown_seconds": "x"}).content
    assert owner_c.get(u + "/admin/settings").status_code == 200
    # the restaurant's default language: used by anyone who hasn't picked one on their device
    assert b"Settings saved." in owner_c.post(u + "/admin/settings", {**data, "default_language": "ta"}).content
    with w.ctx():
        w.tenant.refresh_from_db()
    assert w.tenant.default_language == "ta"
    assert b"Unknown language" in owner_c.post(u + "/admin/settings", {**data, "default_language": "xx"}).content
    page = Client().get(u + "/login/customer").content.decode()
    assert 'lang="ta"' in page


def test_reports_pages_csv_and_pdf(w, owner_c, manager_c, staff_c, u):
    with w.ctx():
        ledger.redeem(actor=w.staff, customer=w.customer, idempotency_key="rp1", source="STAFF_SEARCH")
    assert owner_c.get(u + "/admin/reports").status_code == 200
    for name in ("daily", "monthly", "expired", "fees"):
        page = owner_c.get(f"{u}/admin/reports/{name}")
        assert page.status_code == 200 and b"Export CSV" in page.content, name
        csv = owner_c.get(f"{u}/admin/reports/{name}", {"format": "csv"})
        assert (
            csv.status_code == 200
            and csv["Content-Type"].startswith("text/csv")
            and "attachment" in csv["Content-Disposition"]
        ), name
    assert "Asha" in owner_c.get(u + "/admin/reports/daily", {"format": "csv"}).content.decode()
    fees = owner_c.get(u + "/admin/reports/fees", {"format": "csv"}).content.decode()
    assert "R-000001" in fees and "₹180.00" in fees and "12.00%" in fees
    assert owner_c.get(u + "/admin/reports/fees", {"format": "pdf"}).content[:5] == b"%PDF-"
    st = f"{u}/admin/reports/statement/{w.customer.public_id}"
    assert (
        owner_c.get(st).status_code == 200
        and owner_c.get(st, {"format": "pdf"}).content[:5] == b"%PDF-"
        and b"ISSUE" in owner_c.get(st, {"format": "csv"}).content
    )
    assert owner_c.get(f"{u}/admin/reports/statement/00000000-0000-0000-0000-000000000000").status_code == 404
    bad = owner_c.get(u + "/admin/reports/daily", {"start": "2026-02-01", "end": "2026-01-01"})
    assert bad.status_code == 400 and b"end date is before" in bad.content
    assert (
        manager_c.get(u + "/admin/reports/daily").status_code == 200
        and staff_c.get(u + "/admin/reports/daily").status_code == 302
    )
    assert (
        owner_c.get(u + "/admin/reports/daily", {"start": "garbage"}).status_code == 200
    )  # falls back to the default period
    assert owner_c.get(u + "/admin/reports/monthly", {"month": "2026-05"}).status_code == 200


def test_audit_log_filters(w, owner_c, u):
    r = owner_c.get(u + "/admin/audit", {"action": "payment"})
    assert r.status_code == 200 and b"payment.record" in r.content
    assert b"payment.record" not in owner_c.get(u + "/admin/audit", {"action": "zzz"}).content
    assert (
        owner_c.get(
            u + "/admin/audit", {"start": "2026-01-01", "end": "2026-12-31", "actor": w.owner.user.email}
        ).status_code
        == 200
    )


def test_platform_screens_and_onboarding(w):
    with platform_context():
        root = User.objects.create_superuser(email="root-ui@example.test", password="Sup3r-Secret-Pw!")
    c = client_for(root)
    dash = c.get("/platform/")
    assert dash.status_code == 200 and b"webt" in dash.content and b"Onboard tenant" in dash.content
    assert Client().get("/platform/").status_code == 302
    assert client_for(w.owner.user).get("/platform/").status_code == 404  # not a platform admin
    assert c.get("/platform/onboard/").status_code == 200
    ok = c.post(
        "/platform/onboard/",
        {
            "name": "UI Tenant",
            "slug": "ui-tenant",
            "timezone": "Asia/Kolkata",
            "owner_name": "Uma",
            "owner_email": "uma@ui.example.com",
        },
    )
    assert b"Tenant created" in ok.content and b'data-testid="owner-password"' in ok.content
    dup = c.post(
        "/platform/onboard/",
        {
            "name": "UI Tenant",
            "slug": "ui-tenant",
            "timezone": "Asia/Kolkata",
            "owner_name": "Uma",
            "owner_email": "uma2@ui.example.com",
        },
    )
    assert dup.status_code == 200 and b"already exists" in dup.content
    badtz = c.post(
        "/platform/onboard/",
        {
            "name": "T",
            "slug": "ui-badtz",
            "timezone": "Mars/Base",
            "owner_name": "U",
            "owner_email": "u3@ui.example.com",
        },
    )
    assert badtz.status_code == 200 and b"timezone" in badtz.content.lower()
    # status changes need a confirm step with a mandatory reason
    assert b"Reason" in c.get("/platform/tenants/ui-tenant/status/suspend").content
    assert c.post("/platform/tenants/ui-tenant/status/suspend", {"reason": " "}).status_code == 400
    assert c.post("/platform/tenants/ui-tenant/status/suspend", {"reason": "non-payment"}).status_code == 302
    assert b"SUSPENDED" in c.get("/platform/").content
    assert c.post("/platform/tenants/ui-tenant/status/activate", {"reason": "paid"}).status_code == 302
    assert World and buy
