"""The meal ledger: the ONLY writer of ``MealLedgerEntry`` and of pass balances' meaning.

Every credit movement is one append-only row; ``pass.meals_remaining`` is a cache kept
equal to ``SUM(quantity)`` (verified nightly by :func:`find_mismatches`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import F
from django.db.models import Q
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from mealtally.accounts.models import Role
from mealtally.accounts.policy import Action
from mealtally.accounts.policy import Actor
from mealtally.accounts.policy import require
from mealtally.audit import services as audit
from mealtally.common.errors import AlreadyReversed
from mealtally.common.errors import CooldownConfirmRequired
from mealtally.common.errors import DailyCapReached
from mealtally.common.errors import DomainError
from mealtally.common.errors import IdempotencyKeyReused
from mealtally.common.errors import MealSlotCapReached
from mealtally.common.errors import MealSlotClosed
from mealtally.common.errors import NoActivePass
from mealtally.common.errors import NoCredits
from mealtally.common.errors import NotAllowed
from mealtally.common.errors import NotFound
from mealtally.common.errors import PassNotValidNow
from mealtally.common.errors import StateConflict
from mealtally.common.errors import ValidationFailed
from mealtally.common.utils import local_date
from mealtally.passes import services as passes
from mealtally.passes.models import Pass
from mealtally.plans import meal_rules
from mealtally.plans.models import MealSlot
from mealtally.tenancy.models import Tenant

from .models import MealLedgerEntry

logger = logging.getLogger(__name__)
E = MealLedgerEntry.EntryType
S = MealLedgerEntry.Source


@dataclass(frozen=True)
class RedeemResult:
    entry: MealLedgerEntry
    customer: object
    pass_: Pass
    meals_remaining: int
    meal_date: date
    replayed: bool


# --- internals -----------------------------------------------------------------------------------


def _clean_key(key) -> str:
    key = str(key or "").strip()
    if not key or len(key) > 200:  # noqa: PLR2004
        raise ValidationFailed("idempotency_key is required (UUID recommended).", details={"field": "idempotency_key"})
    return key


def _tenant(tenant_id: int) -> Tenant:
    return Tenant.objects.get(pk=tenant_id)


def _find_by_key(key: str) -> MealLedgerEntry | None:
    return MealLedgerEntry.objects.select_related("pass_ref", "customer").filter(idempotency_key=key).first()


def _post_entry(
    *,
    tenant: Tenant,
    pass_: Pass,
    entry_type: str,
    quantity: int,
    source: str,
    idempotency_key: str,
    operator=None,
    reason: str = "",
    reverses: MealLedgerEntry | None = None,
    device_ref: str | None = None,
    meal_date: date | None = None,
    now: datetime | None = None,
    meal_slot: MealSlot | None = None,
) -> MealLedgerEntry:
    """Insert one entry and move the cached balance. ``pass_`` must be row-locked and fresh."""
    now = now or timezone.now()
    new_balance = pass_.meals_remaining + quantity
    if new_balance < 0:
        raise ValidationFailed("This would make the balance negative.", code="INSUFFICIENT_BALANCE")
    entry = MealLedgerEntry.objects.create(
        tenant_id=pass_.tenant_id,
        pass_ref=pass_,
        customer_id=pass_.customer_id,
        entry_type=entry_type,
        quantity=quantity,
        balance_after=new_balance,
        meal_date=meal_date or local_date(now, tenant.timezone),
        occurred_at=now,
        source=source,
        operator=operator if (operator is not None and getattr(operator, "pk", None)) else None,
        device_ref=device_ref,
        reason=reason,
        reverses=reverses,
        idempotency_key=idempotency_key,
        meal_slot=meal_slot,
    )
    passes.apply_balance(pass_, new_balance)
    return entry


def _result(entry: MealLedgerEntry, *, replayed: bool) -> RedeemResult:
    return RedeemResult(
        entry=entry,
        customer=entry.customer,
        pass_=entry.pass_ref,
        meals_remaining=entry.balance_after,
        meal_date=entry.meal_date,
        replayed=replayed,
    )


def _net_redemptions(pass_: Pass, day: date) -> int:
    base = MealLedgerEntry.objects.filter(pass_ref=pass_, meal_date=day)
    return base.filter(entry_type=E.REDEEM).count() - base.filter(entry_type=E.REVERSAL).count()


# --- system postings (called by passes) ---------------------------------------------------------


def issue_pass_credits(*, pass_: Pass, now: datetime | None = None, operator=None) -> MealLedgerEntry:
    """ISSUE +meals_total when a pass becomes ACTIVE (idempotent per pass)."""
    key = f"issue:{pass_.public_id}"
    existing = _find_by_key(key)
    if existing is not None:
        return existing
    return _post_entry(
        tenant=_tenant(pass_.tenant_id),
        pass_=pass_,
        entry_type=E.ISSUE,
        quantity=pass_.meals_total,
        source=S.SYSTEM,
        idempotency_key=key,
        operator=operator,
        now=now,
    )


def expire_pass_credits(*, pass_: Pass, now: datetime | None = None) -> MealLedgerEntry:
    """EXPIRE -meals_remaining (a 0-quantity marker when nothing is left)."""
    key = f"expire:{pass_.public_id}"
    existing = _find_by_key(key)
    if existing is not None:
        return existing
    return _post_entry(
        tenant=_tenant(pass_.tenant_id),
        pass_=pass_,
        entry_type=E.EXPIRE,
        quantity=-pass_.meals_remaining,
        source=S.SYSTEM,
        idempotency_key=key,
        now=now,
    )


def zero_out_pass(*, pass_: Pass, reason: str, operator, now: datetime | None = None) -> MealLedgerEntry:
    """EXPIRE-style zeroing entry for cancel / void (source=ADMIN, with a reason)."""
    key = f"cancel:{pass_.public_id}"
    existing = _find_by_key(key)
    if existing is not None:
        return existing
    return _post_entry(
        tenant=_tenant(pass_.tenant_id),
        pass_=pass_,
        entry_type=E.EXPIRE,
        quantity=-pass_.meals_remaining,
        source=S.ADMIN,
        idempotency_key=key,
        operator=operator,
        reason=reason,
        now=now,
    )


def pass_has_redemptions(pass_: Pass) -> bool:
    return MealLedgerEntry.objects.filter(pass_ref=pass_, entry_type=E.REDEEM).exists()


# --- redeem --------------------------------------------------------------------------------------


# Refusals worth an audit row (fraud spotting): the rule blocks plus "nothing to redeem" (D03.9 §B5).
# COOLDOWN_CONFIRM_REQUIRED is a confirmation prompt, not a refusal, so it is not logged.
RULE_CODES = frozenset({"MEAL_SLOT_CLOSED", "MEAL_SLOT_CAP_REACHED", "DAILY_CAP_REACHED"})
DENIAL_CODES = RULE_CODES | {"NO_ACTIVE_PASS", "PASS_NOT_VALID_NOW", "NO_CREDITS", "TENANT_PAUSED", "CUSTOMER_BLOCKED"}


def blocked_message(customer) -> str:
    """'Blocked by the owner: <reason>' (QA-01 P2-11), from the latest block in the audit trail."""
    from mealtally.audit.models import AuditEvent  # noqa: PLC0415

    event = (
        AuditEvent.objects.filter(action="customer.set_status", object_public_id=customer.public_id)
        .order_by("-id")
        .first()
    )
    reason = ((event.after or {}).get("reason") or "").strip() if event else ""
    return _("Blocked by the owner: %(reason)s") % {"reason": reason} if reason else _("Blocked by the owner.")


OVERRIDE_ROLES = (Role.OWNER, Role.MANAGER)


def _served_label(entry: MealLedgerEntry, tz) -> str:
    """'12:41, Counter 1' for the last meal (who served it, in tenant-local time)."""
    op = entry.operator
    who = (op.name or op.email or op.phone_e164) if op is not None else _("System")
    return f"{meal_rules.hhmm(entry.occurred_at.astimezone(tz))}, {who}"


def check_meal_rules(*, pass_: Pass, tenant: Tenant, now: datetime) -> tuple[MealSlot | None, date]:
    """Raise if the pass's meal-time rules forbid a meal at ``now``; else return (slot, meal_date) for the entry.

    Order: is an allowed slot open -> per-slot cap -> per-day cap. A pass with no allowed slots behaves exactly as
    before D03.9 (only the optional daily cap applies). Read-only: callers hold the pass row lock when it matters.
    """
    tz = tenant.zone
    meal_date = local_date(now, tenant.timezone)
    slot = None
    unreversed = MealLedgerEntry.objects.filter(pass_ref=pass_, entry_type=E.REDEEM, reversal__isnull=True)
    if pass_.allowed_slot_ids:
        slots = [s for s in meal_rules.slots_for_ids(pass_.allowed_slot_ids) if s.is_active]
        current = meal_rules.open_slot(slots, now, tz)
        if current is None:
            text, nxt = (
                meal_rules.closed_message(slots, now, tz)
                if slots
                else (_("No meal time is set up for this pass."), None)
            )
            raise MealSlotClosed(
                text,
                details={
                    "next_at": nxt.isoformat() if nxt else None,
                    "slots": [
                        {"name": s.name, "start": meal_rules.hhmm(s.start_time), "end": meal_rules.hhmm(s.end_time)}
                        for s in slots
                    ],
                },
            )
        slot, meal_date = current.slot, current.service_date
        in_slot = unreversed.filter(meal_slot=slot, meal_date=meal_date).select_related("operator")
        if in_slot.count() >= pass_.max_meals_per_slot:
            last = in_slot.order_by("-occurred_at", "-id").first()
            raise MealSlotCapReached(
                _("Already had %(meal)s today (%(served)s).")
                % {"meal": meal_rules.slot_label(slot).lower(), "served": _served_label(last, tz)},
                details={"slot": slot.name, "max_meals_per_slot": pass_.max_meals_per_slot},
            )
    if pass_.max_meals_per_day is not None and _net_redemptions(pass_, meal_date) >= pass_.max_meals_per_day:
        last = unreversed.filter(meal_date=meal_date).select_related("operator").order_by("-occurred_at", "-id").first()
        n = pass_.max_meals_per_day
        text = ngettext("Already had %(n)d meal today", "Already had %(n)d meals today", n) % {"n": n}
        if last is not None:
            text += f" ({_served_label(last, tz)})"
        raise DailyCapReached(text + ".", details={"max_meals_per_day": n})
    return slot, meal_date


def _record_denial(*, actor: Actor, customer, exc: DomainError, source: str) -> None:
    """``redeem.denied`` audit row, written OUTSIDE the failed redeem's savepoint so it survives the refusal."""
    try:
        with transaction.atomic():
            audit.record(
                action="redeem.denied",
                tenant_id=actor.tenant_id,
                actor=actor.user,
                object_type="customer",
                object_public_id=customer.public_id,
                after={"code": exc.code, "message": exc.message, "channel": source, "role": actor.role},
            )
    except Exception:  # an audit failure must never turn a clean refusal into a 500
        logger.exception("could not record redeem.denied")
    exc.keep_transaction = True  # the API must not roll the request back (that would drop this row)


