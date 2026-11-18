# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import pytest

from mealtally.ledger import services as ledger
from mealtally.testing import World
from mealtally.testing import buy
from mealtally.testing import make_customer

from .conftest import client_for

pytestmark = pytest.mark.django_db


def done_pin(w):
    with w.ctx():
        c = w.customer.__class__.objects.get(pk=w.customer.pk)
        c.must_change_pin = False
        c.save()


def test_home_shows_balance_validity_and_no_refund_footer(w, cust_c, u):
    done_pin(w)
    with w.ctx():
        ledger.redeem(actor=w.staff, customer=w.customer, idempotency_key="h1", source="STAFF_SEARCH")
    r = cust_c.get(u + "/me/")
    html = r.content.decode()
    assert (
        r.status_code == 200
        and 'data-testid="balance">29<' in html
        and "of 30 meals left" in html
        and "days left" in html
    )
    assert "Meals today: 1" in html and "No refund or carry-forward of unused meals." in html and "Active" in html


def test_home_states_queued_warning_and_no_pass(w, cust_c, u):
    done_pin(w)
    buy(w.tenant, w.owner, w.customer, w.plan)
    html = cust_c.get(u + "/me/").content.decode()
    assert "Queued" in html and "Starts " in html
    w2 = World(slug="webnopass", buy_pass=False)
    c2 = client_for(w2.customer.user, "mealtally.accounts.backends.CustomerPinBackend")
    with w2.ctx():
        w2.customer.must_change_pin = False
        w2.customer.save()
    assert "No active pass" in c2.get("/t/webnopass/me/").content.decode()
    w3 = World(slug="weblow", plan_kwargs={"meals_per_cycle": 3})
    c3 = client_for(w3.customer.user, "mealtally.accounts.backends.CustomerPinBackend")
    with w3.ctx():
        w3.customer.must_change_pin = False
        w3.customer.save()
    assert "Running low" in c3.get("/t/weblow/me/").content.decode()  # <= 3 meals triggers the warning style


def test_qr_page_fragment_and_history_pagination(w, cust_c, u):
    done_pin(w)
    page = cust_c.get(u + "/me/qr").content.decode()
    assert (
        'hx-trigger="every 30s"' in page and "data:image/svg+xml;base64," in page and w.customer.customer_code in page
    )
    frag = cust_c.get(u + "/me/qr/fragment").content.decode()
    assert 'data-seconds="30"' in frag and "Refreshes in" in frag
    with w.ctx():
        for i in range(25):
            ledger.redeem(
                actor=w.staff,
                customer=w.customer,
                idempotency_key=f"pg{i}",
                source="STAFF_SEARCH",
                confirm_additional=True,
            )
    first = cust_c.get(u + "/me/history").content.decode()
    assert "Meal redeemed" in first and 'hx-trigger="revealed"' in first and "page=2" in first
    more = cust_c.get(u + "/me/history?page=2", HTTP_HX_REQUEST="true").content.decode()
    assert "Meals issued" in more and "<html" not in more and "revealed" not in more


def test_payments_profile_and_receipts_are_private(w, cust_c, u):
    done_pin(w)
    other = World(slug="webprivate")
    pay = w.recorded.payment
    assert b"R-000001" in cust_c.get(u + "/me/payments").content
    assert cust_c.get(f"{u}/receipt/{pay.public_id}").status_code == 200
    assert cust_c.get(f"{u}/receipt/{pay.public_id}.pdf")["Content-Type"] == "application/pdf"
    stranger = make_customer(w.tenant, w.owner, name="Stranger")[0]
    with w.ctx():
        stranger.must_change_pin = False
        stranger.save()
    assert (
        client_for(stranger.user, "mealtally.accounts.backends.CustomerPinBackend")
        .get(f"{u}/receipt/{pay.public_id}")
        .status_code
        == 404
    )
    assert cust_c.get(f"{u}/receipt/{other.recorded.payment.public_id}").status_code == 404  # another tenant's payment
    assert b"Valid" in cust_c.get(f"{u}/receipt/{pay.public_id}").content
    r = cust_c.post(u + "/me/profile", {"full_name": "Renamed"})
    assert b"Saved." in r.content
    assert b"Name is required" in cust_c.post(u + "/me/profile", {"full_name": " "}).content
    assert cust_c.get(u + "/me/pin").status_code == 200
