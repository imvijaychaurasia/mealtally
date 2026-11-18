# SPDX-License-Identifier: AGPL-3.0-only
"""Redirects that take a target from the request (``?next=``) go through here, so none can send people to another site.

Django's ``url_has_allowed_host_and_scheme`` is the check: it rejects other hosts, ``//host`` and ``/\\host`` (which
browsers read as ``//host``), and ``javascript:`` URLs.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


def is_safe(request, url: str) -> bool:
    return bool(url) and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    )


def safe_next(request, url: str, fallback: str) -> str:
    """``url`` when it stays on this site, else ``fallback``."""
    return url if is_safe(request, url) else fallback


def to_login(request, login_url: str):
    """Redirect to ``login_url`` and come back to the current page afterwards (``?next=``, encoded)."""
    here = request.get_full_path()
    query = urlencode({"next": safe_next(request, here, "/")}, safe="/")
    return redirect(f"{login_url}?{query}")
