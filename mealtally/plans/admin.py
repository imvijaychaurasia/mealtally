from django.contrib import admin

from mealtally.accounts.admin_site import PlatformModelAdmin

from .models import Plan


@admin.register(Plan)
class PlanAdmin(PlatformModelAdmin):
    list_display = (
        "id",
        "tenant",
        "name",
        "price_minor",
        "meals_per_cycle",
        "validity_mode",
        "max_meals_per_day",
        "is_active",
    )
    list_filter = ("tenant", "validity_mode", "is_active")
    readonly_fields = ("public_id",)
