"""Tenant lifecycle. These functions run in (and open) platform context themselves."""

from __future__ import annotations

from django.db import transaction

from mealtally.audit import services as audit
from mealtally.common.errors import NotFound
from mealtally.common.errors import ValidationFailed

from .context import platform_context
from .models import Tenant
from .models import TenantSettings


def ensure_defaults(tenant: Tenant, *, actor=None) -> None:
    """Make sure settings, a default fee policy and the default meal slots exist (idempotent)."""
    from mealtally.billing import services as billing  # noqa: PLC0415
    from mealtally.plans import meal_rules  # noqa: PLC0415

    with platform_context():
        TenantSettings.objects.get_or_create(tenant=tenant)
        billing.ensure_default_fee_policy(tenant_id=tenant.id)
        meal_rules.ensure_default_slots(tenant.id)


def create_tenant(*, name: str, slug: str, timezone: str = "Asia/Kolkata", actor=None) -> Tenant:
    with platform_context(), transaction.atomic():
        if Tenant.objects.filter(slug=slug).exists():
            raise ValidationFailed("A tenant with this slug already exists.", details={"field": "slug"})
        tenant = Tenant(name=name, slug=slug, timezone=timezone)
        tenant.full_clean()
        tenant.save()
        ensure_defaults(tenant)
        audit.record(
            action="tenant.create",
            tenant_id=tenant.id,
            actor=actor,
            object_type="tenant",
            object_public_id=tenant.public_id,
            after={"slug": tenant.slug, "timezone": tenant.timezone},
        )
    return tenant


def get_tenant_by_slug(slug: str) -> Tenant:
    with platform_context():
        tenant = Tenant.objects.filter(slug=slug).first()
    if tenant is None:
        raise NotFound("Tenant not found.")
    return tenant


def set_status(*, tenant: Tenant, status: str, actor=None, reason: str = "") -> Tenant:
    if status not in Tenant.Status.values:
        raise ValidationFailed("Unknown tenant status.")
    with platform_context(), transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
        before = tenant.status
        tenant.status = status
        tenant.save(update_fields=["status", "updated_at"])
        audit.record(
            action="tenant.set_status",
            tenant_id=tenant.id,
            actor=actor,
            object_type="tenant",
            object_public_id=tenant.public_id,
            before={"status": before},
            after={"status": status, "reason": reason},
        )
    return tenant


def list_tenant_ids() -> list[int]:
    """All tenant ids (any status): expiry/reconciliation must run for suspended tenants too."""
    with platform_context():
        return list(Tenant.objects.order_by("id").values_list("id", flat=True))


def next_customer_code(tenant_id: int) -> str:
    """Allocate C0001, C0002, ... safely under concurrency (row lock on the settings row)."""
    with transaction.atomic():
        settings_row = TenantSettings.objects.select_for_update().get(tenant_id=tenant_id)
        number = settings_row.next_customer_number
        settings_row.next_customer_number = number + 1
        settings_row.save(update_fields=["next_customer_number", "updated_at"])
    return f"C{number:04d}"


def get_settings(tenant_id: int) -> TenantSettings:
    return TenantSettings.objects.get(tenant_id=tenant_id)


# --- D02 -------------------------------------------------------------------------------------------
import re  # noqa: E402

from mealtally.accounts.policy import Action  # noqa: E402
from mealtally.accounts.policy import Actor  # noqa: E402
from mealtally.accounts.policy import require  # noqa: E402


def next_receipt_number(tenant_id: int) -> str:
    """R-000001, R-000002, ... per tenant. Allocated under SELECT ... FOR UPDATE: no duplicates, no gaps on rollback."""
    with transaction.atomic():
        row = TenantSettings.objects.select_for_update().get(tenant_id=tenant_id)
        number = row.next_receipt_number
        row.next_receipt_number = number + 1
        row.save(update_fields=["next_receipt_number", "updated_at"])
    return f"R-{number:06d}"


_SETTINGS_FIELDS = {
    "display_name": str,
    "address": str,
    "contact_phone": str,
    "brand_color": str,
    "receipt_footer": str,
    "tax_id": str,
    "food_licence_no": str,
    "tagline": str,
    "redeem_cooldown_seconds": int,
    "staff_reversal_window_hours": int,
    "max_queued_passes": int,
    "allow_self_signup": bool,
    "counter_can_reverse_others": bool,  # D03.9 §A1
    "topup_min_minor": int,  # D03.9 QA-01 P1-6
    "topup_max_minor": int,
    "meal_rules_banner_dismissed": bool,  # D03.9 §B6
}


