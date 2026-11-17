# SPDX-License-Identifier: AGPL-3.0-only
from django.contrib import admin

from mealtally.accounts.admin_site import PlatformModelAdmin

from . import services
from .models import DemoRequest
from .models import PlatformSettings
from .models import Tenant
from .models import TenantSettings


@admin.register(Tenant)
class TenantAdmin(PlatformModelAdmin):
    list_display = ("id", "slug", "name", "status", "ui_shell", "theme", "has_demo_dataset", "timezone", "created_at")
    list_editable = ("ui_shell", "theme")  # flip a restaurant between shells straight from the list (D03.4)
    list_filter = ("status", "ui_shell", "theme")
    search_fields = ("slug", "name")
    readonly_fields = ("public_id",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        services.ensure_defaults(obj, actor=request.user)


@admin.register(TenantSettings)
class TenantSettingsAdmin(PlatformModelAdmin):
    list_display = ("tenant", "redeem_cooldown_seconds", "staff_reversal_window_hours", "max_queued_passes")
    readonly_fields = ("public_id", "next_customer_number")


@admin.register(DemoRequest)
class DemoRequestAdmin(PlatformModelAdmin):
    """D03.6: demo enquiries from the landing page (platform admins only)."""

    list_display = ("created_at", "business_name", "city", "business_type", "name", "phone", "handled")
    list_editable = ("handled",)
    list_filter = ("handled", "business_type")
    search_fields = ("business_name", "name", "city", "phone")
    readonly_fields = ("created_at",)


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(PlatformModelAdmin):
    """D03.9: landing-page pricing and legal-page details. Every change is audit-logged (before/after)."""

    fieldsets = (
        ("Landing-page pricing", {"fields": ("marketing_pricing_mode", "pricing_headline", "pricing_footnote")}),
        (
            "Legal pages (privacy notice and terms)",
            {
                "fields": PlatformSettings.LEGAL_FIELDS,
                "description": "Empty fields show 'Contact us' on the pages.",
            },
        ),
    )

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not PlatformSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        from mealtally.audit import services as audit  # noqa: PLC0415

        fields = ("marketing_pricing_mode", "pricing_headline", "pricing_footnote", *PlatformSettings.LEGAL_FIELDS)
        old = PlatformSettings.objects.filter(pk=1).first()
        before = {f: getattr(old, f) for f in fields} if old else None
        super().save_model(request, obj, form, change)
        audit.record(
            action="platform_settings.update",
            tenant_id=None,
            actor=request.user,
            object_type="platform_settings",
            before=before,
            after={f: getattr(obj, f) for f in fields},
        )
