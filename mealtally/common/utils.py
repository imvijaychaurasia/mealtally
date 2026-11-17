"""Small pure helpers: money, phone numbers, tenant-local time."""

from __future__ import annotations

import re
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from decimal import ROUND_HALF_UP
from decimal import Decimal
from zoneinfo import ZoneInfo

from .errors import ValidationFailed

# --- money -------------------------------------------------------------------


def percent_of_paise(base_paise: int, pct: Decimal) -> int:
    """``base * pct / 100`` rounded HALF_UP to whole paise. 12% of 150000 = 18000."""
    amount = (Decimal(base_paise) * Decimal(pct)) / Decimal(100)
    return int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_inr(paise: int, *, symbol: bool = True) -> str:
    """THE money formatter: integer paise -> ``₹1,500.00`` with Indian digit grouping (``₹1,50,000.00``).

    Every screen, CSV and PDF goes through this (template filter ``|inr``); amounts are never divided elsewhere.
    """
    paise = int(paise)
    sign = "-" if paise < 0 else ""
    rupees, ps = divmod(abs(paise), 100)
    digits = str(rupees)
    if len(digits) > 3:  # noqa: PLR2004
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:  # noqa: PLR2004
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join([*groups, tail])
    return f"{sign}{'₹' if symbol else ''}{digits}.{ps:02d}"


def inr_compact(paise) -> str:
    """Compact Indian notation for tiles and chart axes: ``₹1.24L``, ``₹82.1K``, ``₹1.2Cr``. Full value: ``format_inr``.

    Below ₹1,000 the rupee amount is shown as is; rounding that reaches the next unit promotes it (₹99,99x -> ₹1L).
    """
    value = int(paise or 0)
    sign = "-" if value < 0 else ""
    rupees = abs(value) / 100
    units = ((10_000_000, "Cr", 2), (100_000, "L", 2), (1_000, "K", 1))
    for size, suffix, places in units:
        if rupees >= size:
            scaled = round(rupees / size, places)
            if suffix == "K" and scaled >= 100:  # 99,950+ -> 100.0K == 1L
                return f"{sign}\u20b91L"
            if suffix == "L" and scaled >= 100:  # 99,95,000+ -> 100L == 1Cr
                return f"{sign}\u20b91Cr"
            text = f"{scaled:.{places}f}".rstrip("0").rstrip(".")
            return f"{sign}\u20b9{text}{suffix}"
    whole = round(rupees)
    return f"{sign}\u20b9{whole}" if abs(rupees - whole) < 0.005 else f"{sign}\u20b9{rupees:.2f}"


def per_meal_inr(price_paise: int, meals: int) -> str:
    """``₹50`` per meal (whole rupees when exact, else with paise)."""
    if not meals:
        return ""
    each = price_paise / meals
    return format_inr(round(each)).removesuffix(".00") if round(each) % 100 == 0 else format_inr(round(each))


# --- phone numbers -----------------------------------------------------------

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw: str, default_country_code: str = "91") -> str:
    """Return an E.164 number. 10-digit Indian mobiles get ``+91``."""
    cleaned = re.sub(r"[\s\-().]", "", (raw or "").strip())
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if not cleaned.startswith("+"):
        digits = re.sub(r"\D", "", cleaned)
        if len(digits) == 10:  # noqa: PLR2004
            cleaned = f"+{default_country_code}{digits}"
        elif len(digits) == 12 and digits.startswith(default_country_code):  # noqa: PLR2004
            cleaned = f"+{digits}"
        elif len(digits) == 11 and digits.startswith("0"):  # noqa: PLR2004
            cleaned = f"+{default_country_code}{digits[1:]}"
        else:
            cleaned = f"+{digits}"
    if not _E164.match(cleaned):
        raise ValidationFailed("Enter a valid phone number.", details={"field": "phone"})
    return cleaned


def format_phone(phone: str) -> str:
    """Readable phone (QA-01 P2-8): ``+91 90000 30002`` for India, others in E.164 groups (``+44 79111 23456``)."""
    phone = (phone or "").strip()
    digits = phone[1:] if phone.startswith("+") else phone
    if not digits.isdigit():
        return phone
    if digits.startswith("91") and len(digits) == 12:  # noqa: PLR2004
        return f"+91 {digits[2:7]} {digits[7:]}"
    if len(digits) <= 4:  # noqa: PLR2004
        return phone
    three = {"971", "966", "974", "965", "968", "973", "880", "977", "975", "960", "852", "353", "351", "358"}
    cc = 3 if digits[:3] in three else 1 if digits[0] in "17" else 2
    rest = digits[cc:]
    mid = len(rest) // 2 if len(rest) > 7 else len(rest)  # noqa: PLR2004
    return " ".join(part for part in (f"+{digits[:cc]}", rest[:mid], rest[mid:]) if part.strip("+"))


def mask_phone(phone: str) -> str:
    """Staff match customers on the LAST four digits, so those stay visible: ``••••• 0002``."""
    return f"\u2022\u2022\u2022\u2022\u2022 {phone[-4:]}" if len(phone) > 4 else phone  # noqa: PLR2004


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
