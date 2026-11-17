"""Pass lifecycle: create / queue / activate / expire / suspend / resume / cancel.

Public entry points are called by ``billing`` (create / cancel-for-void), the
Celery job (``run_due_transitions``) and the API (suspend / resume / cancel).
Credit movements are *never* written here: they go through ``ledger.services``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from datetime import time
from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db import transaction
from django.utils import timezone

from mealtally.accounts.policy import Action
from mealtally.accounts.policy import Actor
from mealtally.accounts.policy import require
from mealtally.audit import services as audit
from mealtally.common.errors import NoActivePass
from mealtally.common.errors import NotFound
from mealtally.common.errors import QueueFull
from mealtally.common.errors import StateConflict
from mealtally.common.errors import ValidationFailed
from mealtally.common.utils import end_of_local_day
from mealtally.common.utils import first_of_next_month
from mealtally.common.utils import last_of_month
from mealtally.common.utils import local_date
from mealtally.common.utils import start_of_local_day
from mealtally.common.utils import tz_of
from mealtally.plans.models import Plan

from .models import Pass

logger = logging.getLogger(__name__)

LIVE_STATUSES = (Pass.Status.ACTIVE, Pass.Status.SUSPENDED)


# --- validity maths ------------------------------------------------------------------------------


def compute_ends_at(*, validity_mode: str, validity_days: int, starts_at: datetime, tz_name: str) -> datetime:
    """Last instant of the pass, in UTC (ADR 0008).

    ROLLING_DAYS: end of the tenant-local day ``validity_days - 1`` after the start date (purchase day = day 1).
    CALENDAR_MONTH: end of the tenant-local calendar month containing ``starts_at``.
    """
    start_day = local_date(starts_at, tz_name)
    if validity_mode == Plan.ValidityMode.CALENDAR_MONTH:
        end_day = last_of_month(start_day)
    else:
        end_day = start_day + timedelta(days=validity_days - 1)
    return end_of_local_day(end_day, tz_name)


def compute_queued_start(*, validity_mode: str, prior_ends_at: datetime, tz_name: str) -> datetime:
    """A queued pass starts right after the one before it (+1 µs); calendar plans snap to the 1st."""
    candidate = prior_ends_at + timedelta(microseconds=1)
    if validity_mode == Plan.ValidityMode.CALENDAR_MONTH:
        local = candidate.astimezone(tz_of(tz_name))
        if not (local.day == 1 and local.time() == time(0, 0)):
            candidate = start_of_local_day(first_of_next_month(local.date()), tz_name)
    return candidate


# --- lookups -------------------------------------------------------------------------------------


def get_pass(public_id, *, lock: bool = False) -> Pass:
    qs = Pass.objects.select_related("customer", "plan")
    if lock:
        qs = qs.select_for_update(of=("self",))
    try:
        return qs.get(public_id=public_id)
    except (Pass.DoesNotExist, ValueError, TypeError, DjangoValidationError) as exc:
        raise NotFound("Pass not found.") from exc


def get_pass_for_payment(payment, *, lock: bool = False) -> Pass:
    qs = Pass.objects.select_related("customer")
    if lock:
        qs = qs.select_for_update(of=("self",))
    try:
        return qs.get(payment_id=payment.pk)
    except Pass.DoesNotExist as exc:
        raise NotFound("Pass not found for payment.") from exc


def active_pass_for(customer_id: int) -> Pass | None:
    return Pass.objects.filter(customer_id=customer_id, status=Pass.Status.ACTIVE).first()


def lock_active_pass(customer_id: int) -> Pass | None:
    """``SELECT ... FOR UPDATE`` on the customer's ACTIVE pass (the redeem hot path)."""
    return Pass.objects.select_for_update().filter(customer_id=customer_id, status=Pass.Status.ACTIVE).first()


def queued_passes_for(customer_id: int):
    return Pass.objects.filter(customer_id=customer_id, status=Pass.Status.QUEUED).order_by("starts_at")


def passes_for_customer(customer_id: int):
    return Pass.objects.filter(customer_id=customer_id).order_by("-starts_at", "-id")


def apply_balance(pass_: Pass, new_balance: int) -> None:
    """Called by ledger after it inserted an entry: keep the cached balance in step."""
    pass_.meals_remaining = new_balance
    pass_.save(update_fields=["meals_remaining", "updated_at"])


# --- transitions ---------------------------------------------------------------------------------


def _snapshot(pass_: Pass) -> dict:
    return {"status": pass_.status, "meals_remaining": pass_.meals_remaining}