def redeem(
    *,
    actor: Actor,
    customer,
    idempotency_key,
    source: str,
    confirm_additional: bool = False,
    override_reason: str = "",
    device_ref: str | None = None,
    now: datetime | None = None,
) -> RedeemResult:
    """Consume one meal credit. One transaction; the pass row lock serialises concurrent redeems.

    ``override_reason`` (OWNER/MANAGER only) serves a meal the meal-time rules would block; it is audit-logged.
    Refusals in :data:`DENIAL_CODES` are audit-logged as ``redeem.denied``.
    """
    try:
        return _redeem(
            actor=actor,
            customer=customer,
            idempotency_key=idempotency_key,
            source=source,
            confirm_additional=confirm_additional,
            override_reason=(override_reason or "").strip(),
            device_ref=device_ref,
            now=now or timezone.now(),
        )
    except DomainError as exc:
        if exc.code in DENIAL_CODES:
            _record_denial(actor=actor, customer=customer, exc=exc, source=source)
        raise


def _redeem(*, actor, customer, idempotency_key, source, confirm_additional, override_reason, device_ref, now):
    require(actor, Action.REDEEM)
    key = _clean_key(idempotency_key)
    if override_reason and actor.role not in OVERRIDE_ROLES:
        raise NotAllowed(_("Only a manager or the owner can override the meal rules."))
    with transaction.atomic():
        # Idempotent replay first: a retry of a successful call must return the original result.
        replay = _find_by_key(key)
        if replay is not None:
            return _replay(replay, customer)

        tenant = _tenant(actor.tenant_id)
        if tenant.status != Tenant.Status.ACTIVE:
            raise NotAllowed("This restaurant is paused.", code="TENANT_PAUSED")
        if customer.status != customer.Status.ACTIVE:
            raise NotAllowed(blocked_message(customer), code="CUSTOMER_BLOCKED")

        pass_ = passes.lock_active_pass(customer.id)
        if pass_ is None:
            raise NoActivePass("The customer has no active pass.")

        # Re-check under the lock: a parallel call with the same key may just have committed.
        replay = _find_by_key(key)
        if replay is not None:
            return _replay(replay, customer)

        if not (pass_.starts_at <= now <= pass_.ends_at):
            raise PassNotValidNow(
                "The pass is not valid right now.",
                details={"starts_at": pass_.starts_at.isoformat(), "ends_at": pass_.ends_at.isoformat()},
            )
        if pass_.meals_remaining <= 0:
            raise NoCredits("No meal credits left on this pass.")

        overridden = None
        try:
            slot, meal_date = check_meal_rules(pass_=pass_, tenant=tenant, now=now)
        except DomainError as exc:
            if not override_reason or exc.code not in RULE_CODES:
                raise
            overridden = exc
            current = None
            if pass_.allowed_slot_ids:
                current = meal_rules.open_slot(
                    [s for s in meal_rules.slots_for_ids(pass_.allowed_slot_ids) if s.is_active], now, tenant.zone
                )
            slot = current.slot if current else None
            meal_date = current.service_date if current else local_date(now, tenant.timezone)

        cooldown = tenant.settings.redeem_cooldown_seconds
        last = (
            MealLedgerEntry.objects.filter(pass_ref=pass_, entry_type=E.REDEEM, reversal__isnull=True)
            .order_by("-occurred_at", "-id")
            .first()
        )
        if (
            last is not None
            and not confirm_additional
            and overridden is None
            and (now - last.occurred_at) < timedelta(seconds=cooldown)
        ):
            raise CooldownConfirmRequired(
                "This customer was served moments ago. Confirm to redeem an additional meal.",
                details={"last_redeemed_at": last.occurred_at.isoformat(), "cooldown_seconds": cooldown},
            )

        entry = _post_entry(
            tenant=tenant,
            pass_=pass_,
            entry_type=E.REDEEM,
            quantity=-1,
            source=source,
            idempotency_key=key,
            operator=actor.user,
            device_ref=device_ref,
            meal_date=meal_date,
            now=now,
            reason=override_reason if overridden is not None else "",
            meal_slot=slot,
        )
        if overridden is not None:
            audit.record(
                action="redeem.override",
                tenant_id=actor.tenant_id,
                actor=actor.user,
                object_type="ledger_entry",
                object_public_id=entry.public_id,
                before={"code": overridden.code, "message": overridden.message},
                after={"reason": override_reason, "channel": source, "balance": pass_.meals_remaining},
            )
        return RedeemResult(
            entry=entry,
            customer=customer,
            pass_=pass_,
            meals_remaining=pass_.meals_remaining,
            meal_date=meal_date,
            replayed=False,
        )


