from django.contrib import admin

from mealtally.accounts.admin_site import PlatformModelAdmin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(PlatformModelAdmin):
    """Creation goes through the service layer (PIN + code allocation); admin can edit status/notes."""

    list_display = ("customer_code", "tenant", "full_name", "phone_e164", "status")
    list_filter = ("tenant", "status")
    search_fields = ("customer_code", "full_name", "phone_e164")
    readonly_fields = ("public_id", "customer_code", "pin_hash", "user", "tenant")

    def has_add_permission(self, request):
        return False
