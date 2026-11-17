"""Tenant context: the single place that talks to the ``app.*`` Postgres settings.

Two things always move together:

* the Postgres GUCs ``app.tenant_id`` / ``app.platform`` set with
  ``set_config(..., is_local => true)`` (== ``SET LOCAL``) -- these drive the
  row-level-security policies and vanish at COMMIT/ROLLBACK, so a pooled or
  persistent connection can never carry a tenant over to the next request;
* a ``ContextVar`` mirroring them, used by ``TenantManager`` to add an ordinary
  ``WHERE tenant_id = X`` so Postgres can use the tenant indexes (RLS alone is a
  post-scan filter).

No context at all means *zero rows* (fail closed), never "all rows".
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from contextvars import Token
from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.db import transaction


@dataclass(frozen=True)
class TenancyState:
    tenant_id: int | None = None
    platform: bool = False


NO_CONTEXT = TenancyState()
_state: ContextVar[TenancyState] = ContextVar("mealtally_tenancy_state", default=NO_CONTEXT)


def current_state() -> TenancyState:
    return _state.get()


def current_tenant_id() -> int | None:
    return _state.get().tenant_id


def _apply_gucs(state: TenancyState) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.tenant_id', %s, true), set_config('app.platform', %s, true)",
            [str(state.tenant_id) if state.tenant_id is not None else "", "on" if state.platform else "off"],
        )


def begin(state: TenancyState) -> Token[TenancyState]:
    """Enter ``state`` for the *current transaction* (no automatic exit).

    Used by the request layer, where ATOMIC_REQUESTS already provides the
    surrounding transaction. Pair with :func:`end` in a ``finally``.
    """
    if not connection.in_atomic_block:
        msg = "Tenant context requires an open transaction (ATOMIC_REQUESTS or transaction.atomic())."
        raise ImproperlyConfigured(msg)
    _apply_gucs(state)
    return _state.set(state)


def end(token: Token[TenancyState]) -> None:
    previous = token.old_value if token.old_value is not Token.MISSING else NO_CONTEXT
    _state.reset(token)
    _restore_gucs(previous)


def _restore_gucs(previous: TenancyState) -> None:
    # SET LOCAL survives savepoint release until the outer transaction ends, so
    # put the outer value back. Skip when there is nothing to restore into.
    if connection.in_atomic_block and not connection.needs_rollback:
        _apply_gucs(previous)


@contextmanager
def _context(state: TenancyState):
    previous = current_state()
    try:
        with transaction.atomic():
            _apply_gucs(state)
            token = _state.set(state)
            try:
                yield
            finally:
                _state.reset(token)
    finally:
        _restore_gucs(previous)


def tenant_context(tenant_or_id):
    """Run a block as one tenant (RLS + ORM filter). Opens a (nested) transaction."""
    tenant_id = getattr(tenant_or_id, "pk", tenant_or_id)
    if tenant_id is None:
        msg = "tenant_context() needs a saved tenant or an id."
        raise ValueError(msg)
    return _context(TenancyState(tenant_id=int(tenant_id)))


def platform_context():
    """Run a block with cross-tenant (platform) visibility. Use sparingly and explicitly."""
    return _context(TenancyState(platform=True))
