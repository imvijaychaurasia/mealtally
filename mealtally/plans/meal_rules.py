# SPDX-License-Identifier: AGPL-3.0-only
"""Meal-time rules: which meal slot is open now (in the tenant's timezone), and plain-words rule summaries.

Pure functions over ``MealSlot`` rows. The redemption check itself lives in ``mealtally.ledger.services`` (in the locked
transaction); this module only answers "what slot is it?", "when is the next one?" and "how do we say the rule?".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.utils import formats
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from .models import MealSlot


def default_slots() -> list[dict]:
    """The meal times every new restaurant starts with: seed data in plans/seed/meal_slots.json (or the file in
    MEALTALLY_MEAL_SLOTS_FILE), not code."""
    import json  # noqa: PLC0415
    import os  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    path = os.environ.get("MEALTALLY_MEAL_SLOTS_FILE") or Path(__file__).with_name("seed") / "meal_slots.json"
    rows = json.loads(Path(path).read_text(encoding="utf-8"))["slots"]
    return [
        {
            "name": r["name"],
            "name_hi": r.get("name_hi", ""),
            "start_time": time.fromisoformat(r["start"]),
            "end_time": time.fromisoformat(r["end"]),
            "grace_minutes": int(r.get("grace_minutes", 0)),
            "sort_order": n,
        }
        for n, r in enumerate(rows, start=1)
    ]


def ensure_default_slots(tenant_id: int) -> list[MealSlot]:
    """Create the three default slots for a tenant that has none (idempotent)."""
    existing = list(MealSlot.objects.filter(tenant_id=tenant_id))
    if existing:
        return existing
    return [MealSlot.objects.create(tenant_id=tenant_id, **row) for row in default_slots()]


def slot_label(slot: MealSlot) -> str:
    if (get_language() or "").startswith("hi") and slot.name_hi:
        return slot.name_hi
    return slot.name


def crosses_midnight(slot: MealSlot) -> bool:
    return slot.end_time < slot.start_time


def window(slot: MealSlot, service_date: date, tz: ZoneInfo, *, with_grace: bool = True) -> tuple[datetime, datetime]:
    """Aware [open, close] of ``slot`` on the day it opens (``service_date``), grace included on both sides."""
    start = datetime.combine(service_date, slot.start_time, tzinfo=tz)
    end_day = service_date + timedelta(days=1) if crosses_midnight(slot) else service_date
    end = datetime.combine(end_day, slot.end_time, tzinfo=tz)
    if with_grace:
        grace = timedelta(minutes=slot.grace_minutes)
        start, end = start - grace, end + grace
    return start, end


@dataclass(frozen=True)
class OpenSlot:
    slot: MealSlot
    service_date: date  # the day the window opened: the meal's ``meal_date``


def open_slot(slots: list[MealSlot], now: datetime, tz: ZoneInfo) -> OpenSlot | None:
    """The first of ``slots`` (in sort order) open at ``now``; checks yesterday too for windows that cross midnight."""
    today = now.astimezone(tz).date()
    for slot in sorted(slots, key=lambda s: (s.sort_order, s.start_time, s.id or 0)):
        for day in (today, today - timedelta(days=1)):
            start, end = window(slot, day, tz)
            if start <= now <= end:
                return OpenSlot(slot, day)
    return None


def next_opening(slots: list[MealSlot], now: datetime, tz: ZoneInfo) -> tuple[MealSlot, datetime] | None:
    """The next slot start (without grace) after ``now``, within the coming week."""
    today = now.astimezone(tz).date()
    best: tuple[MealSlot, datetime] | None = None
    for slot in slots:
        for offset in range(8):
            start = datetime.combine(today + timedelta(days=offset), slot.start_time, tzinfo=tz)
            if start > now:
                if best is None or start < best[1]:
                    best = (slot, start)
                break
    return best


def hhmm(t: time | datetime) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def when(at: datetime, now: datetime, tz: ZoneInfo) -> str:
    """'today 12:00', 'tomorrow 12:00' or 'Monday 12:00' (tenant-local)."""
    local, today = at.astimezone(tz), now.astimezone(tz).date()
    if local.date() == today:
        day = _("today")
    elif local.date() == today + timedelta(days=1):
        day = _("tomorrow")
    else:
        day = formats.date_format(local, "l")
    return f"{day} {hhmm(local)}"


def served_text(slots: list[MealSlot]) -> str:
    """'Lunch is served 12:00–15:00' / 'Lunch 12:00–15:00 or Dinner 19:00–22:30'."""
    ordered = sorted(slots, key=lambda s: (s.sort_order, s.start_time))
    parts = [f"{slot_label(s)} {hhmm(s.start_time)}–{hhmm(s.end_time)}" for s in ordered]
    if len(ordered) == 1:
        s = ordered[0]
        return _("%(meal)s is served %(start)s–%(end)s") % {
            "meal": slot_label(s),
            "start": hhmm(s.start_time),
            "end": hhmm(s.end_time),
        }
    return _("Meals are served: %(list)s") % {"list": _(" or ").join(parts)}


def closed_message(slots: list[MealSlot], now: datetime, tz: ZoneInfo) -> tuple[str, datetime | None]:
    """'Lunch is served 12:00–15:00. Next: Monday 12:00.' and the next opening."""
    nxt = next_opening(slots, now, tz)
    text = served_text(slots) + "."
    if nxt is not None:
        text += " " + _("Next: %(when)s.") % {"when": when(nxt[1], now, tz)}
    return text, (nxt[1] if nxt else None)


def rule_summary(*, slots: list[MealSlot], max_per_slot: int, max_per_day: int | None) -> str:
    """Plain words for a plan/pass rule: 'Lunch only, 1 meal per day' / 'Any time, no daily limit'."""
    ordered = sorted(slots, key=lambda s: (s.sort_order, s.start_time))
    if not ordered:
        when_part = _("Any time")
    elif len(ordered) == 1:
        when_part = _("%(meal)s only") % {"meal": slot_label(ordered[0])}
    else:
        when_part = _(" and ").join(slot_label(s) for s in ordered)
    if max_per_day is not None:
        limit = ngettext("%(n)d meal per day", "%(n)d meals per day", max_per_day) % {"n": max_per_day}
    elif ordered:
        limit = ngettext("%(n)d meal per slot", "%(n)d meals per slot", max_per_slot) % {"n": max_per_slot}
        if len(ordered) == 1:  # one slot + per-slot cap == a daily cap in words
            limit = ngettext("%(n)d meal per day", "%(n)d meals per day", max_per_slot) % {"n": max_per_slot}
    else:
        limit = _("no daily limit")
    return f"{when_part}, {limit}"


def slots_for_ids(ids) -> list[MealSlot]:
    ids = list(ids or [])
    return list(MealSlot.objects.filter(id__in=ids)) if ids else []


def customer_rule_line(pass_, now: datetime, tz: ZoneInfo) -> str:
    """For the customer app: 'Lunch only · 1 meal a day · Next: today 12:00' ('' when the pass has no rules)."""
    slots = [s for s in slots_for_ids(getattr(pass_, "allowed_slot_ids", None)) if s.is_active]
    cap = getattr(pass_, "max_meals_per_day", None)
    if not slots and cap is None:
        return ""
    parts = []
    if slots:
        ordered = sorted(slots, key=lambda s: (s.sort_order, s.start_time))
        parts.append(
            _("%(meal)s only") % {"meal": slot_label(ordered[0])}
            if len(ordered) == 1
            else _(" and ").join(slot_label(s) for s in ordered)
        )
        per_day = cap if cap is not None else (pass_.max_meals_per_slot if len(ordered) == 1 else None)
    else:
        per_day = cap
    if per_day is not None:
        parts.append(ngettext("%(n)d meal a day", "%(n)d meals a day", per_day) % {"n": per_day})
    if slots:
        current = open_slot(slots, now, tz)
        if current is not None:
            _start, end = window(current.slot, current.service_date, tz, with_grace=False)
            parts.append(
                _("Now: %(meal)s until %(end)s") % {"meal": slot_label(current.slot), "end": hhmm(end.astimezone(tz))}
            )
        else:
            nxt = next_opening(slots, now, tz)
            if nxt is not None:
                parts.append(_("Next: %(when)s") % {"when": when(nxt[1], now, tz)})
    return " · ".join(parts)
