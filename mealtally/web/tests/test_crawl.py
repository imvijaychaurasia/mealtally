# SPDX-License-Identifier: AGPL-3.0-only
"""Seeded-data crawl (D02.1 section 4) -- runs in default CI.

Loads ``seed_demo`` into a pilot-like tenant (back-dated payments, an expired pass, a queued pass, a void),
logs in as owner, staff, a demo customer and the platform admin, and GETs every navigable page and every report for the
current and previous month. It asserts: 200, no server-error text, no x100 money (nothing above Rs 10,000 in demo data),
and that every fee headline equals the sum of its lines.
"""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from mealtally.accounts.models import User
from mealtally.billing import fees
from mealtally.billing import services as billing
from mealtally.billing.models import Payment
from mealtally.common.money import format_money
from mealtally.customers import services as customers
from mealtally.customers.models import Customer
from mealtally.tenancy.context import platform_context
from mealtally.testing import World

from .conftest import client_for

pytestmark = pytest.mark.django_db
SLUG = "crawl-pilot"
MONEY = re.compile(r"₹([\d,]+)\.(\d{2})")
FORBIDDEN = (
    "Server Error",
    "Traceback (most recent call last)",
    "TemplateSyntaxError",
    "VariableDoesNotExist",
    "150,000",
    "1,50,000",
)
SKIP = ("/logout", "/static/", "/api/", "/sw.js", "/offline/", "/manifest")


def to_minor(text: str) -> int:
    m = MONEY.fullmatch(text.strip())
    return int(m.group(1).replace(",", "")) * 100 + int(m.group(2))


def check_body(path: str, resp) -> None:
    assert resp.status_code == 200, f"{path} -> {resp.status_code}"
    ctype = resp["Content-Type"]
    if ctype.startswith("text/html"):
        body = resp.content.decode()
        for bad in FORBIDDEN:
            assert bad not in body, f"{path}: contains {bad!r}"
        for rupees, _minor in MONEY.findall(body):
            assert int(rupees.replace(",", "")) <= 10_000, (
                f"{path}: amount ₹{rupees} is too large for demo data (x100 bug?)"
            )
    elif ctype.startswith("application/pdf"):
        assert resp.content[:5] == b"%PDF-", path


def links(html: str) -> set[str]:
    out = set()
    for href in re.findall(r'href="([^"#]+)"', html):
        clean = href.replace("&amp;", "&")
        if clean.startswith("/") and not clean.startswith(SKIP):
            out.add(clean)
    return out


def crawl(client, starts, seen: set[str], limit=250) -> int:
    queue, count = list(starts), 0
    while queue and count < limit:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        resp = client.get(path)
        check_body(path, resp)
        count += 1
        if resp["Content-Type"].startswith("text/html"):
            queue.extend(p for p in links(resp.content.decode()) if p not in seen)
    return count


@pytest.fixture
def pilot(capsys):
    w = World(slug=SLUG, buy_pass=False)
    call_command("seed_demo", "--slug", SLUG)
    capsys.readouterr()
    with w.ctx():
        demo = list(Customer.objects.filter(full_name__startswith="Demo"))
        mid = next(c for c in demo if c.full_name == "Demo Mid-use")
        customers.reset_pin(actor=w.owner, customer=mid, pin="482916")
        mid.refresh_from_db()
        mid.must_change_pin = False
        mid.save()
        fresh = next(c for c in demo if c.full_name == "Demo Fresh")
        # one void so reversals are in the numbers (Fresh has no redemptions yet)
        billing.void_payment(
            actor=w.owner, payment_public_id=Payment.objects.get(customer=fresh).public_id, reason="crawl void"
        )
    with platform_context():
        admin = User.objects.create_superuser(email="crawl-root@example.test", password="Sup3r-Secret-Pw!")
    return w, demo, mid, admin


def months(w):
    y, m = fees.local_month(w.tenant)
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    return [(y, m), (py, pm)]


