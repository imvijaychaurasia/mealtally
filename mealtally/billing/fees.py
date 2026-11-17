# SPDX-License-Identifier: AGPL-3.0-only
"""THE platform-fee reporting function. It becomes an invoice, so there is exactly one implementation.

Binding rule:
* a **charge** belongs to the tenant-local month of the payment's ``received_at``;
* a **void reversal** belongs to the tenant-local month of the payment's ``voided_at``.

The statement, the tenant dashboard, the platform dashboard and the platform tenant page all call :func:`fee_month`;
its headline numbers are computed *from the same line items it returns*, so they cannot disagree.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from mealtally.common.utils import start_of_local_day

from .models import Payment
from .models import PlatformFeeEntry


def month_bounds(tenant, year: int, month: int) -> tuple[datetime, datetime]:
    first = datetime(year, month, 1).date()  # noqa: DTZ001
    nxt = datetime(year + (month == 12), month % 12 + 1, 1).date()  # noqa: DTZ001
    return start_of_local_day(first, tenant.timezone), start_of_local_day(nxt, tenant.timezone)


def fee_month(tenant, year: int, month: int) -> dict:
    """Fee lines + totals for one tenant-local calendar month. Works in tenant *or* platform context."""
    start, end = month_bounds(tenant, year, month)
    base = PlatformFeeEntry.objects.filter(tenant_id=tenant.id).select_related("payment", "payment__customer")
    charges = list(base.filter(sign=1, payment__received_at__gte=start, payment__received_at__lt=end).order_by("id"))
    reversals = list(base.filter(sign=-1, payment__voided_at__gte=start, payment__voided_at__lt=end).order_by("id"))

    by_payment: dict[int, dict] = defaultdict(lambda: {"charged": 0, "reversed": 0, "pct": "", "payment": None})
    totals = {PlatformFeeEntry.Kind.PLATFORM: 0, PlatformFeeEntry.Kind.GATEWAY: 0}
    for entry in charges:
        row = by_payment[entry.payment_id]
        row["payment"] = entry.payment
        row["charged"] += entry.amount_minor
        if entry.kind == PlatformFeeEntry.Kind.PLATFORM:
            row["pct"] = str(entry.pct)
        totals[entry.kind] += entry.amount_minor
    for entry in reversals:
        row = by_payment[entry.payment_id]
        row["payment"] = entry.payment
        row["reversed"] += entry.amount_minor
        if not row["pct"] and entry.kind == PlatformFeeEntry.Kind.PLATFORM:
            row["pct"] = str(entry.pct)
        totals[entry.kind] -= entry.amount_minor

    zone = tenant.zone
    lines = []
    for row in sorted(by_payment.values(), key=lambda r: r["payment"].id):
        p = row["payment"]
        lines.append(
            {
                "payment_id": str(p.public_id),
                "receipt_number": p.receipt_number,
                "date": p.received_at.astimezone(zone).isoformat(),
                "customer": p.customer.full_name,
                "status": p.status,
                "base_minor": p.amount_minor,
                "platform_pct": row["pct"],
                "fee_minor": row["charged"],
                "reversed_minor": row["reversed"],
                "net_minor": row["charged"] - row["reversed"],
            }
        )
    platform, gateway = totals[PlatformFeeEntry.Kind.PLATFORM], totals[PlatformFeeEntry.Kind.GATEWAY]
    assert platform + gateway == sum(line["net_minor"] for line in lines)  # headline == sum of lines, by construction  # noqa: S101

    received = Payment.objects.filter(tenant_id=tenant.id, received_at__gte=start, received_at__lt=end)
    recorded = received.filter(status=Payment.Status.RECORDED)
    voided = Payment.objects.filter(
        tenant_id=tenant.id, voided_at__gte=start, voided_at__lt=end, status=Payment.Status.VOIDED
    )
    gross = sum(p.amount_minor for p in recorded.only("amount_minor"))
    return {
        "month": f"{year:04d}-{month:02d}",
        "lines": lines,
        "entries": [*charges, *reversals],
        "platform_fee_minor": platform,
        "gateway_fee_minor": gateway,
        "total_minor": platform + gateway,
        "gross_minor": gross,
        "payments_count": recorded.count(),
        "voided_count": voided.count(),
    }


def local_month(tenant, moment: datetime | None = None) -> tuple[int, int]:
    from django.utils import timezone  # noqa: PLC0415

    local = (moment or timezone.now()).astimezone(tenant.zone)
    return local.year, local.month
