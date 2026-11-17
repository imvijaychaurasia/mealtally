# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError

from mealtally.common.errors import NotFound

from .models import Plan


def get_plan(public_id) -> Plan:
    try:
        return Plan.objects.get(public_id=public_id)
    except (Plan.DoesNotExist, ValueError, TypeError, DjangoValidationError) as exc:
        raise NotFound("Plan not found.") from exc


def list_plans(*, active_only: bool = True):
    qs = Plan.objects.order_by("price_minor", "id")
    return qs.filter(is_active=True) if active_only else qs


def create_plan(
    *,
    tenant_id: int,
    name: str,
    price_minor: int,
    meals_per_cycle: int = 30,
    validity_mode: str = Plan.ValidityMode.ROLLING_DAYS,
    validity_days: int = 30,
    max_meals_per_day: int | None = None,
    max_meals_per_slot: int = 1,
    allowed_slots=(),
) -> Plan:
    plan = Plan.objects.create(
        tenant_id=tenant_id,
        name=name,
        price_minor=price_minor,
        meals_per_cycle=meals_per_cycle,
        validity_mode=validity_mode,
        validity_days=validity_days,
        max_meals_per_day=max_meals_per_day,
        max_meals_per_slot=max_meals_per_slot,
    )
    if allowed_slots:
        set_allowed_slots(plan, allowed_slots)
    return plan


def set_allowed_slots(plan: Plan, slots) -> None:
    """Replace the plan's allowed meal slots (MealSlot rows or ids of this tenant's slots)."""
    from .models import MealSlot  # noqa: PLC0415
    from .models import PlanMealSlot  # noqa: PLC0415

    ids = {getattr(s, "id", s) for s in slots}
    valid = set(MealSlot.objects.filter(tenant_id=plan.tenant_id, id__in=ids).values_list("id", flat=True))
    if valid != ids:
        raise ValidationFailed("Unknown meal slot.", details={"field": "allowed_slots"})
    PlanMealSlot.objects.filter(plan=plan).exclude(slot_id__in=valid).delete()
    have = set(PlanMealSlot.objects.filter(plan=plan).values_list("slot_id", flat=True))
    PlanMealSlot.objects.bulk_create(
        [PlanMealSlot(tenant_id=plan.tenant_id, plan=plan, slot_id=i) for i in sorted(valid - have)]
    )


def rule_summary(plan: Plan) -> str:
    from . import meal_rules  # noqa: PLC0415

    return meal_rules.rule_summary(
        slots=list(plan.allowed_slots.all()),
        max_per_slot=plan.max_meals_per_slot,
        max_per_day=plan.max_meals_per_day,
    )


# --- plan management (OWNER / MANAGER). Editing never touches sold passes (they hold a snapshot). ----
from mealtally.accounts.policy import Action  # noqa: E402
from mealtally.accounts.policy import Actor  # noqa: E402
from mealtally.accounts.policy import require  # noqa: E402
from mealtally.audit import services as audit  # noqa: E402
from mealtally.common.errors import ValidationFailed  # noqa: E402

_FIELDS = (
    "name",
    "price_minor",
    "meals_per_cycle",
    "validity_mode",
    "validity_days",
    "max_meals_per_day",
    "max_meals_per_slot",
    "is_active",
)


def _validate(data: dict) -> dict:
    out = dict(data)
    if "name" in out and not str(out["name"]).strip():
        raise ValidationFailed("Plan name is required.", details={"field": "name"})
    for key in ("price_minor", "meals_per_cycle", "validity_days", "max_meals_per_slot"):
        if key in out and (not isinstance(out[key], int) or out[key] <= 0):
            raise ValidationFailed("Must be a positive whole number.", details={"field": key})
    if (
        "max_meals_per_day" in out
        and out["max_meals_per_day"] is not None
        and (not isinstance(out["max_meals_per_day"], int) or out["max_meals_per_day"] <= 0)
    ):
        raise ValidationFailed(
            "Daily cap must be positive (or blank for no cap).", details={"field": "max_meals_per_day"}
        )
    if "validity_mode" in out and out["validity_mode"] not in Plan.ValidityMode.values:
        raise ValidationFailed("Unknown validity mode.", details={"field": "validity_mode"})
    return out


