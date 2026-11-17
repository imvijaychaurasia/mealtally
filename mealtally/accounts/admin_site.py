# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

from functools import wraps

from django.contrib import admin

from mealtally.tenancy.context import TenancyState
from mealtally.tenancy.context import begin
from mealtally.tenancy.context import end


class PlatformAdminSite(admin.AdminSite):
    """Django admin == the *platform* admin: cross-tenant, platform administrators only."""

    site_header = "Mealtally - platform admin"
    site_title = "Mealtally platform"
    index_title = "Platform administration"

    def has_permission(self, request) -> bool:
        user = request.user
        return bool(user.is_active and getattr(user, "is_platform_admin", False))

    def admin_view(self, view, cacheable=False):
        inner = super().admin_view(view, cacheable)

        @wraps(inner)
        def wrapper(request, *args, **kwargs):
            if not self.has_permission(request):
                return inner(request, *args, **kwargs)  # redirects to the login page
            token = begin(TenancyState(platform=True))
            try:
                return inner(request, *args, **kwargs)
            finally:
                end(token)

        return wrapper


class PlatformModelAdmin(admin.ModelAdmin):
    """ModelAdmin whose permissions follow ``is_platform_admin`` (not Django model perms)."""

    def has_module_permission(self, request):
        return self.admin_site.has_permission(request)

    def has_view_permission(self, request, obj=None):
        return self.admin_site.has_permission(request)

    def has_add_permission(self, request):
        return self.admin_site.has_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.admin_site.has_permission(request)

    def has_delete_permission(self, request, obj=None):
        return self.admin_site.has_permission(request)


class ReadOnlyAdmin(PlatformModelAdmin):
    """For immutable (append-only) tables."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