def activate(pass_: Pass, *, now: datetime | None = None, actor=None) -> Pass:
    """QUEUED -> ACTIVE and issue its credits. Caller holds the pass/customer lock."""
    from mealtally.ledger import services as ledger  # noqa: PLC0415

    before = _snapshot(pass_)
    pass_.status = Pass.Status.ACTIVE
    pass_.save(update_fields=["status", "updated_at"])
    ledger.issue_pass_credits(pass_=pass_, now=now)
    audit.record(
        action="pass.activate",
        tenant_id=pass_.tenant_id,
        actor=actor,
        object_type="pass",
        object_public_id=pass_.public_id,
        before=before,
        after=_snapshot(pass_),
    )
    return pass_


def expire(pass_: Pass, *, now: datetime | None = None) -> Pass:
    """ACTIVE/SUSPENDED -> EXPIRED: zero the unused credits (they are forfeited)."""
    from mealtally.ledger import services as ledger  # noqa: PLC0415

    before = _snapshot(pass_)
    ledger.expire_pass_credits(pass_=pass_, now=now)
    pass_.status = Pass.Status.EXPIRED
    pass_.save(update_fields=["status", "updated_at"])
    audit.record(
        action="pass.expire",
        tenant_id=pass_.tenant_id,
        actor=None,
        object_type="pass",
        object_public_id=pass_.public_id,
        before=before,
        after=_snapshot(pass_),
    )
    return pass_


def settle_customer(customer_id: int, *, now: datetime) -> None:
    """Bring ONE customer's passes up to date (used inside record_payment; caller holds the customer lock)."""
    for p in Pass.objects.select_for_update().filter(
        customer_id=customer_id, status__in=LIVE_STATUSES, ends_at__lte=now
    ):
        expire(p, now=now)
    if not Pass.objects.filter(customer_id=customer_id, status=Pass.Status.ACTIVE).exists():
        due = (
            Pass.objects.select_for_update()
            .filter(customer_id=customer_id, status=Pass.Status.QUEUED, starts_at__lte=now)
            .order_by("starts_at")
            .first()
        )
        if due is not None:
            activate(due, now=now)


def create_pass_for_payment(*, actor: Actor, tenant, settings_row, payment, customer, plan, now: datetime) -> Pass:
    """Step 3 of record_payment: ACTIVE now, or QUEUED behind the current pass. Caller locked the customer."""
    from mealtally.ledger import services as ledger  # noqa: PLC0415

    settle_customer(customer.id, now=now)
    active = active_pass_for(customer.id)
    snapshot = {
        "plan_name": plan.name,
        "price_minor": plan.price_minor,
        "meals_total": plan.meals_per_cycle,
        "validity_mode": plan.validity_mode,
        "validity_days": plan.validity_days,
        "max_meals_per_day": plan.max_meals_per_day,
        # D03.9: which meal slots, snapshotted (the slots' times stay live).
        "allowed_slot_ids": sorted(plan.allowed_slots.values_list("id", flat=True)),
        "max_meals_per_slot": plan.max_meals_per_slot,
    }
    if active is None:
        starts_at = now
        status = Pass.Status.ACTIVE
    else:
        queued = list(queued_passes_for(customer.id))
        if len(queued) >= settings_row.max_queued_passes:
            raise QueueFull(
                "This customer already has the maximum number of queued passes.",
                details={"max_queued_passes": settings_row.max_queued_passes},
            )
        prior_end = max([active.ends_at, *[q.ends_at for q in queued]])
        starts_at = compute_queued_start(
            validity_mode=plan.validity_mode, prior_ends_at=prior_end, tz_name=tenant.timezone
        )
        status = Pass.Status.QUEUED
    ends_at = compute_ends_at(
        validity_mode=plan.validity_mode, validity_days=plan.validity_days, starts_at=starts_at, tz_name=tenant.timezone
    )
    pass_ = Pass.objects.create(
        tenant_id=tenant.id,
        customer=customer,
        payment=payment,
        plan=plan,
        status=status,
        starts_at=starts_at,
        ends_at=ends_at,
        meals_remaining=0,
        **snapshot,
    )
    if status == Pass.Status.ACTIVE:
        ledger.issue_pass_credits(pass_=pass_, now=now, operator=actor.user)
    return pass_


def _require_reason(reason: str) -> str:
    reason = (reason or "").strip()
    if not reason:
        raise ValidationFailed("A reason is required.", details={"field": "reason"})
    return reason


