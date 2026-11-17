from __future__ import annotations

import uuid
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from .managers import TenantManager


def validate_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(f"{value!r} is not a valid IANA timezone.") from exc


class Tenant(models.Model):
    """A business (e.g. a tiffin restaurant). Row visible only to itself (RLS on ``id``)."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        SUSPENDED = "SUSPENDED"
        DEACTIVATED = "DEACTIVATED"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(
        max_length=50,
        unique=True,
        validators=[RegexValidator(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", "Lowercase letters, digits and hyphens only.")],
    )
    status = models.CharField(max_length=12, choices=Status, default=Status.ACTIVE)
    timezone = models.CharField(max_length=64, default="Asia/Kolkata", validators=[validate_timezone])
    currency = models.CharField(max_length=3, default="INR")
    is_test = models.BooleanField(
        default=False, help_text="e2e/perf tenants: hidden from platform lists and metrics by default."
    )
    has_demo_dataset = models.BooleanField(
        default=False, help_text="D03: serve the deterministic preview dataset for not-yet-built modules."
    )

    class UiShell(models.TextChoices):
        CLASSIC = "classic", "Classic (top navigation)"
        CONSOLE = "console", "Console (left sidebar + dashboard)"

    ui_shell = models.CharField(
        max_length=10,
        choices=UiShell,
        default=UiShell.CONSOLE,
        help_text="D03.4: which app shell staff see. Flip here (no deploy) to switch a restaurant between the two.",
    )

    class Theme(models.TextChoices):
        MASALA = "masala", "Masala kitchen"
        FRESH = "fresh", "Fresh market"
        TALLY = "tally", "Mealtally"

    theme = models.CharField(
        max_length=10,
        choices=Theme,
        default=Theme.MASALA,
        help_text="D03.5: colour theme for this restaurant's screens (platform screens are always Mealtally).",
    )
    show_preview_badges = models.BooleanField(default=True, help_text="D03: show the 'Preview' badge on preview pages.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager(scope_field="id")

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return self.slug

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


class TenantScopedModel(models.Model):
    """Base for every tenant-scoped table: bigint PK, indexed NOT NULL ``tenant``, ``public_id``."""

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT, related_name="+")
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    objects = TenantManager()

    class Meta:
        abstract = True


class TenantOwnedModel(TenantScopedModel):
    """Tenant-scoped, mutable rows: adds created_at / updated_at."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantAppendOnlyModel(TenantScopedModel):
    """Tenant-scoped, immutable rows (DB trigger rejects UPDATE/DELETE): created_at only."""

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class TenantSettings(TenantOwnedModel):
    tenant = models.OneToOneField("tenancy.Tenant", on_delete=models.PROTECT, related_name="settings")
    redeem_cooldown_seconds = models.PositiveIntegerField(default=120)
    staff_reversal_window_hours = models.PositiveIntegerField(default=12)
    # D03.9 §A1 (Vijay's decision: yes): counters may reverse other staff members' redemptions inside the window.
    counter_can_reverse_others = models.BooleanField(default=True)
    max_queued_passes = models.PositiveSmallIntegerField(default=1)
    customer_pin_length = models.PositiveSmallIntegerField(default=6)
    display_name = models.CharField(max_length=200, blank=True)
    # Counters for human-friendly customer codes (C0001...) and receipts (R-000001). Row-locked on use.
    next_customer_number = models.PositiveIntegerField(default=1)
    next_receipt_number = models.PositiveIntegerField(default=1)
    address = models.TextField(blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    brand_color = models.CharField(max_length=7, default="#0f766e")  # deep teal
    receipt_footer = models.CharField(max_length=300, blank=True)
    gstin = models.CharField("GSTIN", max_length=15, blank=True)
    fssai_no = models.CharField("FSSAI licence no.", max_length=20, blank=True)
    allow_self_signup = models.BooleanField(default=False)
    tagline = models.CharField(max_length=120, blank=True, help_text="D03.6: one line shown on the sign-in screens.")
    # D03.9 (QA-01 P1-6): wallet top-up bounds.
    topup_min_paise = models.PositiveBigIntegerField(default=10_000)  # Rs 100
    topup_max_paise = models.PositiveBigIntegerField(default=5_000_000)  # Rs 50,000
    # D03.9 §B6: the one-time "Set meal times and daily limits for your plans" banner was dismissed.
    meal_rules_banner_dismissed = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "tenant settings"


class DemoRequest(models.Model):
    """D03.6: a 'Book a demo' enquiry from the public landing page. Platform-scoped: no tenant, outside tenant RLS."""

    class BusinessType(models.TextChoices):
        TIFFIN = "tiffin", "Tiffin service"
        MESS = "mess", "Mess / dine-in"
        CLOUD = "cloud", "Cloud kitchen"
        CANTEEN = "canteen", "Canteen / corporate meals"
        OTHER = "other", "Other"

    name = models.CharField(max_length=120)
    business_name = models.CharField(max_length=160)
    city = models.CharField(max_length=80)
    phone = models.CharField(max_length=16)
    business_type = models.CharField(max_length=12, choices=BusinessType, default=BusinessType.TIFFIN)
    message = models.TextField(blank=True, max_length=1000)
    handled = models.BooleanField(default=False, help_text="Tick once someone has followed up.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.business_name} ({self.city}) · {self.name}"


class PlatformSettings(models.Model):
    """D03.9 §A2/§A3: platform-wide settings, edited in platform admin (no restart). One row (pk=1); no tenant, no RLS.

    The landing-page pricing and the legal pages read from here. Empty legal fields show "Contact us" on the pages,
    never bracketed placeholder text.
    """

    class PricingMode(models.TextChoices):
        PERCENTAGE = "percentage", "Show the fee percentages"
        CONTACT = "contact", "Contact us for pricing"

    marketing_pricing_mode = models.CharField(
        "Landing-page pricing", max_length=12, choices=PricingMode, default=PricingMode.PERCENTAGE
    )
    pricing_headline = models.CharField(max_length=120, blank=True, help_text="Optional; replaces the default title.")
    pricing_footnote = models.CharField(max_length=300, blank=True, help_text="Optional small print under the price.")
    legal_entity_name = models.CharField(max_length=200, blank=True)
    registered_address = models.TextField(blank=True)
    contact_email = models.EmailField(blank=True)
    grievance_officer_name = models.CharField(max_length=120, blank=True, help_text="DPDP Act: grievance officer.")
    grievance_officer_email = models.EmailField(blank=True)
    demo_request_retention = models.CharField(
        max_length=120, blank=True, help_text="How long demo requests are kept, e.g. '12 months'."
    )
    governing_law = models.CharField(max_length=120, blank=True, help_text="e.g. 'the laws of India; courts in Pune'.")
    terms_changes_notice = models.CharField(
        max_length=200,
        blank=True,
        help_text="How changes to the terms are announced, e.g. 'by email, 30 days ahead'.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    LEGAL_FIELDS = (
        "legal_entity_name",
        "registered_address",
        "contact_email",
        "grievance_officer_name",
        "grievance_officer_email",
        "demo_request_retention",
        "governing_law",
        "terms_changes_notice",
    )

    class Meta:
        verbose_name = verbose_name_plural = "platform settings"

    def __str__(self) -> str:
        return "Platform settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> PlatformSettings:
        obj = cls.objects.filter(pk=1).first()
        return obj if obj is not None else cls(pk=1)

    def empty_legal_fields(self) -> list[str]:
        return [f for f in self.LEGAL_FIELDS if not (getattr(self, f) or "").strip()]
