# SPDX-License-Identifier: AGPL-3.0-only
"""D03.9 §B: meal-time and per-day redemption rules. Every case runs on a frozen clock (time-machine)."""

from __future__ import annotations

import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from datetime import time
from zoneinfo import ZoneInfo

import pytest
import time_machine
from django.db import connection

from mealtally.audit.models import AuditEvent
from mealtally.common.errors import DailyCapReached
from mealtally.common.errors import DomainError
from mealtally.common.errors import MealSlotCapReached
from mealtally.common.errors import MealSlotClosed
from mealtally.common.errors import NotAllowed
from mealtally.ledger import services as ledger
from mealtally.ledger.models import MealLedgerEntry
from mealtally.plans import meal_rules
from mealtally.plans import services as plans
from mealtally.plans.models import MealSlot
from mealtally.tenancy.context import tenant_context
from mealtally.testing import World
from mealtally.testing import buy

pytestmark = pytest.mark.django_db
IST = ZoneInfo("Asia/Kolkata")
SRC = MealLedgerEntry.Source
# Monday 16 Nov 2026 (the clock is frozen relative to this day unless a test says otherwise)
DAY = (2026, 11, 16)


def at(hh: int, mm: int = 0, *, day=DAY, tz=IST) -> datetime:
    return datetime(*day, hh, mm, tzinfo=tz)


def rules_world(
    *,
    slots=("Lunch",),
    per_slot=1,
    per_day=None,
    tz="Asia/Kolkata",
    bought_at=None,
    edit=None,
    extra_slot=None,
) -> World:
    """A tenant whose plan has the given meal-time rule, and a customer who bought it (snapshot taken at sale)."""
    zone = ZoneInfo(tz)
    with time_machine.travel(bought_at or datetime(2026, 11, 15, 9, 0, tzinfo=zone), tick=False):
        w = World(buy_pass=False, timezone_name=tz)
        with w.ctx():
            by_name = {s.name: s for s in MealSlot.objects.all()}
            if extra_slot:
                by_name[extra_slot["name"]] = MealSlot.objects.create(tenant_id=w.tenant.id, **extra_slot)
            for name, changes in (edit or {}).items():
                MealSlot.objects.filter(pk=by_name[name].pk).update(**changes)
            plans.set_allowed_slots(w.plan, [by_name[n] for n in slots])
            w.plan.max_meals_per_slot = per_slot
            w.plan.max_meals_per_day = per_day
            w.plan.save()
        w.pass_ = buy(w.tenant, w.owner, w.customer, w.plan).pass_
        w.slots = by_name
    return w


def serve(w, *, actor=None, source=SRC.STAFF_SEARCH, override="", confirm=True):
    """Like a view: the refusal is caught INSIDE the request transaction (so the ``redeem.denied`` row commits)."""
    with w.ctx():
        try:
            return ledger.redeem(
                actor=actor or w.staff,
                customer=w.customer,
                idempotency_key=str(uuid.uuid4()),
                source=source,
                confirm_additional=confirm,
                override_reason=override,
            )
        except DomainError as exc:
            refused = exc
    raise refused


# --- the defaults ---------------------------------------------------------------------------------------------------
def test_every_tenant_gets_breakfast_lunch_dinner_and_the_pass_snapshots_the_rule():
    w = rules_world()
    with w.ctx():
        slots = list(MealSlot.objects.order_by("sort_order").values_list("name", "start_time", "end_time"))
        assert slots == [
            ("Breakfast", time(7, 0), time(10, 30)),
            ("Lunch", time(12, 0), time(15, 0)),
            ("Dinner", time(19, 0), time(22, 30)),
        ]
        assert w.pass_.allowed_slot_ids == [w.slots["Lunch"].id]
        assert w.pass_.max_meals_per_slot == 1
        assert plans.rule_summary(w.plan) == "Lunch only, 1 meal per day"


def test_a_plan_without_rules_behaves_exactly_as_before():
    with time_machine.travel(datetime(2026, 11, 15, 9, 0, tzinfo=IST), tick=False):
        w = World()
    with time_machine.travel(at(3, 0), tick=False):  # 03:00, no slot open
        res = serve(w)
    assert res.entry.meal_slot_id is None and res.meals_remaining == 29
    with time_machine.travel(at(3, 1), tick=False):
        assert serve(w).meals_remaining == 28  # no slot cap, no day cap
    with w.ctx():
        assert plans.rule_summary(w.plan) == "Any time, no daily limit"


# --- the window ------------------------------------------------------------------------------------------------------
def test_inside_the_window_serves_and_records_the_slot():
    w = rules_world()
    with time_machine.travel(at(12, 41), tick=False):
        res = serve(w)
    assert res.entry.meal_slot_id == w.slots["Lunch"].id
    assert res.meal_date.isoformat() == "2026-11-16"


