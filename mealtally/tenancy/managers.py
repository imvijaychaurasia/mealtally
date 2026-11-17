from __future__ import annotations

from django.db import models

from .context import current_state


class TenantManager(models.Manager):
    """Fail-closed manager: scoped to the active tenant, or unrestricted in platform mode.

    This is the ORM-level half of the isolation story; Postgres RLS is the
    enforcing half. ``scope_field`` is the column that holds the tenant id
    (``tenant_id`` everywhere except ``Tenant`` itself, where it is ``id``).
    """

    def __init__(self, scope_field: str = "tenant_id") -> None:
        super().__init__()
        self.scope_field = scope_field

    def deconstruct(self):  # keep migrations quiet
        return (False, "mealtally.tenancy.managers.TenantManager", (), {"scope_field": self.scope_field})

    def get_queryset(self):
        qs = super().get_queryset()
        state = current_state()
        if state.platform:
            return qs
        if state.tenant_id is None:
            return qs.none()
        return qs.filter(**{self.scope_field: state.tenant_id})