def _replay(entry: MealLedgerEntry, customer) -> RedeemResult:
    if entry.entry_type != E.REDEEM or entry.customer_id != customer.id:
        raise IdempotencyKeyReused("This idempotency key was already used for a different operation.")
    return _result(entry, replayed=True)


# --- reverse / adjust ----------------------------------------------------------------------------


def reverse_redemption(
    *, actor: Actor, entry_public_id, reason: str, idempotency_key=None, now: datetime | None = None
) -> MealLedgerEntry:
    require(actor, Action.REVERSE)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationFailed("A reason is required.", details={"field": "reason"})
    now = now or timezone.now()
    with transaction.atomic():
        try:
            entry = MealLedgerEntry.objects.select_related("pass_ref").get(public_id=entry_public_id)
        except (MealLedgerEntry.DoesNotExist, ValueError, TypeError, DjangoValidationError) as exc:
            raise NotFound("Ledger entry not found.") from exc
        key = _clean_key(idempotency_key or f"reverse:{entry.public_id}")
        pass_ = Pass.objects.select_for_update().get(pk=entry.pass_ref_id)  # serialise with redeem/adjust

        existing = _find_by_key(key)
        if existing is not None:
            if existing.entry_type == E.REVERSAL and existing.reverses_id == entry.id:
                return existing
            raise IdempotencyKeyReused("This idempotency key was already used for a different operation.")
        if entry.entry_type != E.REDEEM:
            raise ValidationFailed("Only a redemption can be reversed.", code="NOT_A_REDEMPTION")
        if MealLedgerEntry.objects.filter(reverses=entry).exists():
            raise AlreadyReversed("This redemption has already been reversed.")
        if pass_.status != Pass.Status.ACTIVE:
            raise StateConflict("Credits are never restored on a pass that is not ACTIVE.", code="PASS_NOT_ACTIVE")

        tenant = _tenant(actor.tenant_id)
        if actor.role == Role.STAFF:
            window = timedelta(hours=tenant.settings.staff_reversal_window_hours)
            if now - entry.occurred_at >= window or entry.meal_date != local_date(now, tenant.timezone):
                raise NotAllowed("Staff can only reverse today's redemptions inside the reversal window.")
            # D03.9 §A1: the owner decides whether a counter may undo another staff member's meal (default: yes).
            if not tenant.settings.counter_can_reverse_others and entry.operator_id != getattr(actor.user, "pk", None):
                raise NotAllowed(
                    _("Only the person who served this meal, a manager or the owner can undo it."),
                    code="REVERSE_OTHERS_NOT_ALLOWED",
                )

        reversal = _post_entry(
            tenant=tenant,
            pass_=pass_,
            entry_type=E.REVERSAL,
            quantity=+1,
            source=S.ADMIN if actor.role in (Role.OWNER, Role.MANAGER) else S.STAFF_SEARCH,
            idempotency_key=key,
            operator=actor.user,
            reason=reason,
            reverses=entry,
            meal_date=entry.meal_date,  # keeps the daily-cap arithmetic per meal_date
            now=now,
        )
        audit.record(
            action="ledger.reverse",
            tenant_id=actor.tenant_id,
            actor=actor.user,
            object_type="ledger_entry",
            object_public_id=entry.public_id,
            before={"balance": pass_.meals_remaining - 1},
            after={"balance": pass_.meals_remaining, "reversal": str(reversal.public_id), "reason": reason},
        )
        return reversal