def test_outside_the_window_is_blocked_with_the_serving_hours_and_the_next_opening():
    w = rules_world()
    with time_machine.travel(at(10, 0), tick=False), pytest.raises(MealSlotClosed) as exc:
        serve(w)
    assert exc.value.message == "Lunch is served 12:00–15:00. Next: today 12:00."
    with time_machine.travel(at(16, 0), tick=False), pytest.raises(MealSlotClosed) as exc:
        serve(w)
    assert exc.value.message == "Lunch is served 12:00–15:00. Next: tomorrow 12:00."
    assert exc.value.details["next_at"].startswith("2026-11-17T12:00")


def test_next_opening_names_the_weekday_when_it_is_further_away():
    slot = MealSlot(name="Lunch", start_time=time(12, 0), end_time=time(15, 0), sort_order=1, id=1)
    now = at(16, 0)  # Monday
    nxt = meal_rules.next_opening([slot], now, IST)
    assert meal_rules.when(nxt[1], now, IST) == "tomorrow 12:00"
    assert meal_rules.when(at(12, 0, day=(2026, 11, 19)), now, IST) == "Thursday 12:00"


@pytest.mark.parametrize(
    ("hh", "mm", "allowed"),
    [(11, 44, False), (11, 45, True), (12, 0, True), (15, 15, True), (15, 16, False)],
)
def test_grace_minutes_widen_the_window_on_both_sides(hh, mm, allowed):
    w = rules_world(edit={"Lunch": {"grace_minutes": 15}})
    with time_machine.travel(at(hh, mm), tick=False):
        if allowed:
            assert serve(w).entry.meal_slot_id == w.slots["Lunch"].id
        else:
            with pytest.raises(MealSlotClosed):
                serve(w)


# --- caps ------------------------------------------------------------------------------------------------------------
def test_the_slot_cap_blocks_a_second_lunch_and_names_when_and_who():
    w = rules_world()
    with time_machine.travel(at(12, 41), tick=False):
        first = serve(w)
    with time_machine.travel(at(13, 30), tick=False), pytest.raises(MealSlotCapReached) as exc:
        serve(w)
    who = w.staff.user.name or w.staff.user.email
    assert exc.value.message == f"Already had lunch today (12:41, {who})."
    # a reversal gives the slot back
    with time_machine.travel(at(13, 31), tick=False), w.ctx():
        ledger.reverse_redemption(actor=w.manager, entry_public_id=first.entry.public_id, reason="wrong customer")
    with time_machine.travel(at(13, 32), tick=False):
        assert serve(w).entry.meal_slot_id == w.slots["Lunch"].id
    # the next day the slot is open again
    with time_machine.travel(at(12, 5, day=(2026, 11, 17)), tick=False):
        assert serve(w).meal_date.isoformat() == "2026-11-17"


def test_the_day_cap_blocks_dinner_after_lunch():
    w = rules_world(slots=("Lunch", "Dinner"), per_day=1)
    with time_machine.travel(at(12, 41), tick=False):
        serve(w)
    with time_machine.travel(at(19, 30), tick=False), pytest.raises(DailyCapReached) as exc:
        serve(w)
    assert re.fullmatch(r"Already had 1 meal today \(12:41, .+\)\.", exc.value.message)
    with w.ctx():
        assert plans.rule_summary(w.plan) == "Lunch and Dinner, 1 meal per day"


def test_one_per_slot_allows_lunch_and_dinner_but_not_two_dinners():
    w = rules_world(slots=("Lunch", "Dinner"), per_slot=1)
    with time_machine.travel(at(12, 41), tick=False):
        serve(w)
    with time_machine.travel(at(19, 30), tick=False):
        assert serve(w).entry.meal_slot_id == w.slots["Dinner"].id
    with time_machine.travel(at(20, 0), tick=False), pytest.raises(MealSlotCapReached):
        serve(w)


# --- override --------------------------------------------------------------------------------------------------------
def test_owner_and_manager_can_override_with_a_reason_and_it_is_audited():
    w = rules_world()
    with time_machine.travel(at(12, 41), tick=False):
        serve(w)
    with time_machine.travel(at(13, 0), tick=False):
        res = serve(w, actor=w.manager, override="Guest of the owner, approved")
    assert res.entry.reason == "Guest of the owner, approved" and res.entry.meal_slot_id == w.slots["Lunch"].id
    with time_machine.travel(at(17, 0), tick=False):  # outside every slot: the override still serves
        res = serve(w, actor=w.owner, override="Late shift")
    assert res.entry.meal_slot_id is None
    with w.ctx():
        events = list(AuditEvent.objects.filter(action="redeem.override").order_by("id"))
    assert [e.before["code"] for e in events] == ["MEAL_SLOT_CAP_REACHED", "MEAL_SLOT_CLOSED"]
    assert events[0].after["reason"] == "Guest of the owner, approved"


def test_a_counter_cannot_override():
    w = rules_world()
    with time_machine.travel(at(10, 0), tick=False), pytest.raises(NotAllowed):
        serve(w, actor=w.staff, override="please")
    with time_machine.travel(at(10, 0), tick=False), pytest.raises(MealSlotClosed):
        serve(w, actor=w.staff)  # without a reason: the normal block, which the screen turns into "Ask a manager"


