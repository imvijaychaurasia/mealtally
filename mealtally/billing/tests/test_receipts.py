# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection

from mealtally.billing import receipts
from mealtally.billing import services as billing
from mealtally.billing.models import Payment
from mealtally.tenancy import services as tenancy
from mealtally.testing import World
from mealtally.testing import buy
from mealtally.testing import make_customer


@pytest.mark.django_db
def test_receipt_numbers_are_sequential_per_tenant():
    a, b = World(buy_pass=False), World(buy_pass=False)
    nums_a = [buy(a.tenant, a.owner, a.customer, a.plan).payment.receipt_number for _ in range(2)]
    nums_b = [buy(b.tenant, b.owner, b.customer, b.plan).payment.receipt_number]
    assert nums_a == ["R-000001", "R-000002"] and nums_b == ["R-000001"]


@pytest.mark.django_db(transaction=True)
def test_parallel_payments_never_share_a_receipt_number():
    w = World(buy_pass=False)
    people = [make_customer(w.tenant, w.owner, name=f"P{i}")[0] for i in range(8)]
    barrier = threading.Barrier(8)

    def pay(c):
        barrier.wait()
        try:
            return buy(w.tenant, w.owner, c, w.plan).payment.receipt_number
        finally:
            connection.close()

    with ThreadPoolExecutor(8) as pool:
        numbers = list(pool.map(pay, people))
    assert len(set(numbers)) == 8 and sorted(numbers) == [f"R-{i:06d}" for i in range(1, 9)]


@pytest.mark.django_db
def test_receipt_html_and_pdf_content_and_void_watermark():
    w = World()
    with w.ctx():
        row = tenancy.get_settings(w.tenant.id)
        row.address, row.contact_phone, row.tax_id, row.receipt_footer, row.display_name = (
            "12 MG Road",
            "+911234567890",
            "29ABCDE1234F1Z5",
            "Thank you!",
            "Sample Tiffin (test)",
        )
        row.save()
        payment = Payment.objects.select_related("customer", "plan").get(pk=w.recorded.payment.pk)
        html = receipts.render_receipt_html(payment, print_view=True)
        for needle in (
            "Sample Tiffin (test)",
            "12 MG Road",
            "29ABCDE1234F1Z5",
            "R-000001",
            "1,500.00",
            "Thank you!",
            "No refund or carry-forward",
            w.customer.customer_code,
        ):
            assert needle in html, needle
        assert "Void" not in html.replace("voidnote", "")
        pdf = receipts.render_receipt_pdf(payment)
        assert pdf[:5] == b"%PDF-" and len(pdf) > 2000
        billing.void_payment(actor=w.owner, payment_public_id=payment.public_id, reason="entered twice")
        voided = receipts.render_receipt_html(Payment.objects.select_related("customer", "plan").get(pk=payment.pk))
        assert 'class="void">Void' in voided and "entered twice" in voided
