# SPDX-License-Identifier: AGPL-3.0-only
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from mealtally.tenancy.models import TenantAppendOnlyModel


class MealLedgerEntry(TenantAppendOnlyModel):
    """Append-only source of truth for meal credits (DB trigger rejects UPDATE/DELETE)."""

    class EntryType(models.TextChoices):
        ISSUE = "ISSUE"
        REDEEM = "REDEEM"
        REVERSAL = "REVERSAL"
        ADJUST = "ADJUST"
        EXPIRE = "EXPIRE"

    class Source(models.TextChoices):
        STAFF_SEARCH = "STAFF_SEARCH"
        QR_SCAN = "QR_SCAN"
        DEVICE = "DEVICE"
        SYSTEM = "SYSTEM"
        ADMIN = "ADMIN"

    pass_ref = models.ForeignKey(
        "passes.Pass", on_delete=models.PROTECT, related_name="ledger_entries", db_column="pass_id"
    )
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="ledger_entries")
    entry_type = models.CharField(max_length=8, choices=EntryType)
    quantity = models.IntegerField(help_text="Signed credits: +ISSUE/+REVERSAL, -REDEEM/-EXPIRE, +/-ADJUST.")
    balance_after = models.PositiveIntegerField()
    meal_date = models.DateField(help_text="Date in tenant-local time.")
    occurred_at = models.DateTimeField(default=timezone.now)
    source = models.CharField(max_length=12, choices=Source)
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    device_ref = models.TextField(null=True, blank=True)  # noqa: DJ001
    reason = models.TextField(blank=True)
    reverses = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversal"
    )  # OneToOne == UNIQUE: an entry can be reversed at most once
    idempotency_key = models.TextField()
    # D03.9: the meal slot a REDEEM was served in (NULL without slot rules, and for every other entry type).
    meal_slot = models.ForeignKey(
        "plans.MealSlot", null=True, blank=True, on_delete=models.PROTECT, related_name="+", db_index=False
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="uniq_ledger_idempotency_per_tenant"),
            models.CheckConstraint(
                condition=~Q(entry_type__in=["REVERSAL", "ADJUST"]) | ~Q(reason=""),
                name="ledger_reason_required_for_reversal_adjust",
            ),
            models.CheckConstraint(
                condition=Q(entry_type="REVERSAL", reverses__isnull=False) | ~Q(entry_type="REVERSAL"),
                name="ledger_reversal_points_at_entry",
            ),
        ]
        indexes = [
            models.Index(fields=["pass_ref", "id"]),
            models.Index(fields=["tenant", "meal_date"]),
            models.Index(fields=["customer", "-occurred_at"]),
        ]
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.entry_type} {self.quantity:+d} pass={self.pass_ref_id}"
