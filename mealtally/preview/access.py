"""Role-gated preview views: 404 for roles a module does not allow, "Coming soon" for tenants without the dataset."""

from __future__ import annotations

from functools import wraps

from django.shortcuts import render

from mealtally.accounts.models import Role
from mealtally.web.access import tenant_view

from . import data
from .registry import BY_KEY

ALL = (Role.OWNER, Role.MANAGER, Role.STAFF, Role.CHEF, Role.DRIVER, Role.CUSTOMER)


def preview_view(key: str, *, public: bool = False, roles=None):
    """Decorator: ``@preview_view("orders")`` -> view(request, D, **kwargs) with the dataset ``D`` (or Coming soon)."""
    module = BY_KEY.get(key)
    allowed = roles or (module.roles if module else ALL)

    def decorator(view):
        @wraps(view)
        def inner(request, *args, **kwargs):
            if not public and request.role not in allowed:
                return render(request, "web/not_found.html", {"slug": request.tenant.slug}, status=404)
            request.pv_module = module
            if not request.tenant.has_demo_dataset:
                return render(
                    request, "preview/coming_soon.html", {"module": module, "title": module.title if module else ""}
                )
            D = data.for_tenant(request.tenant)
            return view(request, D, *args, **kwargs)

        return tenant_view(roles=ALL, public=public)(inner)

    return decorator
