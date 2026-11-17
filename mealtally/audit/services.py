# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

from typing import Any

from .context import get_request_meta
from .models import AuditEvent


def record(
    *,
    action: str,
    tenant_id: int | None,
    actor,
    object_type: str,
    object_public_id=None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditEvent:
    """Write one audit event in the caller's transaction (so it commits/rolls back with the change)."""
    meta = get_request_meta()
    actor_user = actor if (actor is not None and getattr(actor, "pk", None)) else None
    return AuditEvent.objects.create(
        tenant_id=tenant_id,
        actor=actor_user,
        action=action,
        object_type=object_type,
        object_public_id=object_public_id,
        before=before,
        after=after,
        ip=meta.ip,
        user_agent=meta.user_agent,
    )
