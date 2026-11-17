from django.contrib import admin

from mealtally.accounts.admin_site import ReadOnlyAdmin

from .models import MealLedgerEntry


@admin.register(MealLedgerEntry)
class MealLedgerEntryAdmin(ReadOnlyAdmin):
    list_display = ("id", "tenant", "customer", "entry_type", "quantity", "balance_after", "meal_date", "source")
    list_filter = ("tenant", "entry_type", "source")
    search_fields = ("customer__full_name", "customer__phone_e164", "idempotency_key")
    date_hierarchy = "occurred_at"
