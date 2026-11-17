from django.contrib import admin

from mealtally.accounts.admin_site import PlatformModelAdmin
from mealtally.accounts.admin_site import ReadOnlyAdmin

from .models import FeePolicy
from .models import Payment
from .models import PlatformFeeEntry


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
    """Payments are created/voided via the service layer only (pass + fee side effects)."""

    list_display = ("id", "tenant", "customer", "amount_paise", "method", "status", "received_at")
    list_filter = ("tenant", "method", "status")
    search_fields = ("reference", "customer__full_name", "customer__phone_e164")


@admin.register(FeePolicy)
class FeePolicyAdmin(PlatformModelAdmin):
    list_display = ("tenant", "platform_pct", "gateway_pct", "effective_from")
    list_filter = ("tenant",)
    readonly_fields = ("public_id",)


@admin.register(PlatformFeeEntry)
class PlatformFeeEntryAdmin(ReadOnlyAdmin):
    list_display = ("id", "tenant", "payment", "kind", "sign", "base_paise", "pct", "amount_paise", "created_at")
    list_filter = ("tenant", "kind", "sign")