def update_settings(
    *,
    actor: Actor,
    timezone_name: str | None = None,
    country: str | None = None,
    currency: str | None = None,
    **data,
) -> TenantSettings:
    """OWNER only. Validates and audits; also changes the restaurant's timezone, country and currency when given.

    Changing the currency does not convert existing amounts: they keep their minor units, so do it before selling.
    """
    from zoneinfo import ZoneInfo  # noqa: PLC0415
    from zoneinfo import ZoneInfoNotFoundError  # noqa: PLC0415

    from .models import validate_country  # noqa: PLC0415
    from .models import validate_currency  # noqa: PLC0415

    require(actor, Action.MANAGE_SETTINGS)
    row = TenantSettings.objects.select_for_update().get(tenant_id=actor.tenant_id)
    tenant = Tenant.objects.get(pk=actor.tenant_id)
    tenant_before = {"timezone": tenant.timezone, "country": tenant.country, "currency": tenant.currency}
    for field, value, check in (("country", country, validate_country), ("currency", currency, validate_currency)):
        if value:
            try:
                check(value.upper())
            except Exception as exc:  # noqa: BLE001  (django ValidationError)
                raise ValidationFailed("Unknown code.", details={"field": field}) from exc
            setattr(tenant, field, value.upper())
    tenant_country = tenant.country
    before = {k: getattr(row, k) for k in _SETTINGS_FIELDS}
    for key, value in data.items():
        if key not in _SETTINGS_FIELDS:
            continue
        kind = _SETTINGS_FIELDS[key]
        if kind is int and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise ValidationFailed("Must be a whole number, zero or more.", details={"field": key})
        if key == "brand_color" and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(value)):
            raise ValidationFailed("Use a colour like #0f766e.", details={"field": key})
        if key == "max_queued_passes" and not 0 <= value <= 5:  # noqa: PLR2004
            raise ValidationFailed("Between 0 and 5.", details={"field": key})
        if key == "redeem_cooldown_seconds" and value > 3600:  # noqa: PLR2004
            raise ValidationFailed("At most 3600 seconds.", details={"field": key})
        if key == "tax_id" and value and tenant_country == "IN" and not re.fullmatch(r"[0-9A-Za-z]{15}", str(value)):
            raise ValidationFailed("A GSTIN has 15 letters and digits.", details={"field": key})
        setattr(row, key, value)
    if row.topup_min_minor < 1 or row.topup_max_minor <= row.topup_min_minor:
        raise ValidationFailed(
            "The largest top-up must be above the smallest (at least ₹1).", details={"field": "topup_max_minor"}
        )
    row.save()
    if timezone_name:
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValidationFailed("Unknown timezone.", details={"field": "timezone"}) from exc
        tenant.timezone = timezone_name
    tenant.save(update_fields=["timezone", "country", "currency", "updated_at"])
    audit.record(
        action="settings.update",
        tenant_id=actor.tenant_id,
        actor=actor.user,
        object_type="settings",
        object_public_id=row.public_id,
        before={**before, **tenant_before},
        after={
            **{k: getattr(row, k) for k in _SETTINGS_FIELDS},
            "timezone": tenant.timezone,
            "country": tenant.country,
            "currency": tenant.currency,
        },
    )
    return row


def set_theme(*, actor, tenant: Tenant, theme: str) -> Tenant:
    """Owner (or platform admin via Django admin) changes the restaurant's colour theme. Audited."""
    from mealtally.accounts.policy import Action  # noqa: PLC0415
    from mealtally.accounts.policy import require  # noqa: PLC0415

    if theme not in Tenant.Theme.values:
        raise ValidationFailed("Unknown theme.", details={"field": "theme"})
    require(actor, Action.MANAGE_SETTINGS)
    with platform_context(), transaction.atomic():
        row = Tenant.objects.select_for_update().get(pk=tenant.pk)
        before = row.theme
        if before != theme:
            row.theme = theme
            row.save(update_fields=["theme", "updated_at"])
            audit.record(
                action="tenant.set_theme",
                tenant_id=row.id,
                actor=actor.user,
                object_type="tenant",
                object_public_id=row.public_id,
                before={"theme": before},
                after={"theme": theme},
            )
    return row


def onboard_tenant(
    *,
    actor_user,
    name: str,
    slug: str,
    timezone_name: str,
    owner_name: str,
    owner_email: str | None,
    owner_phone: str | None = None,
    is_test: bool = False,
) -> tuple[Tenant, object, str]:
    """Platform admin: tenant, OWNER (temp password), default plan, fee policy and settings - atomically."""
    from mealtally.accounts import services as accounts  # noqa: PLC0415
    from mealtally.plans.models import Plan  # noqa: PLC0415

    with platform_context(), transaction.atomic():
        tenant = create_tenant(name=name, slug=slug, timezone=timezone_name, actor=actor_user)
        if is_test:
            tenant.is_test = True
            tenant.save(update_fields=["is_test", "updated_at"])
        row = TenantSettings.objects.get(tenant_id=tenant.id)
        row.display_name = name
        row.save(update_fields=["display_name", "updated_at"])
        password = accounts.temp_password()
        owner = accounts.create_staff_user(
            tenant_id=tenant.id,
            role="OWNER",
            email=owner_email or None,
            phone=owner_phone or None,
            password=password,
            name=owner_name,
        )
        owner.must_change_password = True
        owner.save(update_fields=["must_change_password"])
        Plan.objects.create(  # the reference plan every new restaurant starts from
            tenant_id=tenant.id,
            name="Monthly Meal Pass",
            price_minor=150000,
            meals_per_cycle=30,
            validity_mode=Plan.ValidityMode.ROLLING_DAYS,
            validity_days=30,
            max_meals_per_day=None,
        )
        audit.record(
            action="tenant.onboard",
            tenant_id=tenant.id,
            actor=actor_user,
            object_type="tenant",
            object_public_id=tenant.public_id,
            after={"owner": owner.pk},
        )
    return tenant, owner, password