def test_every_page_for_every_role_renders_with_sane_money_and_consistent_fees(pilot):
    w, demo, mid, admin = pilot
    base = f"/t/{SLUG}"
    seen: set[str] = set()
    n = 0

    # ---- owner ------------------------------------------------------------------------------------------------
    owner = client_for(w.owner.user)
    starts = [
        base + p
        for p in (
            "/admin/",
            "/admin/customers",
            "/admin/plans",
            "/admin/plans/new",
            "/admin/staff",
            "/admin/settings",
            "/admin/reports",
            "/admin/audit",
            "/admin/more",
            "/staff/",
            "/staff/sell",
            "/staff/customers",
            "/staff/today",
        )
    ]
    for y, m in months(w):
        for rep in ("monthly", "fees"):
            starts.append(f"{base}/admin/reports/{rep}?month={y}-{m:02d}")
        starts.append(f"{base}/admin/reports/fees?month={y}-{m:02d}&format=csv")
    starts += [f"{base}/admin/reports/daily", f"{base}/admin/reports/expired"]
    with w.ctx():
        starts += [f"{base}/admin/customers/{c.public_id}" for c in demo]
        starts += [f"{base}/admin/reports/statement/{c.public_id}" for c in demo]
        starts += [f"{base}/receipt/{p.public_id}" for p in Payment.objects.all()]
        starts += [f"{base}/receipt/{p.public_id}.pdf" for p in Payment.objects.all()[:2]]
    n += crawl(owner, starts, seen)
    assert n >= 40, n

    # ---- staff ------------------------------------------------------------------------------------------------
    staff = client_for(w.staff.user)
    n += crawl(
        staff,
        [
            base + "/staff/",
            base + "/staff/sell",
            base + "/staff/customers",
            base + "/staff/customers/new",
            f"{base}/staff/search?q=Demo",
            f"{base}/staff/card/{mid.public_id}",
        ],
        set(),
    )

    # ---- demo customer ------------------------------------------------------------------------------------------
    cust = client_for(mid.user, "mealtally.accounts.backends.CustomerPinBackend")
    n += crawl(
        cust,
        [
            base + p
            for p in ("/me/", "/me/qr", "/me/qr/fragment", "/me/history", "/me/payments", "/me/profile", "/me/pin")
        ],
        set(),
    )

    # ---- platform admin ------------------------------------------------------------------------------------------
    plat = client_for(admin)
    pstarts = [
        "/platform/",
        "/platform/?show_test=1",
        "/platform/onboard/",
        f"/platform/tenants/{SLUG}",
        f"/platform/tenants/{SLUG}/status/suspend",
    ]
    for y, m in months(w):
        pstarts += [
            f"/platform/tenants/{SLUG}?month={y}-{m:02d}",
            f"/platform/tenants/{SLUG}/fees?month={y}-{m:02d}&format=csv",
            f"/platform/tenants/{SLUG}/fees?month={y}-{m:02d}&format=pdf",
        ]
    n += crawl(plat, pstarts, set())
    assert n >= 60, n

    # ---- the invoice number: headline == sum of lines, everywhere it appears ----------------------------------------
    for y, m in months(w):
        tag = f"{y}-{m:02d}"
        with w.ctx():
            stmt = billing.fee_statement(actor=w.owner, year=y, month=m)
        assert stmt["total_fee_minor"] == sum(line["net_minor"] for line in stmt["lines"])
        html = owner.get(f"{base}/admin/reports/fees?month={tag}").content.decode()
        headline = re.search(r"Net payable to platform</dt>\s*<dd[^>]*>(₹[\d,]+\.\d{2})", html)
        assert headline and to_minor(headline.group(1)) == stmt["total_fee_minor"], tag
        csv_rows = list(
            csv.reader(io.StringIO(owner.get(f"{base}/admin/reports/fees?month={tag}&format=csv").content.decode()))
        )
        line_nets = [to_minor(r[-1]) for r in csv_rows[1:] if r and r[0].startswith("R-")]
        assert sum(line_nets) == stmt["total_fee_minor"], (
            f"{tag}: CSV lines {sum(line_nets)} != headline {stmt['total_fee_minor']}"
        )
        phtml = plat.get(f"/platform/tenants/{SLUG}?month={tag}").content.decode()
        ptotal = re.search(r'data-testid="tenant-fee-total">(₹[\d,]+\.\d{2})', phtml)
        assert ptotal and to_minor(ptotal.group(1)) == stmt["total_fee_minor"], f"platform tenant page {tag}"
        pcsv = list(
            csv.reader(io.StringIO(plat.get(f"/platform/tenants/{SLUG}/fees?month={tag}&format=csv").content.decode()))
        )
        assert sum(to_minor(r[-1]) for r in pcsv[1:] if r and r[0].startswith("R-")) == stmt["total_fee_minor"]
        assert to_minor(pcsv[-1][-1]) == stmt["total_fee_minor"]  # TOTAL row
    y, m = months(w)[0]
    with w.ctx():
        current = billing.fee_statement(actor=w.owner, year=y, month=m)["total_fee_minor"]
    dash = owner.get(f"{base}/admin/").content.decode()
    shown = re.search(r'data-testid="t-fee">(₹[\d,]+\.\d{2})', dash)
    assert shown and to_minor(shown.group(1)) == current, "tenant dashboard fee headline"
    prow = re.search(rf'data-slug="{SLUG}".*?</tr>', plat.get("/platform/", {"show_test": "1"}).content.decode(), re.S)
    assert prow and format_money(current) in prow.group(0), "platform dashboard fee headline"
    # sanity: demo data really spans several months (the bug needed back-dated payments)
    with w.ctx():
        received = {p.received_at.astimezone(w.tenant.zone).strftime("%Y-%m") for p in Payment.objects.all()}
    assert len(received) >= 2 and timezone.now() and Decimal(0) == 0
