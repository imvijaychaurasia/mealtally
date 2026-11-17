# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant resolution + role gate for server-rendered views (same rules as the API's TenantAPIView)."""

from __future__ import annotations

from functools import wraps

from django.http import Http404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from mealtally.accounts import services as accounts
from mealtally.accounts.models import STAFF_ROLES
from mealtally.accounts.models import Role
from mealtally.accounts.policy import Actor
from mealtally.common import money
from mealtally.customers.models import Customer
from mealtally.tenancy import services as tenancy
from mealtally.tenancy.context import TenancyState
from mealtally.tenancy.context import begin
from mealtally.tenancy.context import end
from mealtally.tenancy.models import Tenant
from mealtally.web.views_language import activate_preferred

ANY_MEMBER = (*STAFF_ROLES, Role.CUSTOMER)


def home_url(slug: str, role: str, demo: bool = False) -> str:
    if role == Role.CUSTOMER:
        return reverse("web:me-home", args=[slug])
    if role == Role.STAFF:
        return reverse("web:staff-console", args=[slug])
    if role == Role.CHEF:
        return reverse("preview:kitchen", args=[slug])
    if role == Role.DRIVER:
        return reverse("preview:driver", args=[slug])
    if demo:
        return reverse("preview:today", args=[slug])
    return reverse("web:admin-dashboard", args=[slug])


def tenant_view(*, roles=ANY_MEMBER, public=False, allow_forced=False):
    """Decorator. ``public`` views need no login (tenant home, login, sign-up)."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, slug, *args, **kwargs):
            token = begin(TenancyState(platform=True))
            try:
                tenant = Tenant.objects.filter(slug=slug).first()
                member_roles = (
                    accounts.active_roles(user=request.user, tenant_id=tenant.id)
                    if (tenant and request.user.is_authenticated)
                    else []
                )
            finally:
                end(token)
            request.member_roles = member_roles
            if tenant is None:
                return render(request, "web/not_found.html", {"slug": slug}, status=404)
            request.tenant = tenant
            # Templates render aware datetimes in the *current* timezone and money in the *current* currency: make both
            # the tenant's for this request only (never leaks into the next one).
            activate_preferred(request, tenant)
            money_token = money.use(tenant.currency, tenant.country)
            try:
                with timezone.override(tenant.zone):
                    return _serve(request, tenant, slug, args, kwargs)
            finally:
                money.reset(money_token)

        def _serve(request, tenant, slug, args, kwargs):
            if tenant.status != Tenant.Status.ACTIVE:
                return render(request, "web/paused.html", {"tenant": tenant}, status=403)
            member_roles = request.member_roles
            role = accounts.effective_role(member_roles)
            request.role = role
            if not public:
                if not request.user.is_authenticated:
                    return redirect(f"{reverse('web:tenant-home', args=[slug])}?next={request.path}")
                if role is None:
                    return render(request, "web/not_found.html", {"slug": slug}, status=404)  # non-member: 404
                if role not in roles:
                    return redirect(home_url(slug, role, demo=tenant.has_demo_dataset))
            ctx_token = begin(TenancyState(tenant_id=tenant.id))
            try:
                request.cfg = tenancy.get_settings(tenant.id)
                request.actor = Actor(user=request.user, role=role, tenant_id=tenant.id) if role else None
                if role and not allow_forced and not public:
                    forced = _forced_redirect(request, slug, role)
                    if forced:
                        return forced
                return view(request, *args, **kwargs)
            finally:
                end(ctx_token)

        return wrapper

    return decorator


def _forced_redirect(request, slug, role):
    if role == Role.CUSTOMER:
        cust = Customer.objects.filter(user=request.user).first()
        if cust and cust.must_change_pin:
            return redirect("web:me-pin", slug=slug)
    elif request.user.must_change_password:
        return redirect("web:staff-password", slug=slug)
    return None


def htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def require_customer(request) -> Customer:
    cust = Customer.objects.filter(user=request.user).select_related("user").first()
    if cust is None:
        raise Http404
    return cust