def _snapshot(plan: Plan) -> dict:
    out = {k: getattr(plan, k) for k in _FIELDS}
    out["allowed_slots"] = sorted(plan.allowed_slots.values_list("name", flat=True)) if plan.pk else []
    return out


def save_plan(*, actor: Actor, plan: Plan | None = None, allowed_slots=None, **data) -> Plan:
    """Create/update a plan. ``allowed_slots`` (ids or rows; None = leave as is) sets the meal-time rule."""
    require(actor, Action.MANAGE_PLANS)
    data = _validate({k: v for k, v in data.items() if k in _FIELDS})
    before = None
    if plan is None:
        plan = Plan(tenant_id=actor.tenant_id)
    else:
        before = _snapshot(plan)
    for key, value in data.items():
        setattr(plan, key, value)
    plan.save()
    if allowed_slots is not None:
        set_allowed_slots(plan, allowed_slots)
    audit.record(
        action="plan.update" if before else "plan.create",
        tenant_id=actor.tenant_id,
        actor=actor.user,
        object_type="plan",
        object_public_id=plan.public_id,
        before=before,
        after=_snapshot(plan),
    )
    return plan


# --- meal slots (OWNER) ---------------------------------------------------------------------------------------------
_SLOT_FIELDS = ("name", "name_hi", "start_time", "end_time", "grace_minutes", "is_active", "sort_order")


def _slot_snapshot(slot) -> dict:
    out = {k: getattr(slot, k) for k in _SLOT_FIELDS}
    out["start_time"] = out["start_time"].strftime("%H:%M") if out["start_time"] else None
    out["end_time"] = out["end_time"].strftime("%H:%M") if out["end_time"] else None
    return out


def save_meal_slot(*, actor: Actor, slot=None, **data):
    """Create or edit a meal slot (OWNER). Times are tenant-local; end < start means the window crosses midnight."""
    from .models import MealSlot  # noqa: PLC0415

    require(actor, Action.MANAGE_SETTINGS)
    data = {k: v for k, v in data.items() if k in _SLOT_FIELDS}
    if "name" in data:
        data["name"] = str(data["name"]).strip()[:60]
        if not data["name"]:
            raise ValidationFailed("Give the meal time a name.", details={"field": "name"})
    if (data.get("start_time") is None and slot is None) or (data.get("end_time") is None and slot is None):
        raise ValidationFailed("Start and end times are required.", details={"field": "start_time"})
    grace = data.get("grace_minutes", getattr(slot, "grace_minutes", 0))
    if not isinstance(grace, int) or not 0 <= grace <= 120:  # noqa: PLR2004
        raise ValidationFailed("Grace must be 0 to 120 minutes.", details={"field": "grace_minutes"})
    before = _slot_snapshot(slot) if slot else None
    if slot is None:
        slot = MealSlot(tenant_id=actor.tenant_id)
    for key, value in data.items():
        setattr(slot, key, value)
    if slot.start_time == slot.end_time:
        raise ValidationFailed("Start and end can't be the same time.", details={"field": "end_time"})
    others = MealSlot.objects.filter(name__iexact=slot.name).exclude(pk=slot.pk)
    if others.exists():
        raise ValidationFailed("There is already a meal time with this name.", details={"field": "name"})
    slot.save()
    audit.record(
        action="meal_slot.update" if before else "meal_slot.create",
        tenant_id=actor.tenant_id,
        actor=actor.user,
        object_type="meal_slot",
        object_public_id=slot.public_id,
        before=before,
        after=_slot_snapshot(slot),
    )
    return slot
