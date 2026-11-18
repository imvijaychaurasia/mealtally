# SPDX-License-Identifier: AGPL-3.0-only
"""Sign-in redirects: send people to the sign-in page and back to where they were (``?next=``), never to another site.

Views that redirect to a ``next`` from the request call ``url_has_allowed_host_and_scheme`` themselves, in the
``if`` around the redirect, where code scanning recognises it as the guard; ``safe_next`` is the same check for code.

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