def adjust(
    *, actor: Actor, pass_public_id, quantity: int, reason: str, idempotency_key, now: datetime | None = None
) -> MealLedgerEntry:
    require(actor, Action.ADJUST)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationFailed("A reason is required.", details={"field": "reason"})
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity == 0:
        raise ValidationFailed("quantity must be a non-zero integer.", details={"field": "quantity"})
    key = _clean_key(idempotency_key)
    now = now or timezone.now()
    with transaction.atomic():
        pass_ = passes.get_pass(pass_public_id, lock=True)
        existing = _find_by_key(key)
        if existing is not None:
            if existing.entry_type == E.ADJUST and existing.pass_ref_id == pass_.id:
                return existing
            raise IdempotencyKeyReused("This idempotency key was already used for a different operation.")
        if pass_.status != Pass.Status.ACTIVE:
            raise StateConflict("Only an ACTIVE pass can be adjusted.", code="PASS_NOT_ACTIVE")
        before = pass_.meals_remaining
        entry = _post_entry(
            tenant=_tenant(actor.tenant_id),
            pass_=pass_,
            entry_type=E.ADJUST,
            quantity=quantity,
            source=S.ADMIN,
            idempotency_key=key,
            operator=actor.user,
            reason=reason,
            now=now,
        )
        audit.record(
            action="ledger.adjust",
            tenant_id=actor.tenant_id,
            actor=actor.user,
            object_type="pass",
            object_public_id=pass_.public_id,
            before={"meals_remaining": before},
            after={"meals_remaining": pass_.meals_remaining, "quantity": quantity, "reason": reason},
        )
        return entry


