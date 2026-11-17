"""Scoped Content-Security-Policy relaxation.

The whole site runs on the strict policy from settings (``script-src 'self'``, ``style-src 'self'``). Two
third-party UIs need more and ONLY they get it, by URL prefix:

* Django admin (``/platform/admin/``): inline ``style`` attributes.
* Swagger UI (``/api/v1/docs/``): inline bootstrap script + styles.

Nothing else is relaxed (ADR 0013).
"""

from __future__ import annotations

import re

SCOPES = {
    "/platform/admin/": {"style-src": "'self' 'unsafe-inline'"},
    "/api/v1/docs/": {
        "style-src": "'self' 'unsafe-inline'",
        "script-src": "'self' 'unsafe-inline'",
        "img-src": "'self' data:",
    },
}


class ScopedCSPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        for prefix, overrides in SCOPES.items():
            if request.path.startswith(prefix):
                header = response.headers.get("Content-Security-Policy")
                if header:
                    directives = {}
                    for raw in header.split(";"):
                        part = raw.strip()
                        if part:
                            name, _sep, value = part.partition(" ")
                            directives[name] = value
                    directives.update(overrides)
                    response.headers["Content-Security-Policy"] = "; ".join(
                        f"{k} {v}".strip() for k, v in directives.items()
                    )
        return response


class PermissionsPolicyMiddleware:
    """D03.9 §D2: the app owns the camera permission. ``camera=(self)`` ONLY on the counter scan page (the staff
    console, the one page with the live QR scanner); every other page sends ``camera=()``. The driver's photo proof uses
    a file input with ``capture``, which needs no camera permission. Microphone and geolocation are off everywhere.

    NOTE: Traefik's entrypoint ``security-headers`` middleware OVERWRITES this header today (verified with curl, D03.9),
    so the edge value is what browsers see until the edge stops setting Permissions-Policy for Mealtally.
    """

    CAMERA_SELF = "camera=(self), microphone=(), geolocation=()"
    CAMERA_OFF = "camera=(), microphone=(), geolocation=()"
    PATH = re.compile(r"^/t/[^/]+/staff/?$")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers["Permissions-Policy"] = (
            self.CAMERA_SELF if self.PATH.match(request.path_info) else self.CAMERA_OFF
        )
        return response


class CanonicalSlashMiddleware:
    """``/t/x/admin/customers/`` (404) -> permanent redirect to the canonical ``/t/x/admin/customers`` when that exists.

    The inverse (missing slash on slash-terminated routes) is already handled by Django's APPEND_SLASH.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = request.path_info
        if (
            response.status_code == 404
            and len(path) > 1
            and path.endswith("/")
            and not path.startswith(("/api/", "/static/"))
        ):
            from django.http import HttpResponsePermanentRedirect  # noqa: PLC0415
            from django.urls import Resolver404  # noqa: PLC0415
            from django.urls import resolve  # noqa: PLC0415

            try:
                resolve(path.rstrip("/"))
            except Resolver404:
                return response
            query = request.META.get("QUERY_STRING", "")
            return HttpResponsePermanentRedirect(path.rstrip("/") + (f"?{query}" if query else ""))
        return response
