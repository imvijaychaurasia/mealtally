# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import ipaddress

from django.conf import settings


def _trusted(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in ipaddress.ip_network(cidr, strict=False) for cidr in settings.MEALTALLY_TRUSTED_PROXY_CIDRS)


def client_ip(request) -> str | None:
    """Real client address. X-Forwarded-For counts only with MEALTALLY_TRUST_PROXY=true and from a trusted proxy."""
    remote = request.META.get("REMOTE_ADDR")
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if settings.MEALTALLY_TRUST_PROXY and remote and forwarded and _trusted(remote):
        # the proxy appends the connecting address; take the right-most entry
        candidate = forwarded.split(",")[-1].strip()
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            return remote
        return candidate
    return remote
