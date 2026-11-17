# SPDX-License-Identifier: AGPL-3.0-only
"""Branded 400/403/404/500 pages that work with no tenant, no session and under the strict CSP.

API paths (``/api/...``) get the JSON error envelope instead of HTML. The 500 handler never touches the database.
"""

from __future__ import annotations

import logging

from django.http import HttpResponse
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)

_COPY = {
    400: ("BAD_REQUEST", "Something was wrong with that request", "Please go back and try again."),
    403: (
        "FORBIDDEN",
        "You can't open this page",
        "You don't have access. If you think that's a mistake, ask the restaurant.",
    ),
    404: ("NOT_FOUND", "We couldn't find that page", "Check the link, or head back to the start."),
    500: ("SERVER_ERROR", "Something went wrong on our side", "We've been told. Please try again in a minute."),
}


def _theme_for(request, status: int) -> str:
    """The restaurant's theme on tenant-scoped URLs (never from the DB on a 500), else the platform's tally."""
    import re  # noqa: PLC0415

    from . import themes  # noqa: PLC0415

    m = re.match(r"^/t/([\w-]+)/", getattr(request, "path", "") or "")
    if m and status != 500:
        try:
            from mealtally.tenancy.context import platform_context  # noqa: PLC0415
            from mealtally.tenancy.models import Tenant  # noqa: PLC0415

            with platform_context():
                name = Tenant.objects.filter(slug=m.group(1)).values_list("theme", flat=True).first()
            if name in themes.THEMES:
                return name
        except Exception:  # noqa: BLE001 -- an error page must never raise
            logger.debug("theme lookup failed for error page", exc_info=True)
    return themes.PLATFORM


def _respond(request, status: int):
    code, title, message = _COPY[status]
    if request is not None and request.path.startswith("/api/"):
        return JsonResponse({"error": {"code": code, "message": _(title), "details": {}}}, status=status)
    try:
        html = render_to_string(
            "web/error.html",
            {"status": status, "title": _(title), "message": _(message), "theme": _theme_for(request, status)},
        )
    except Exception:  # noqa: BLE001 -- the error page itself must never raise (e.g. static manifest missing)
        logger.exception("error template failed")
        html = (
            f"<!doctype html><title>{status}</title><h1>{_(title)}</h1><p>{_(message)}</p><p><a href='/'>Home</a></p>"
        )
    return HttpResponse(html, status=status)


def bad_request(request, exception=None):
    return _respond(request, 400)


def permission_denied(request, exception=None):
    return _respond(request, 403)


def not_found(request, exception=None):
    return _respond(request, 404)


def server_error(request):
    return _respond(request, 500)


def csrf_failure(request, reason=""):
    return _respond(request, 403)
