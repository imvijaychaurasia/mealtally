"""D03.9 QA-01 P1-2..P1-5: the preview dataset is built from the tenant's REAL customers, wallets, drivers and slots."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from mealtally.accounts.models import Membership
from mealtally.audit.models import AuditEvent
from mealtally.customers.models import Customer
from mealtally.passes.models import Pass
from mealtally.preview import data as pvdata
from mealtally.preview import util
from mealtally.tenancy.context import tenant_context
from mealtally.tenancy.models import Tenant
from mealtally.web.tests.conftest import client_for

from .test_preview import CUSTOMER_BACKEND
from .test_preview import SLUG
from .test_preview import clients  # noqa: F401 (fixture)
from .test_preview import demo  # noqa: F401 (fixture)
from .test_preview import tid
from .test_preview import user

pytestmark = pytest.mark.django_db


def dataset():
    with tenant_context(tid()):
        return pvdata.for_tenant(Tenant.objects.get(slug=SLUG))


def customer_client(name):
    with tenant_context(tid()):
        c = Customer.objects.select_related("user").get(full_name=name)
    return client_for(c.user, CUSTOMER_BACKEND)


def test_every_name_on_the_preview_pages_is_a_real_customer_of_the_tenant(demo):  # noqa: F811
    D = dataset()
    with tenant_context(tid()):
        real = set(Customer.objects.values_list("full_name", flat=True))
        drivers = set(Membership.objects.filter(role="DRIVER").values_list("user__name", flat=True))
    shown = {s["name"] for s in D["subscribers"]}
    shown |= {o["customer"] for o in D["orders"] if o["customer"] != "Walk-in"}
    shown |= {t["customer"] for t in D["topups"]} | {i["customer"] for i in D["invoices"]}
    shown |= {h["customer"] for h in D["holds"]} | {o["customer"] for o in D["ck_orders"]}
    assert shown, "the dataset shows customers"
    assert shown <= real, f"invented names: {sorted(shown - real)}"
    assert {r["driver"] for r in D["routes"]} <= drivers
    # addresses are the customers' own
    with tenant_context(tid()):
        addresses = dict(Customer.objects.values_list("full_name", "address"))
    assert all(s["address"] == addresses[s["name"]] for s in D["subscribers"])


def test_only_wallet_subscribers_have_a_wallet_and_balances_vary(demo):  # noqa: F811
    D = dataset()
    with tenant_context(tid()):
        # blocked customers are left out of the preview (they can't order)
        flagged = set(Customer.objects.filter(has_wallet=True, status="ACTIVE").values_list("full_name", flat=True))
        total = Customer.objects.count()
    assert {s["name"] for s in D["subscribers"]} == flagged
    assert total * 0.4 <= len(flagged) <= total * 0.6  # about half
    balances = {s["balance_minor"] for s in D["subscribers"]}
    days = {s["days_left"] for s in D["subscribers"]}
    assert len(balances) > len(D["subscribers"]) // 2 and len(days) > 2


def test_a_customer_without_a_wallet_sees_no_wallet_anywhere(demo):  # noqa: F811
    with tenant_context(tid()):
        name = Customer.objects.filter(has_wallet=False).order_by("customer_code").first().full_name
    c = customer_client(name)
    home = c.get(f"/t/{SLUG}/me/").content.decode()
    assert 'data-testid="home-no-wallet"' in home and 'data-testid="home-wallet"' not in home
    assert reverse("preview:me-wallet", args=[SLUG]) not in home  # no Wallet tab
    page = c.get(reverse("preview:me-wallet", args=[SLUG])).content.decode()
    assert 'data-testid="no-wallet"' in page and "Ask the restaurant about home delivery" in page
    order = c.get(reverse("preview:me-order", args=[SLUG])).content.decode()
    assert "Paid from your wallet" not in order and "Pay on delivery or at the counter" in order


def test_two_wallet_customers_see_their_own_balance(demo):  # noqa: F811
    from mealtally.web.templatetags.mealtally_extras import money_consumer

    D = dataset()
    a, b = D["subscribers"][0], D["subscribers"][2]
    assert a["balance_minor"] != b["balance_minor"]
    pages = {}
    for s in (a, b):
        pages[s["name"]] = customer_client(s["name"]).get(reverse("preview:me-wallet", args=[SLUG])).content.decode()
        assert money_consumer(s["balance_minor"]) in pages[s["name"]]
    assert (
        money_consumer(b["balance_minor"]) not in pages[a["name"]].split("data-testid")[0]
        or pages[a["name"]] != pages[b["name"]]
    )


def test_drivers_see_their_own_route_and_the_owner_can_reassign(demo, clients):  # noqa: F811
    d1 = client_for(user("driver1@saffrontiffins.example.com"))
    d2 = client_for(user("driver2@saffrontiffins.example.com"))
    url = reverse("preview:driver", args=[SLUG])
    p1, p2 = d1.get(url).content.decode(), d2.get(url).content.decode()
    assert "Kothrud A" in p1 and "Ramesh Gawade" in p1 and "MH12 AB 4021" in p1
    assert "Kothrud B" in p2 and "Sunil Bhor" in p2 and "MH12 CD 7718" in p2
    delivery = clients["OWNER"].get(reverse("preview:delivery", args=[SLUG])).content.decode()
    assert 'data-testid="assign-A"' in delivery
    with tenant_context(tid()):
        m1 = Membership.objects.get(user__email="driver1@saffrontiffins.example.com", role="DRIVER")
    resp = clients["OWNER"].post(
        reverse("web:admin-driver-assign", args=[SLUG]), {"route": "Kothrud B", "driver": m1.pk}
    )
    assert resp.status_code == 302
    assert "Kothrud B" in d1.get(url).content.decode() and "Kothrud A" in d2.get(url).content.decode()
    with tenant_context(tid()):
        assert AuditEvent.objects.filter(action="driver.route_assign").count() == 1
    assert clients["STAFF"].post(reverse("web:admin-driver-assign", args=[SLUG]), {}).status_code in (302, 403, 404)


def test_the_cart_uses_the_customers_address_or_asks_for_one(demo):  # noqa: F811
    with tenant_context(tid()):
        c = Customer.objects.filter(has_wallet=True).order_by("customer_code").first()
        restaurant = Tenant.objects.get(slug=SLUG)
    page = customer_client(c.full_name).get(reverse("preview:me-order", args=[SLUG])).content.decode()
    assert (
        c.address in page
        and "Shivaji Society, Kothrud, Pune 411038" not in page.split('data-testid="cart-address"')[1][:300]
    )
    with tenant_context(tid()):
        Customer.objects.filter(pk=c.pk).update(address="")
    page = customer_client(c.full_name).get(reverse("preview:me-order", args=[SLUG])).content.decode()
    assert 'data-testid="cart-address-missing"' in page
    assert restaurant.slug == SLUG


def test_active_customers_counts_each_real_customer_once(demo, clients):  # noqa: F811
    from mealtally.common.country import format_phone

    D = dataset()
    with tenant_context(tid()):
        pass_phones = set(Pass.objects.filter(status="ACTIVE").values_list("customer__phone_e164", flat=True))
        total = Customer.objects.count()
    wallets = {s["phone"] for s in D["subscribers"] if s["status"] == "ACTIVE"}
    expected = len({format_phone(p) for p in pass_phones} | wallets)
    resp = clients["OWNER"].get(reverse("preview:today", args=[SLUG]))
    tile = next(t for t in resp.context["tiles"] if t["key"] == "customers")
    assert tile["value"] == expected <= total


def test_each_persona_cooks_a_different_menu():
    today = timezone.localdate()
    people = tuple((f"Person {n}", f"+91 90009 {n:05d}", "", True) for n in range(1, 13))
    a = pvdata.build(today, (people, (), (), 0))
    b = pvdata.build(today, (people, (), (), 3))
    day = next(today + timedelta(days=k) for k in range(7) if (today + timedelta(days=k)).weekday() < 6)
    ta = {r["name"]: r["qty"] for r in util.cooking_plan(pvdata.day_orders(a, day))}
    tb = {r["name"]: r["qty"] for r in util.cooking_plan(pvdata.day_orders(b, day))}
    assert ta and ta != tb
