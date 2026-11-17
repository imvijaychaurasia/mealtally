# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.hashers import check_password
from django.contrib.auth.hashers import make_password

from mealtally.common.country import normalize_phone
from mealtally.common.errors import ValidationFailed

_DUMMY_HASH = make_password("dummy-password-for-constant-time-checks")


def _active_user(user_id):
    user_model = get_user_model()
    try:
        user = user_model._default_manager.get(pk=user_id)  # noqa: SLF001
    except user_model.DoesNotExist:
        return None
    return user if user.is_active else None


class IdentifierPasswordBackend(BaseBackend):
    """Staff / owner / platform-admin login: e-mail *or* phone + password."""

    def authenticate(self, request, login=None, password=None, username=None, **kwargs):
        identifier = (login or username or "").strip()
        if not identifier or password is None:
            return None
        user_model = get_user_model()
        user = None
        try:
            if "@" in identifier:
                user = user_model._default_manager.filter(email__iexact=identifier).first()  # noqa: SLF001
            else:
                user = user_model._default_manager.filter(phone_e164=normalize_phone(identifier)).first()  # noqa: SLF001
        except ValidationFailed:
            user = None
        if user is None:
            check_password(password, _DUMMY_HASH)  # equalise timing
            return None
        if user.check_password(password) and user.is_active:
            return user
        return None

    def get_user(self, user_id):
        return _active_user(user_id)


class CustomerPinBackend(BaseBackend):
    """Customer login: tenant slug + phone + PIN (the PIN travels as ``password``)."""

    def authenticate(self, request, tenant_slug=None, phone=None, password=None, **kwargs):
        if tenant_slug is None or phone is None or password is None:
            return None
        from mealtally.customers import services as customer_services  # noqa: PLC0415 (avoid import cycle)

        return customer_services.verify_pin(tenant_slug=tenant_slug, phone=phone, pin=password)

    def get_user(self, user_id):
        return _active_user(user_id)
