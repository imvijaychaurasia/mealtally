from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from mealtally.plans.models import Plan
from mealtally.tenancy.models import TenantOwnedModel


class Pass(TenantOwnedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        ACTIVE = "ACTIVE"
        EXPIRED = "EXPIRED"
        SUSPENDED = "SUSPENDED"
        CANCELLED = "CANCELLED"

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="passes")
    payment = models.OneToOneField("billing.Payment", on_delete=models.PROTECT, related_name="pass_record")
    plan = models.ForeignKey("plans.Plan", on_delete=models.PROTECT, related_name="+")
    # Snapshot of the plan at purchase time (later plan edits never change a sold pass).
    plan_name = models.CharField(max_length=120)
    price_paise = models.PositiveBigIntegerField()
    meals_total = models.PositiveIntegerField()
    validity_mode = models.CharField(max_length=16, choices=Plan.ValidityMode)
    validity_days = models.PositiveIntegerField()
    max_meals_per_day = models.PositiveSmallIntegerField(null=True, blank=True)
    # D03.9 meal-time rules, snapshotted from the plan at sale (slot times stay live: the owner edits Lunch once).
    allowed_slot_ids = ArrayField(models.BigIntegerField(), default=list, blank=True, help_text="Empty = any time.")
    max_meals_per_slot = models.PositiveSmallIntegerField(default=1)

    status = models.CharField(max_length=10, choices=Status)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    meals_remaining = models.PositiveIntegerField(default=0, help_text="Cached balance == SUM(ledger.quantity).")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(meals_remaining__gte=0), name="pass_meals_remaining_non_negative"),
            models.UniqueConstraint(
                fields=["customer"],
                condition=Q(status="ACTIVE"),
                name="uniq_active_pass_per_customer",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "customer", "status"]),
            models.Index(fields=["status", "ends_at"]),
            models.Index(fields=["status", "starts_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.plan_name} ({self.status}) {self.customer_id}"
