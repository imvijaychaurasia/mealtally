# SPDX-License-Identifier: AGPL-3.0-only
"""Deployment mode and operator feature flags (MEALTALLY_MODE, MEALTALLY_PLATFORM_FEES, ...); see docs/configuration.md.

A switched-off feature answers 404, so it looks exactly as if it weren't installed.
"""

from __future__ import annotations

from functools import wraps

from django.conf import settings
from django.http import Http404


def multi() -> bool:
    return settings.MEALTALLY_MODE == "multi"


def fees() -> bool:
    return settings.MEALTALLY_PLATFORM_FEES


def marketing() -> bool:
    return settings.MEALTALLY_MARKETING_SITE


def requires(check):
    """View decorator: 404 unless ``check()`` is true (for example ``@requires(features.fees)``)."""

    def decorator(view):
        @wraps(view)
        def inner(request, *args, **kwargs):
            if not check():
                raise Http404
            return view(request, *args, **kwargs)

        return inner

    return decorator
