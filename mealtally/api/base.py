"""Base views that bind the URL's tenant to the DB transaction (RLS) and to an ``Actor``."""

from __future__ import annotations

from rest_framework.views import APIView

from mealtally.accounts import services as accounts
from mealtally.accounts.models import STAFF_ROLES
from mealtally.accounts.models import Role
from mealtally.accounts.policy import Actor
from mealtally.common.errors import NotAllowed
from mealtally.common.errors import NotFound
from mealtally.tenancy.context import TenancyState
from mealtally.tenancy.context import begin
from mealtally.tenancy.context import end
from mealtally.tenancy.models import Tenant

ALL_ROLES = (*STAFF_ROLES, Role.CUSTOMER)


CREDENTIAL_CHANGE_REQUIRED = "CREDENTIAL_CHANGE_REQUIRED"


def enforce_credential_change(user, role, tenant_id) -> None:
    """D02.1 Q2: while a temporary password / PIN is still in force, nothing but the change itself works."""
    from mealtally.customers.models import Customer  # noqa: PLC0415

    if role == Role.CUSTOMER:
        pending = Customer.objects.filter(user=user, must_change_pin=True).exists()
        what = "PIN"
    else:
        pending = bool(user.must_change_password)
        what = "password"
    if pending:
        raise NotAllowed(f"You must change your temporary {what} first.", code=CREDENTIAL_CHANGE_REQUIRED)


class TenantAPIView(APIView):
    """Resolve ``/t/<tenant_slug>/`` -> tenant, check Membership, enter tenant context.

    Runs inside ATOMIC_REQUESTS' transaction, so the ``SET LOCAL`` context ends with the request.
    A user with no active membership at that tenant gets 404 (never 403: do not reveal tenants).
    """

    allowed_roles: tuple[str, ...] = STAFF_ROLES
    credential_exempt = False  # set on `me` and change-PIN so a customer can see/fix the requirement
    _ctx_token = None

    def dispatch(self, request, *args, **kwargs):
        self._ctx_token = None
        self.tenant_slug = kwargs.pop("tenant_slug")  # consumed here; handlers never see it
        try:
            return super().dispatch(request, *args, **kwargs)
        finally:
            if self._ctx_token is not None:
                end(self._ctx_token)
                self._ctx_token = None

    def perform_authentication(self, request):
        super().perform_authentication(request)
        user = request.user
        if not user.is_authenticated:
            return  # IsAuthenticated will answer 401
        slug = self.tenant_slug
        token = begin(TenancyState(platform=True))  # only to look the tenant & membership up
        try:
            tenant = Tenant.objects.filter(slug=slug).first()
            roles = accounts.active_roles(user=user, tenant_id=tenant.id) if tenant else []
        finally:
            end(token)
        role = accounts.effective_role(roles)
        if tenant is None or role is None:
            raise NotFound("Not found.")
        if role not in self.allowed_roles:
            raise NotAllowed("Your role may not use this endpoint.", code="FORBIDDEN")
        if tenant.status != Tenant.Status.ACTIVE:
            raise NotAllowed("This tenant is not active.")
        self._ctx_token = begin(TenancyState(tenant_id=tenant.id))
        request.tenant = tenant
        request.actor = Actor(user=user, role=role, tenant_id=tenant.id)
        if not self.credential_exempt:
            enforce_credential_change(user, role, tenant.id)


class PlatformAPIView(APIView):
    """Platform administrators only; runs in platform (cross-tenant) context."""

    _ctx_token = None

    def dispatch(self, request, *args, **kwargs):
        self._ctx_token = None
        try:
            return super().dispatch(request, *args, **kwargs)
        finally:
            if self._ctx_token is not None:
                end(self._ctx_token)
                self._ctx_token = None

    def perform_authentication(self, request):
        super().perform_authentication(request)
        user = request.user
        if not user.is_authenticated:
            return
        if not user.is_active or not user.is_platform_admin:
            raise NotAllowed("Platform administrators only.", code="FORBIDDEN")
        if user.must_change_password:
            raise NotAllowed("You must change your temporary password first.", code=CREDENTIAL_CHANGE_REQUIRED)
        self._ctx_token = begin(TenancyState(platform=True))
