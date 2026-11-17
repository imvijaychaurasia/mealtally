from __future__ import annotations

import contextlib

from mealtally.common.country import normalize_phone
from mealtally.common.errors import ValidationFailed


def get_username(request, credentials) -> str:
    """Lockout identity: ``slug:phone`` for customers, the normalised identifier for staff."""
    credentials = credentials or {}
    if credentials.get("tenant_slug"):
        phone = str(credentials.get("phone") or "")
        with contextlib.suppress(ValidationFailed):
            phone = normalize_phone(phone)
        return f"{str(credentials['tenant_slug']).lower()}:{phone}"
    return str(credentials.get("login") or credentials.get("username") or "").strip().lower()
