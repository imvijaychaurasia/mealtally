# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import pytest
from django.test import Client

from mealtally.customers import services as customers
from mealtally.tenancy import services as tenancy
from mealtally.testing import PASSWORD
from mealtally.testing import World
from mealtally.testing import make_user

from .conftest import client_for

pytestmark = pytest.mark.django_db


def test_landing_go_and_pwa_assets(client):
    r = client.get("/")
    assert (
        r.status_code == 200
        and b"Prepaid meal passes for restaurants" in r.content
        and b"Restaurant sign-in" in r.content
    )
    assert client.post("/go", {"code": " Sample Tiffin "}).headers["Location"] == "/t/sample-tiffin/"
    assert client.post("/go", {"code": ""}).status_code == 400
    m = client.get("/manifest.webmanifest")
    assert (
        m.status_code == 200 and m["Content-Type"].startswith("application/manifest+json") and b"icon-512" in m.content
    )
    sw = client.get("/sw.js")
    assert (
        sw.status_code == 200
        and b"/offline/" in sw.content
        and b"IndexedDB" not in sw.content
        and sw["Service-Worker-Allowed"] == "/"
    )
    assert client.get("/offline/").status_code == 200


def test_tenant_home_two_entry_points_unknown_slug_and_paused(w, client, u):
    r = client.get(u + "/")
    import html as _html

    assert (
        r.status_code == 200
        and "I'm a customer" in _html.unescape(r.content.decode())
        and b"Staff sign-in" in r.content
    )
    assert client.get("/t/nope-nope/").status_code == 404 and b"couldn" in client.get("/t/nope-nope/").content
    tenancy.set_status(tenant=w.tenant, status="SUSPENDED")
    p = client.get(u + "/")
    assert p.status_code == 403 and b"Service paused" in p.content
    assert client.get(u + "/staff/").status_code == 403  # nobody acts on a paused tenant


def test_brand_css_uses_tenant_colour(w, client, u):
    with w.ctx():
        tenancy.update_settings(actor=w.owner, brand_color="#aa5500")
    r = client.get(u + "/brand.css")
    assert r.status_code == 200 and b"--brand:#aa5500" in r.content and r["Content-Type"].startswith("text/css")


def test_customer_login_forces_pin_change_then_home(w, client, u):
    assert client.post(u + "/login/customer", {"phone": w.customer.phone_e164, "pin": "000000"}).status_code == 400
    r = client.post(u + "/login/customer", {"phone": w.customer.phone_e164, "pin": w.pin})
    assert r.status_code == 302 and r["Location"] == u + "/me/"
    assert client.get(u + "/me/").headers["Location"] == u + "/me/pin"  # must change PIN first
    bad = client.post(u + "/me/pin", {"old_pin": w.pin, "new_pin": "482916", "confirm_pin": "000000"})
    assert bad.status_code == 400 and b"do not match" in bad.content
    assert (
        client.post(u + "/me/pin", {"old_pin": w.pin, "new_pin": "482916", "confirm_pin": "482916"}).status_code == 302
    )
    home = client.get(u + "/me/")
    assert home.status_code == 200 and b"No refund or carry-forward" in home.content
    assert client.session.get_expiry_age() > 29 * 24 * 3600  # customers: 30-day session


def test_customer_login_lockout_message(w, client, u):
    for _ in range(5):
        client.post(u + "/login/customer", {"phone": w.customer.phone_e164, "pin": "000000"})
    r = client.post(u + "/login/customer", {"phone": w.customer.phone_e164, "pin": w.pin})
    assert r.status_code == 400 and b"15 minutes" in r.content