def suspend_pass(*, actor: Actor, pass_public_id, reason: str, now: datetime | None = None) -> Pass:
    require(actor, Action.SUSPEND_CANCEL_PASS)
    reason = _require_reason(reason)
    with transaction.atomic():
        pass_ = get_pass(pass_public_id, lock=True)
        if pass_.status != Pass.Status.ACTIVE:
            raise StateConflict("Only an ACTIVE pass can be suspended.", code="PASS_STATE_INVALID")
        before = _snapshot(pass_)
        pass_.status = Pass.Status.SUSPENDED
        pass_.save(update_fields=["status", "updated_at"])
        audit.record(
            action="pass.suspend",
            tenant_id=pass_.tenant_id,
            actor=actor.user,
            object_type="pass",
            object_public_id=pass_.public_id,
            before=before,
            after={**_snapshot(pass_), "reason": reason},
        )
    return pass_


def resume_pass(*, actor: Actor, pass_public_id, reason: str, now: datetime | None = None) -> Pass:
    """SUSPENDED -> ACTIVE. ``ends_at`` is NOT extended (no pause feature in v1)."""
    require(actor, Action.SUSPEND_CANCEL_PASS)
    reason = _require_reason(reason)
    now = now or timezone.now()
    with transaction.atomic():
        pass_ = get_pass(pass_public_id, lock=True)
        if pass_.status != Pass.Status.SUSPENDED:
            raise StateConflict("Only a SUSPENDED pass can be resumed.", code="PASS_STATE_INVALID")
        if pass_.ends_at <= now:
            raise StateConflict("The pass has already ended.", code="PASS_STATE_INVALID")
        if Pass.objects.filter(customer_id=pass_.customer_id, status=Pass.Status.ACTIVE).exists():
            raise StateConflict("The customer already has an ACTIVE pass.", code="PASS_STATE_INVALID")
        before = _snapshot(pass_)
        pass_.status = Pass.Status.ACTIVE
        pass_.save(update_fields=["status", "updated_at"])
        audit.record(
            action="pass.resume",
            tenant_id=pass_.tenant_id,
            actor=actor.user,
            object_type="pass",
            object_public_id=pass_.public_id,
            before=before,
            after={**_snapshot(pass_), "reason": reason},
        )
    return pass_


def promote_next(customer_id: int, *, now: datetime | None = None, actor=None) -> Pass | None:
    """When a live pass ends early (cancel / void) the earliest QUEUED pass starts immediately (ADR 0011).

    ``starts_at`` becomes ``now``; ``ends_at`` is recomputed for its validity mode; later queued passes are
    re-chained behind it. Runs in the caller's transaction.
    """
    from mealtally.tenancy.models import Tenant  # noqa: PLC0415

    now = now or timezone.now()
    queued = list(queued_passes_for(customer_id).select_for_update())
    if not queued or Pass.objects.filter(customer_id=customer_id, status=Pass.Status.ACTIVE).exists():
        return None
    tz_name = Tenant.objects.get(pk=queued[0].tenant_id).timezone
    first, rest = queued[0], queued[1:]
    first.starts_at = now
    first.ends_at = compute_ends_at(
        validity_mode=first.validity_mode, validity_days=first.validity_days, starts_at=now, tz_name=tz_name
    )
    first.save(update_fields=["starts_at", "ends_at", "updated_at"])
    activate(first, now=now, actor=actor)
    prior_end = first.ends_at
    for nxt in rest:
        nxt.starts_at = compute_queued_start(validity_mode=nxt.validity_mode, prior_ends_at=prior_end, tz_name=tz_name)
        nxt.ends_at = compute_ends_at(
            validity_mode=nxt.validity_mode, validity_days=nxt.validity_days, starts_at=nxt.starts_at, tz_name=tz_name
        )
        nxt.save(update_fields=["starts_at", "ends_at", "updated_at"])
        prior_end = nxt.ends_at
    return first


def _cancel(pass_: Pass, *, actor_user, reason: str, action: str, now: datetime | None) -> Pass:
    from mealtally.ledger import services as ledger  # noqa: PLC0415

    before = _snapshot(pass_)
    was_live = pass_.status in LIVE_STATUSES
    if was_live:
        ledger.zero_out_pass(pass_=pass_, reason=reason, operator=actor_user, now=now)
    pass_.status = Pass.Status.CANCELLED
    pass_.save(update_fields=["status", "updated_at"])
    audit.record(
        action=action,
        tenant_id=pass_.tenant_id,
        actor=actor_user,
        object_type="pass",
        object_public_id=pass_.public_id,
        before=before,
        after={**_snapshot(pass_), "reason": reason},
    )
    if was_live:
        promote_next(pass_.customer_id, now=now, actor=actor_user)
    return pass_


