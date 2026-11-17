# SPDX-License-Identifier: AGPL-3.0-only
from django.db import models
from django.db.models import Q

from mealtally.tenancy.models import TenantOwnedModel
from mealtally.tenancy.models import TenantScopedModel


class MealSlot(TenantOwnedModel):
    """A serving window (Breakfast, Lunch, Dinner...) in the tenant's own timezone.

    ``end_time < start_time`` means the window crosses midnight (e.g. 22:00-01:00); a meal served after midnight in that
    window belongs to the day the window opened. ``grace_minutes`` widens the window on both sides.
    """

    name = models.CharField(max_length=60)
    name_hi = models.CharField("Name (Hindi)", max_length=60, blank=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    grace_minutes = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "start_time", "id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="uniq_meal_slot_name_per_tenant"),
            models.CheckConstraint(condition=~Q(start_time=models.F("end_time")), name="meal_slot_not_empty"),
            models.CheckConstraint(condition=Q(grace_minutes__lte=120), name="meal_slot_grace_max_120"),
        ]
        indexes = [models.Index(fields=["tenant", "is_active"])]

    def __str__(self) -> str:
        return f"{self.name} {self.start_time:%H:%M}-{self.end_time:%H:%M}"


class Plan(TenantOwnedModel):
    class ValidityMode(models.TextChoices):
        ROLLING_DAYS = "ROLLING_DAYS"
        CALENDAR_MONTH = "CALENDAR_MONTH"

    name = models.CharField(max_length=120)
    price_minor = models.PositiveBigIntegerField()
    meals_per_cycle = models.PositiveIntegerField(default=30)
    validity_mode = models.CharField(max_length=16, choices=ValidityMode, default=ValidityMode.ROLLING_DAYS)
    validity_days = models.PositiveIntegerField(default=30, help_text="Used for ROLLING_DAYS.")
    max_meals_per_day = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Blank = no daily cap.")
    # Meal-time rules. No allowed slots = any time.
    allowed_slots = models.ManyToManyField(MealSlot, through="PlanMealSlot", blank=True, related_name="plans")
    max_meals_per_slot = models.PositiveSmallIntegerField(default=1, help_text="Per allowed meal slot, per day.")
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(price_minor__gt=0), name="plan_price_positive"),
            models.CheckConstraint(condition=Q(meals_per_cycle__gt=0), name="plan_meals_positive"),
            models.CheckConstraint(condition=Q(validity_days__gt=0), name="plan_validity_days_positive"),
            models.CheckConstraint(
                condition=Q(max_meals_per_day__isnull=True) | Q(max_meals_per_day__gt=0),
                name="plan_daily_cap_positive_or_null",
            ),
            models.CheckConstraint(condition=Q(max_meals_per_slot__gt=0), name="plan_slot_cap_positive"),
        ]
        indexes = [models.Index(fields=["tenant", "is_active"])]

    def __str__(self) -> str:
        return self.name


class PlanMealSlot(TenantScopedModel):
    """Explicit through table so the plan<->slot link carries ``tenant`` and row-level security like every other row."""

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="+")
    slot = models.ForeignKey(MealSlot, on_delete=models.CASCADE, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["plan", "slot"], name="uniq_plan_meal_slot")]
