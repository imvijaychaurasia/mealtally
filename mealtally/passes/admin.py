# SPDX-License-Identifier: AGPL-3.0-only
from django.contrib import admin

from mealtally.accounts.admin_site import ReadOnlyAdmin

from .models import Pass


@admin.register(Pass)
class PassAdmin(ReadOnlyAdmin):
    """Read-only: pass state changes go through services (ledger + audit)."""

    list_display = ("id", "tenant", "customer", "plan_name", "status", "meals_remaining", "starts_at", "ends_at")
    list_filter = ("tenant", "status", "validity_mode")
    search_fields = ("customer__full_name", "customer__phone_e164")
