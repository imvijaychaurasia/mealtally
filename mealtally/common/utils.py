# SPDX-License-Identifier: AGPL-3.0-only
"""Small pure helpers: tenant-local time and rounding. Money is in .money, phones in .country."""

from __future__ import annotations

from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from decimal import ROUND_HALF_UP
from decimal import Decimal
from zoneinfo import ZoneInfo

# --- money -------------------------------------------------------------------


def percent_of_minor(base_minor: int, pct: Decimal) -> int:
    """``base * pct / 100`` rounded HALF_UP to whole minor. 12% of 150000 = 18000."""
    amount = (Decimal(base_minor) * Decimal(pct)) / Decimal(100)
    return int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --- time --------------------------------------------------------------------


def tz_of(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def local_date(moment: datetime, tz_name: str) -> date:
    return moment.astimezone(tz_of(tz_name)).date()


def end_of_local_day(day: date, tz_name: str) -> datetime:
    """Last representable instant of ``day`` in the tenant zone, returned in UTC."""
    tz = tz_of(tz_name)
    return datetime.combine(day, time(23, 59, 59, 999999), tzinfo=tz).astimezone(UTC)


def start_of_local_day(day: date, tz_name: str) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=tz_of(tz_name)).astimezone(UTC)


def first_of_next_month(day: date) -> date:
    return (day.replace(day=1) + timedelta(days=32)).replace(day=1)


def last_of_month(day: date) -> date:
    return first_of_next_month(day) - timedelta(days=1)