def test_refused_attempts_are_audited_with_code_operator_and_channel():
    w = rules_world()
    with time_machine.travel(at(10, 0), tick=False):
        for source in (SRC.QR_SCAN, SRC.STAFF_SEARCH):
            with pytest.raises(MealSlotClosed):
                serve(w, source=source)
    with w.ctx():
        denied = list(AuditEvent.objects.filter(action="redeem.denied").order_by("id"))
    assert [(e.after["code"], e.after["channel"]) for e in denied] == [
        ("MEAL_SLOT_CLOSED", "QR_SCAN"),
        ("MEAL_SLOT_CLOSED", "STAFF_SEARCH"),
    ]
    assert all(e.actor_id == w.staff.user.pk and e.object_public_id == w.customer.public_id for e in denied)


def test_qr_and_search_give_the_same_results():
    results = {}
    for source in (SRC.QR_SCAN, SRC.STAFF_SEARCH):
        w = rules_world()
        out = []
        for hh, mm in ((10, 0), (12, 41), (13, 0)):
            with time_machine.travel(at(hh, mm), tick=False):
                try:
                    serve(w, source=source)
                    out.append("OK")
                except DomainError as exc:
                    out.append((exc.code, re.sub(r"\(.*\)", "()", exc.message)))
        results[source] = out
    assert results[SRC.QR_SCAN] == results[SRC.STAFF_SEARCH]
    assert results[SRC.QR_SCAN][1] == "OK"


# --- midnight and timezones ------------------------------------------------------------------------------------------
def test_a_window_that_crosses_midnight_belongs_to_the_day_it_opened():
    late = {"name": "Late night", "start_time": time(22, 0), "end_time": time(1, 0), "sort_order": 4}
    w = rules_world(slots=("Late night",), extra_slot=late)
    with time_machine.travel(at(0, 30, day=(2026, 11, 17)), tick=False):
        res = serve(w)
    assert res.meal_date.isoformat() == "2026-11-16"  # served at 00:30 Tuesday, Monday's late-night meal
    with time_machine.travel(at(0, 45, day=(2026, 11, 17)), tick=False), pytest.raises(MealSlotCapReached):
        serve(w)
    with time_machine.travel(at(1, 30, day=(2026, 11, 17)), tick=False), pytest.raises(MealSlotClosed) as exc:
        serve(w)
    assert exc.value.message == "Late night is served 22:00–01:00. Next: today 22:00."
    with time_machine.travel(at(22, 10, day=(2026, 11, 17)), tick=False):
        assert serve(w).meal_date.isoformat() == "2026-11-17"


def test_the_tenant_timezone_decides_the_slot_not_the_server_timezone():
    ny = ZoneInfo("America/New_York")
    w = rules_world(tz="America/New_York")
    with time_machine.travel(at(12, 30), tick=False), pytest.raises(MealSlotClosed):
        serve(w)  # 12:30 in India is 02:00 in New York
    with time_machine.travel(datetime(*DAY, 12, 30, tzinfo=ny), tick=False):
        res = serve(w)  # 12:30 in New York (23:00 in India)
    assert res.entry.meal_slot_id == w.slots["Lunch"].id
    assert res.meal_date.isoformat() == "2026-11-16"


def test_redeem_status_previews_the_same_rule_for_the_counter_card():
    w = rules_world()
    with time_machine.travel(at(10, 0), tick=False), w.ctx():
        status = ledger.redeem_status(customer=w.customer)
    assert status["state"] == "blocked" and status["code"] == "MEAL_SLOT_CLOSED" and status["rule"] is True
    assert status["message"].startswith("Lunch is served 12:00–15:00")
    with time_machine.travel(at(12, 10), tick=False), w.ctx():
        assert ledger.redeem_status(customer=w.customer)["state"] == "ok"


# --- concurrency -----------------------------------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
def test_two_counters_cannot_beat_the_slot_cap():
    w = rules_world()
    from mealtally.accounts.models import Role  # noqa: PLC0415
    from mealtally.testing import make_actor  # noqa: PLC0415

    counter2 = make_actor(w.tenant, Role.STAFF)  # a second counter at the same restaurant
    n = 10
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        try:
            with tenant_context(w.tenant.id):
                ledger.redeem(
                    actor=w.staff if i % 2 else counter2,
                    customer=w.customer,
                    idempotency_key=str(uuid.uuid4()),
                    source=SRC.QR_SCAN if i % 2 else SRC.STAFF_SEARCH,
                    confirm_additional=True,
                )
            return "ok"
        except DomainError as exc:
            return exc.code
        finally:
            connection.close()

    with time_machine.travel(at(12, 41), tick=False), ThreadPoolExecutor(max_workers=n) as pool:
        outcomes = list(pool.map(worker, range(n)))
    assert outcomes.count("ok") == 1, outcomes
    assert set(outcomes) - {"ok"} == {"MEAL_SLOT_CAP_REACHED"}
    with tenant_context(w.tenant.id):
        assert MealLedgerEntry.objects.filter(entry_type="REDEEM").count() == 1
        assert ledger.find_mismatches() == []