def test_staff_login_forces_password_change_and_routes_by_role(w, client, u):
    for actor, home in ((w.staff, "/staff/"), (w.manager, "/admin/"), (w.owner, "/admin/")):
        actor.user.must_change_password = False
        actor.user.save()
        c = Client()
        r = c.post(u + "/login/staff", {"login": actor.user.email, "password": PASSWORD})
        assert r.status_code == 302 and r["Location"] == u + home
        assert c.session.get_expiry_age() == 12 * 3600  # staff: 12 h
    fresh = make_user(w.tenant, "STAFF")
    fresh.must_change_password = True
    fresh.save()
    c = Client()
    c.post(u + "/login/staff", {"login": fresh.email, "password": PASSWORD})
    assert c.get(u + "/staff/").headers["Location"] == u + "/password"
    assert (
        c.post(u + "/password", {"old_password": PASSWORD, "new_password": "x", "confirm_password": "x"}).status_code
        == 400
    )
    assert (
        c.post(
            u + "/password",
            {"old_password": PASSWORD, "new_password": "Brand-New-Pass-77", "confirm_password": "different"},
        ).status_code
        == 400
    )
    ok = c.post(
        u + "/password",
        {"old_password": PASSWORD, "new_password": "Brand-New-Pass-77", "confirm_password": "Brand-New-Pass-77"},
    )
    assert ok.status_code == 302 and c.get(u + "/staff/").status_code == 200  # still logged in after the change


def test_staff_login_failures_and_wrong_tenant(w, client, u):
    other = World(slug="webother", buy_pass=False)
    assert client.post(u + "/login/staff", {"login": w.owner.user.email, "password": "nope"}).status_code == 400
    r = client.post(u + "/login/staff", {"login": other.owner.user.email, "password": PASSWORD})
    assert r.status_code == 403 and b"does not have staff access" in r.content  # a valid user of another tenant
    assert client.get(u + "/login/customer").status_code == 200 and client.get(u + "/login/staff").status_code == 200


def test_cross_tenant_access_is_404_and_roles_are_redirected(w, staff_c, cust_c, u):
    other = World(slug="webother2", buy_pass=False)
    for path in ("/staff/", "/admin/", "/me/", "/staff/sell"):
        assert staff_c.get(f"/t/{other.tenant.slug}{path}").status_code == 404
    assert staff_c.get(u + "/admin/").headers["Location"] == u + "/staff/"  # STAFF cannot use admin
    assert cust_c.get(u + "/staff/").headers["Location"] == u + "/me/"
    assert Client().get(u + "/me/").headers["Location"].startswith(u + "/?next=")


def test_global_login_single_tenant_picker_and_platform_admin(w, client):
    two = make_user(w.tenant, "STAFF")
    other = World(slug="webpick", buy_pass=False)
    from mealtally.accounts import services as accounts
    from mealtally.tenancy.context import platform_context

    with platform_context():
        accounts.ensure_membership(user=two, tenant_id=other.tenant.id, role="MANAGER")
    r = Client().post("/login", {"login": two.email, "password": PASSWORD})
    assert r.status_code == 200 and b"Choose a restaurant" in r.content and b"/t/webpick/admin/" in r.content
    r = Client().post("/login", {"login": w.owner.user.email, "password": PASSWORD})
    assert r.status_code == 302 and r["Location"].endswith("/admin/")
    assert Client().post("/login", {"login": "x@y.z", "password": "bad"}).status_code == 400
    assert Client().get("/login").status_code == 200


def test_logout_and_signup_flow(w, owner_c, u):
    assert owner_c.post("/logout", {"slug": w.tenant.slug}).headers["Location"] == u + "/"
    assert owner_c.get(u + "/admin/").status_code == 302
    c = Client()
    assert c.get(u + "/signup").status_code == 404  # off by default
    with w.ctx():
        from mealtally.tenancy import services as t

        t.update_settings(actor=w.owner, allow_self_signup=True)
    assert c.get(u + "/signup").status_code == 200
    bad = c.post(u + "/signup", {"full_name": "S", "phone": "9877777777", "pin": "12"})
    assert bad.status_code == 400
    ok = c.post(u + "/signup", {"full_name": "Selfie", "phone": "9877777777", "pin": "482916"})
    assert ok.status_code == 200 and b"pay at the counter" in ok.content
    with w.ctx():
        assert customers.verify_pin(tenant_slug=w.tenant.slug, phone="9877777777", pin="482916")


def test_unsafe_next_redirect_is_ignored(w, client, u):
    r = client.post(
        u + "/login/customer", {"phone": w.customer.phone_e164, "pin": w.pin, "next": "https://evil.example/x"}
    )
    assert r["Location"] == u + "/me/"
    assert client_for(w.owner.user)  # smoke