# --- reads used by the API -----------------------------------------------------------------------


def entries_for_customer(customer_id: int):
    return MealLedgerEntry.objects.filter(customer_id=customer_id).select_related("pass_ref").order_by("-id")


def consumed_count(pass_: Pass) -> int:
    """Meals consumed on a pass = REDEEMs minus their REVERSALs."""
    base = MealLedgerEntry.objects.filter(pass_ref=pass_)
    return base.filter(entry_type=E.REDEEM).count() - base.filter(entry_type=E.REVERSAL).count()


def daily_redemptions(*, actor: Actor, day: date):
    """REDEEM entries for a tenant-local ``day`` (+ reversed flag). STAFF may only see today."""
    tenant = _tenant(actor.tenant_id)
    today = local_date(timezone.now(), tenant.timezone)
    if actor.role == Role.STAFF:
        require(actor, Action.REPORTS_TODAY)
        if day != today:
            raise NotAllowed("Staff can only view today's redemptions.")
    else:
        require(actor, Action.REPORTS_FULL)
    return (
        MealLedgerEntry.objects.filter(entry_type=E.REDEEM, meal_date=day)
        .select_related("customer", "pass_ref", "operator", "reversal")
        .order_by("-occurred_at", "-id")
    )


# --- reconciliation ------------------------------------------------------------------------------


