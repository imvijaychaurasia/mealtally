# SPDX-License-Identifier: AGPL-3.0-only
"""The language picker: Django's set_language (cookie), plus the signed-in person's saved preference."""

from __future__ import annotations

from django.conf import settings
from django.utils import translation
from django.views.decorators.http import require_POST
from django.views.i18n import set_language as django_set_language

from mealtally.accounts.models import User
from mealtally.tenancy.context import platform_context


@require_POST
def set_language(request):
    response = django_set_language(request)
    code = request.POST.get("language", "")
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and translation.check_for_language(code):
        if code in dict(settings.LANGUAGES):
            with platform_context():
                User.objects.filter(pk=user.pk).update(preferred_language=code)
    return response


def activate_preferred(request, tenant=None) -> None:
    """No language chosen on this device: use the person's saved one, else the restaurant's default."""
    if request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME):
        return
    user = getattr(request, "user", None)
    code = getattr(user, "preferred_language", "") if user is not None and user.is_authenticated else ""
    code = code or (tenant.default_language if tenant is not None else "")
    if code and code in dict(settings.LANGUAGES):
        translation.activate(code)
        request.LANGUAGE_CODE = code