def cancel_pass(*, actor: Actor, pass_public_id, reason: str, now: datetime | None = None) -> Pass:
    require(actor, Action.SUSPEND_CANCEL_PASS)
    reason = _require_reason(reason)
    with transaction.atomic():
        pass_ = get_pass(pass_public_id, lock=True)
        if pass_.status not in (Pass.Status.ACTIVE, Pass.Status.SUSPENDED, Pass.Status.QUEUED):
            raise StateConflict("This pass can no longer be cancelled.", code="PASS_STATE_INVALID")
        return _cancel(pass_, actor_user=actor.user, reason=reason, action="pass.cancel", now=now)


def cancel_for_void(*, pass_: Pass, actor: Actor, reason: str, now: datetime | None = None) -> Pass:
    """Used by billing.void_payment. Caller holds the pass lock and verified there are no redemptions."""
    return _cancel(pass_, actor_user=actor.user, reason=reason, action="pass.cancel_for_void", now=now)


# --- the periodic job (per tenant, inside that tenant's context) ----------------------------------


def run_due_transitions(*, now: datetime | None = None) -> dict[str, int]:
    """Expire ended passes, then activate due queued ones. Idempotent; safe to run concurrently.

    Rows are taken with ``FOR UPDATE SKIP LOCKED`` so two workers never fight over a pass and a
    pass a redeemer holds is simply picked up on the next run.
    """
    from mealtally.customers import services as customers  # noqa: PLC0415

    now = now or timezone.now()
    counts = {"expired": 0, "activated": 0}
    with transaction.atomic():
        ending = list(
            Pass.objects.select_for_update(skip_locked=True, of=("self",))
            .filter(status__in=LIVE_STATUSES, ends_at__lte=now)
            .order_by("id")
        )
        for pass_ in ending:
            expire(pass_, now=now)
            counts["expired"] += 1
        due = list(
            Pass.objects.select_for_update(skip_locked=True, of=("self",))
            .filter(status=Pass.Status.QUEUED, starts_at__lte=now)
            .order_by("starts_at", "id")
        )
    for pass_ in due:
        try:
            with transaction.atomic():
                customers.get_customer(pass_.customer.public_id, lock=True)  # serialise with record_payment
                fresh = Pass.objects.select_for_update().get(pk=pass_.pk)
                if fresh.status != Pass.Status.QUEUED:
                    continue
                if Pass.objects.filter(customer_id=fresh.customer_id, status=Pass.Status.ACTIVE).exists():
                    continue
                activate(fresh, now=now)
                counts["activated"] += 1
        except IntegrityError:  # lost a race for the one-ACTIVE-pass slot: next run retries
            logger.warning("pass activation lost a race", extra={"pass": str(pass_.public_id)})
    return counts


def require_active_pass(customer_id: int) -> Pass:
    pass_ = active_pass_for(customer_id)
    if pass_ is None:
        raise NoActivePass("The customer has no active pass.")
    return pass_


def preview_purchase(*, customer_id: int | None, plan, tenant, settings_row, now: datetime | None = None) -> dict:
    """What would buying ``plan`` do? Pure read: used by the sell-pass preview (no writes)."""
    now = now or timezone.now()
    live = []
    if customer_id is not None:
        live = [
            p
            for p in Pass.objects.filter(customer_id=customer_id, status__in=[Pass.Status.ACTIVE, Pass.Status.QUEUED])
            if p.ends_at > now
        ]
    active = next((p for p in live if p.status == Pass.Status.ACTIVE), None)
    queued = [p for p in live if p.status == Pass.Status.QUEUED]
    result = {
        "status": Pass.Status.ACTIVE,
        "gap": None,
        "queue_full": False,
        "no_proration": plan.validity_mode == Plan.ValidityMode.CALENDAR_MONTH,
    }
    if active is None:
        starts = now
    else:
        result["status"] = Pass.Status.QUEUED
        result["queue_full"] = len(queued) >= settings_row.max_queued_passes
        prior_end = max([active.ends_at, *[q.ends_at for q in queued]])
        starts = compute_queued_start(
            validity_mode=plan.validity_mode, prior_ends_at=prior_end, tz_name=tenant.timezone
        )
        if starts > prior_end + timedelta(microseconds=1):
            tz = tz_of(tenant.timezone)
            gap_from = (prior_end + timedelta(microseconds=1)).astimezone(tz).date()
            result["gap"] = {"from": gap_from, "to": starts.astimezone(tz).date() - timedelta(days=1)}
    ends = compute_ends_at(
        validity_mode=plan.validity_mode, validity_days=plan.validity_days, starts_at=starts, tz_name=tenant.timezone
    )
    result.update(starts_at=starts.astimezone(tz_of(tenant.timezone)), ends_at=ends.astimezone(tz_of(tenant.timezone)))
    return result
