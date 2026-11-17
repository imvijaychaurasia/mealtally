# SPDX-License-Identifier: AGPL-3.0-only
"""Domain errors shared by every module. The API maps them to the error envelope."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """A business-rule rejection with a stable machine-readable ``code``."""

    code = "ERROR"
    status_code = 400

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.message = message or self.code
        self.details = details or {}
        super().__init__(self.message)


# --- 409: the request is valid but conflicts with current state ---------------
class StateConflict(DomainError):
    status_code = 409


class NoActivePass(StateConflict):
    code = "NO_ACTIVE_PASS"


class PassNotValidNow(StateConflict):
    code = "PASS_NOT_VALID_NOW"


class NoCredits(StateConflict):
    code = "NO_CREDITS"


class DailyCapReached(StateConflict):
    code = "DAILY_CAP_REACHED"


class MealSlotClosed(StateConflict):
    """None of the pass's meal slots is being served right now."""

    code = "MEAL_SLOT_CLOSED"


class MealSlotCapReached(StateConflict):
    """The customer already had their meal(s) in this slot today."""

    code = "MEAL_SLOT_CAP_REACHED"


class CooldownConfirmRequired(StateConflict):
    code = "COOLDOWN_CONFIRM_REQUIRED"


class QrAlreadyUsed(StateConflict):
    code = "QR_ALREADY_USED"


class AlreadyReversed(StateConflict):
    code = "ALREADY_REVERSED"


class IdempotencyKeyReused(StateConflict):
    code = "IDEMPOTENCY_KEY_REUSED"


class QueueFull(StateConflict):
    code = "QUEUE_FULL"


# --- 403 / 404 / 400 / 401 / 429 ----------------------------------------------
class NotAllowed(DomainError):
    code = "NOT_ALLOWED"
    status_code = 403


class NotFound(DomainError):
    code = "NOT_FOUND"
    status_code = 404


class ValidationFailed(DomainError):
    code = "VALIDATION_ERROR"
    status_code = 400


class AuthFailed(DomainError):
    code = "AUTH_FAILED"
    status_code = 401


class AccountLocked(DomainError):
    code = "ACCOUNT_LOCKED"
    status_code = 429
