# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

from axes.handlers.proxy import AxesProxyHandler
from django.contrib.auth import authenticate
from django.contrib.auth import login
from django.contrib.auth import logout
from django.middleware.csrf import get_token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from mealtally.accounts.models import Membership
from mealtally.api import serializers as s
from mealtally.api.throttles import LoginThrottle
from mealtally.common.errors import AccountLocked
from mealtally.common.errors import AuthFailed
from mealtally.customers import services as customers
from mealtally.tenancy import services as tenancy
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.context import tenant_context


def authenticate_with_lockout(request, **credentials):
    """authenticate() + django-axes lockout (5 failures -> 15 min) with distinct error codes."""
    http_request = getattr(request, "_request", request)  # axes/login need the real HttpRequest
    lock = AccountLocked("Too many failed attempts. Try again in 15 minutes.", details={"retry_after_seconds": 900})
    if not AxesProxyHandler.is_allowed(http_request, credentials):
        raise lock
    user = authenticate(http_request, **credentials)
    if user is None:
        if not AxesProxyHandler.is_allowed(http_request, credentials):
            raise lock
        raise AuthFailed("Invalid credentials.")
    return user


class _PublicAuthView(APIView):
    authentication_classes = ()  # no session => no CSRF requirement on login
    permission_classes = (AllowAny,)
    throttle_classes = (LoginThrottle,)


class CsrfView(APIView):
    """GET to receive the CSRF cookie (then send it back as X-CSRFToken on unsafe requests)."""

    authentication_classes = ()
    permission_classes = (AllowAny,)

    def get(self, request):
        return Response({"csrf_token": get_token(request._request)})  # noqa: SLF001


class StaffLoginView(_PublicAuthView):
    """Staff, owners and platform admins: e-mail or phone + password (session cookie)."""

    def post(self, request):
        data = s.StaffLoginIn(data=request.data)
        data.is_valid(raise_exception=True)
        user = authenticate_with_lockout(
            request, login=data.validated_data["login"], password=data.validated_data["password"]
        )
        login(request._request, user)  # noqa: SLF001
        with platform_context():
            memberships = [
                {"tenant": slug, "role": role}
                for slug, role in Membership.objects.filter(user=user, is_active=True)
                .exclude(role="CUSTOMER")
                .values_list("tenant__slug", "role")
            ]
        return Response(
            {
                "user": {"id": user.pk, "name": user.name, "email": user.email, "phone": user.phone_e164},
                "is_platform_admin": user.is_platform_admin,
                "must_change_password": user.must_change_password,
                "memberships": memberships,
            }
        )


class LogoutView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def post(self, request, **kwargs):
        logout(request._request)  # noqa: SLF001
        return Response({"detail": "Logged out."})


class CustomerLoginView(_PublicAuthView):
    """Customers: tenant slug (URL) + phone + 6-digit PIN."""

    def post(self, request, tenant_slug):
        data = s.CustomerLoginIn(data=request.data)
        data.is_valid(raise_exception=True)
        user = authenticate_with_lockout(
            request, tenant_slug=tenant_slug, phone=data.validated_data["phone"], password=data.validated_data["pin"]
        )
        login(request._request, user, backend="mealtally.accounts.backends.CustomerPinBackend")  # noqa: SLF001
        tenant = tenancy.get_tenant_by_slug(tenant_slug)
        with tenant_context(tenant.id):
            customer = customers.get_customer_for_user(user=user, tenant_id=tenant.id)
            return Response({"customer": s.customer_out(customer), "must_change_pin": customer.must_change_pin})