def find_mismatches() -> list[dict]:
    """Passes whose cached balance disagrees with the ledger, or ended passes not at zero."""
    bad = (
        Pass.objects.annotate(ledger_sum=Coalesce(Sum("ledger_entries__quantity"), 0))
        .filter(
            ~Q(meals_remaining=F("ledger_sum"))
            | Q(status__in=[Pass.Status.EXPIRED, Pass.Status.CANCELLED], meals_remaining__gt=0)
        )
        .values("public_id", "tenant_id", "status", "meals_remaining", "ledger_sum")
    )
    problems = []
    for row in bad:
        problem = {**row, "public_id": str(row["public_id"])}
        logger.error("ledger reconciliation mismatch", extra={"mismatch": problem})
        problems.append(problem)
    return problems


def redeem_status(*, customer, now: datetime | None = None) -> dict:
    """Read-only preview for the console card: would a redeem work, and if not, why? (redeem() re-checks.)"""
    now = now or timezone.now()
    tenant = Tenant.objects.get(pk=customer.tenant_id)
    out = {"state": "ok", "code": None, "pass": None, "meals_today": 0, "last_redeem_at": None}
    today = local_date(now, tenant.timezone)
    day = MealLedgerEntry.objects.filter(customer_id=customer.id, meal_date=today)
    out["meals_today"] = day.filter(entry_type=E.REDEEM).count() - day.filter(entry_type=E.REVERSAL).count()
    pass_ = passes.active_pass_for(customer.id)
    out["pass"] = pass_  # shown even when blocked: the card tells the real meals left (QA-01 P2-11)
    if tenant.status != Tenant.Status.ACTIVE:
        return {**out, "state": "blocked", "code": "TENANT_PAUSED"}
    if customer.status != customer.Status.ACTIVE:
        return {**out, "state": "blocked", "code": "CUSTOMER_BLOCKED", "message": blocked_message(customer)}
    if pass_ is None:
        return {**out, "state": "blocked", "code": "NO_ACTIVE_PASS"}
    if not (pass_.starts_at <= now <= pass_.ends_at):
        return {**out, "state": "blocked", "code": "PASS_NOT_VALID_NOW"}
    if pass_.meals_remaining <= 0:
        return {**out, "state": "blocked", "code": "NO_CREDITS"}
    try:
        check_meal_rules(pass_=pass_, tenant=tenant, now=now)
    except DomainError as exc:
        return {**out, "state": "blocked", "code": exc.code, "message": exc.message, "rule": True}
    last = (
        MealLedgerEntry.objects.filter(pass_ref=pass_, entry_type=E.REDEEM, reversal__isnull=True)
        .order_by("-occurred_at", "-id")
        .first()
    )
    cooldown = tenant.settings.redeem_cooldown_seconds
    if last is not None and (now - last.occurred_at) < timedelta(seconds=cooldown):
        return {**out, "state": "cooldown", "code": "COOLDOWN_CONFIRM_REQUIRED", "last_redeem_at": last.occurred_at}
    return out
