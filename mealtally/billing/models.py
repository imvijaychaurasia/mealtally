from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from mealtally.tenancy.models import TenantAppendOnlyModel
from mealtally.tenancy.models import TenantOwnedModel


class Payment(TenantOwnedModel):
    """A manual payment (cash / UPI / card / bank transfer) for one plan purchase."""

    class Method(models.TextChoices):
        CASH = "CASH"
        UPI_MANUAL = "UPI_MANUAL"
        CARD_MANUAL = "CARD_MANUAL"
        BANK_TRANSFER = "BANK_TRANSFER"
        GATEWAY = "GATEWAY", "Gateway (reserved)"

    class Status(models.TextChoices):
        RECORDED = "RECORDED"
        VOIDED = "VOIDED"

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="payments")
    plan = models.ForeignKey("plans.Plan", on_delete=models.PROTECT, related_name="+")
    amount_paise = models.PositiveBigIntegerField()
    method = models.CharField(max_length=14, choices=Method)
    reference = models.CharField(max_length=120, blank=True, help_text="UPI UTR etc.; required unless CASH.")
    received_at = models.DateTimeField(default=timezone.now)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=8, choices=Status, default=Status.RECORDED)
    receipt_number = models.CharField(max_length=20, blank=True, help_text="R-000001, sequential per tenant.")
    void_reason = models.TextField(blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "-received_at"]),
            models.Index(fields=["tenant", "customer"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(amount_paise__gt=0), name="payment_amount_positive"),
            models.UniqueConstraint(
                fields=["tenant", "receipt_number"],
                condition=~Q(receipt_number=""),
                name="uniq_receipt_number_per_tenant",
            ),
        ]


class FeePolicy(TenantOwnedModel):
    """Per-tenant fee percentages; the latest row with effective_from <= payment.received_at applies."""

    platform_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("12.00"))
    gateway_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10.00"))
    effective_from = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["tenant", "-effective_from"])]
        verbose_name_plural = "fee policies"


class PlatformFeeEntry(TenantAppendOnlyModel):
    class Kind(models.TextChoices):
        PLATFORM = "PLATFORM"
        GATEWAY = "GATEWAY"

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="fee_entries")
    kind = models.CharField(max_length=8, choices=Kind)
    base_paise = models.PositiveBigIntegerField()
    pct = models.DecimalField(max_digits=5, decimal_places=2)
    amount_paise = models.PositiveBigIntegerField()
    sign = models.SmallIntegerField(help_text="+1 charge, -1 reversal (void).")

    class Meta:
        indexes = [models.Index(fields=["tenant", "created_at"]), models.Index(fields=["payment"])]
        constraints = [
            models.CheckConstraint(condition=Q(sign__in=[1, -1]), name="fee_entry_sign_valid"),
        ]
