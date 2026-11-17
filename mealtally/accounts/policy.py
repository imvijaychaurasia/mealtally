# SPDX-License-Identifier: AGPL-3.0-only
"""Role x action matrix -- the single source of authorisation truth."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from mealtally.common.errors import NotAllowed

from .models import Role


class Action(StrEnum):
    MANAGE_PLANS = "manage_plans"
    MANAGE_STAFF = "manage_staff"
    MANAGE_SETTINGS = "manage_settings"
    CREATE_CUSTOMER = "create_customer"
    EDIT_CUSTOMER = "edit_customer"
    EDIT_OWN_PROFILE = "edit_own_profile"
    RECORD_PAYMENT = "record_payment"
    VOID_PAYMENT = "void_payment"
    REDEEM = "redeem"
    REVERSE = "reverse"
    ADJUST = "adjust"
    SUSPEND_CANCEL_PASS = "suspend_cancel_pass"
    REPORTS_FULL = "reports_full"
    REPORTS_TODAY = "reports_today"
    FEE_STATEMENT = "fee_statement"
    VIEW_OWN_HISTORY = "view_own_history"
    VIEW_AUDIT = "view_audit"
    BLOCK_CUSTOMER = "block_customer"


_O, _M, _S, _C = Role.OWNER, Role.MANAGER, Role.STAFF, Role.CUSTOMER
MATRIX: dict[Action, frozenset[str]] = {
    Action.MANAGE_PLANS: frozenset({_O, _M}),
    Action.MANAGE_STAFF: frozenset({_O}),
    Action.MANAGE_SETTINGS: frozenset({_O}),
    Action.CREATE_CUSTOMER: frozenset({_O, _M, _S}),
    Action.EDIT_CUSTOMER: frozenset({_O, _M, _S}),
    Action.EDIT_OWN_PROFILE: frozenset({_C}),
    Action.RECORD_PAYMENT: frozenset({_O, _M, _S}),
    Action.VOID_PAYMENT: frozenset({_O, _M}),
    Action.REDEEM: frozenset({_O, _M, _S}),
    Action.REVERSE: frozenset({_O, _M, _S}),  # STAFF additionally bound by the reversal window
    Action.ADJUST: frozenset({_O, _M}),
    Action.SUSPEND_CANCEL_PASS: frozenset({_O}),
    Action.REPORTS_FULL: frozenset({_O, _M}),
    Action.REPORTS_TODAY: frozenset({_O, _M, _S}),
    Action.FEE_STATEMENT: frozenset({_O}),  # the platform fee is between the owner and Mealtally
    Action.VIEW_OWN_HISTORY: frozenset({_C}),
    Action.VIEW_AUDIT: frozenset({_O, _M}),
    Action.BLOCK_CUSTOMER: frozenset({_O, _M}),
}


@dataclass(frozen=True)
class Actor:
    """Who is acting, in which tenant, with which (effective) role."""

    user: object  # accounts.User (kept loose to avoid import cycles in services)
    role: str
    tenant_id: int

    def can(self, action: Action) -> bool:
        return self.role in MATRIX[action]


def require(actor: Actor, action: Action) -> None:
    if not actor.can(action):
        raise NotAllowed(f"Role {actor.role} may not perform {action.value}.")
