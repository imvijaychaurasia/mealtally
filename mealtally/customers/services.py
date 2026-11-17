from __future__ import annotations

import secrets

from django.contrib.auth.hashers import check_password
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db import transaction
from django.db.models import Q

from mealtally.accounts import services as accounts
from mealtally.accounts.models import Role
from mealtally.accounts.policy import Action
from mealtally.accounts.policy import Actor
from mealtally.accounts.policy import require
from mealtally.audit import services as audit
from mealtally.common.country import normalize_phone
from mealtally.common.errors import NotAllowed
from mealtally.common.errors import NotFound
from mealtally.common.errors import ValidationFailed
from mealtally.tenancy import services as tenancy
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.context import tenant_context
from mealtally.tenancy.models import Tenant

from .models import Customer

_DUMMY_PIN_HASH = make_password("000000")


def validate_pin(pin: str, length: int) -> str:
    pin = (pin or "").strip()
    if not (pin.isdigit() and len(pin) == length):
        raise ValidationFailed(f"The PIN must be exactly {length} digits.", details={"field": "pin"})
    if len(set(pin)) == 1:
        raise ValidationFailed("Choose a PIN that is not all the same digit.", details={"field": "pin"})
    return pin


def generate_pin(length: int = 6) -> str:
    return f"{secrets.randbelow(10**length):0{length}d}"


def create_customer(
    *, actor: Actor, full_name: str, phone: str, notes: str = "", pin: str | None = None
) -> tuple[Customer, str]:
    """Create a customer (+ login identity + CUSTOMER membership). Returns ``(customer, initial_pin)``."""
    require(actor, Action.CREATE_CUSTOMER)
    full_name = (full_name or "").strip()
    if not full_name:
        raise ValidationFailed("Name is required.", details={"field": "full_name"})
    phone = normalize_phone(phone)
    if Customer.objects.filter(phone_e164=phone).exists():
        raise ValidationFailed("A customer with this phone already exists.", details={"field": "phone"})
    settings_row = tenancy.get_settings(actor.tenant_id)
    pin = validate_pin(pin, settings_row.customer_pin_length) if pin else generate_pin(settings_row.customer_pin_length)
    try:
        with transaction.atomic():
            user = accounts.get_or_create_phone_user(phone=phone, name=full_name)
            accounts.ensure_membership(user=user, tenant_id=actor.tenant_id, role=Role.CUSTOMER)
            customer = Customer.objects.create(
                tenant_id=actor.tenant_id,
                user=user,
                customer_code=tenancy.next_customer_code(actor.tenant_id),
                full_name=full_name,
                phone_e164=phone,
                notes=notes,
                pin_hash=make_password(pin),
                must_change_pin=True,
            )
    except IntegrityError as exc:
        raise ValidationFailed("This customer already exists.", details={"field": "phone"}) from exc
    audit.record(
        action="customer.create",
        tenant_id=actor.tenant_id,
        actor=actor.user,
        object_type="customer",
        object_public_id=customer.public_id,
        after={"customer_code": customer.customer_code, "phone": phone},
    )
    return customer, pin


def reset_pin(*, actor: Actor, customer: Customer, pin: str | None = None) -> str:
    require(actor, Action.EDIT_CUSTOMER)
    settings_row = tenancy.get_settings(actor.tenant_id)
    pin = validate_pin(pin, settings_row.customer_pin_length) if pin else generate_pin(settings_row.customer_pin_length)
    customer.pin_hash = make_password(pin)
    customer.must_change_pin = True
    customer.save(update_fields=["pin_hash", "must_change_pin", "updated_at"])
    audit.record(
        action="customer.reset_pin",
        tenant_id=actor.tenant_id,
        actor=actor.user,
        object_type="customer",
        object_public_id=customer.public_id,
    )
    return pin


def set_status(*, actor: Actor, customer: Customer, status: str, reason: str = "") -> Customer:
    require(actor, Action.BLOCK_CUSTOMER)
    if status not in Customer.Status.values:
        raise ValidationFailed("Unknown status.")
    before = customer.status
    customer.status = status
    customer.save(update_fields=["status", "updated_at"])
    audit.record(
        action="customer.set_status",
        tenant_id=actor.tenant_id,
        actor=actor.user,
        object_type="customer",
        object_public_id=customer.public_id,
        before={"status": before},
        after={"status": status, "reason": reason},
    )
    return customer


def update_own_name(*, customer: Customer, full_name: str, address: str | None = None) -> Customer:
    """A customer may change their own name and (D03.9) delivery address -- nothing else."""
    full_name = (full_name or "").strip()
    if not full_name:
        raise ValidationFailed("Name is required.", details={"field": "full_name"})
    before = {"full_name": customer.full_name, "address": customer.address}
    customer.full_name = full_name
    if address is not None:
        customer.address = _clean_address(address)
    customer.save(update_fields=["full_name", "address", "updated_at"])
    audit.record(
        action="customer.update_own_name",
        tenant_id=customer.tenant_id,
        actor=customer.user,
        object_type="customer",
        object_public_id=customer.public_id,
        before=before,
        after={"full_name": full_name, "address": customer.address},
    )
    return customer


def get_customer(public_id, *, lock: bool = False) -> Customer:
    qs = Customer.objects.select_related("user")
    if lock:
        qs = qs.select_for_update()
    try:
        return qs.get(public_id=public_id)
    except (Customer.DoesNotExist, ValueError, TypeError, DjangoValidationError) as exc:
        raise NotFound("Customer not found.") from exc


def get_customer_for_user(*, user, tenant_id: int) -> Customer:
    customer = Customer.objects.filter(user=user, tenant_id=tenant_id).first()
    if customer is None:
        raise NotFound("No customer profile for this account at this tenant.")
    return customer


def search(query: str, *, limit: int = 25):
    """Search by phone (any fragment of digits), customer code, or name."""
    query = (query or "").strip()
    qs = Customer.objects.order_by("full_name", "id")
    if not query:
        return qs[:limit]
    cond = Q(customer_code__istartswith=query) | Q(full_name__icontains=query)
    digits = "".join(ch for ch in query if ch.isdigit())
    if len(digits) >= 3:  # noqa: PLR2004
        cond |= Q(phone_e164__contains=digits)
    return qs.filter(cond)[:limit]


def verify_pin(*, tenant_slug: str, phone: str, pin: str):
    """Customer login check. Returns the User on success, else None. Constant-ish time."""
    user = None
    try:
        phone = normalize_phone(phone)
    except ValidationFailed:
        check_password(pin, _DUMMY_PIN_HASH)
        return None
    with platform_context():
        tenant = Tenant.objects.filter(slug=tenant_slug).first()
    if tenant is None or tenant.status != Tenant.Status.ACTIVE:
        check_password(pin, _DUMMY_PIN_HASH)
        return None
    with tenant_context(tenant.id):
        customer = Customer.objects.select_related("user").filter(phone_e164=phone).first()
        if customer is None or not customer.pin_hash:
            check_password(pin, _DUMMY_PIN_HASH)
        elif check_password(pin, customer.pin_hash) and customer.status == Customer.Status.ACTIVE:
            if customer.user.is_active:
                user = customer.user
    return user


# --- D02 ------------------------------------------------------------------------------------------
from datetime import timedelta  # noqa: E402

from django.db.models import Count  # noqa: E402
from django.db.models import Exists  # noqa: E402
from django.db.models import OuterRef  # noqa: E402
from django.db.models import Subquery  # noqa: E402
from django.db.models.functions import Coalesce  # noqa: E402
from django.utils import timezone  # noqa: E402

from mealtally.passes.models import Pass  # noqa: E402


def change_pin(*, customer: Customer, old_pin: str, new_pin: str, verified: bool = False) -> Customer:
    """``verified=True``: the caller just authenticated this customer with their PIN (forced first-login change)."""
    if not verified and not check_password(old_pin, customer.pin_hash):
        raise ValidationFailed("Your current PIN is incorrect.", details={"field": "old_pin"})
    length = tenancy.get_settings(customer.tenant_id).customer_pin_length
    new_pin = validate_pin(new_pin, length)
    if (new_pin == old_pin) or (verified and check_password(new_pin, customer.pin_hash)):
        raise ValidationFailed("Choose a different PIN.", details={"field": "new_pin"})
    customer.pin_hash = make_password(new_pin)
    customer.must_change_pin = False
    customer.save(update_fields=["pin_hash", "must_change_pin", "updated_at"])
    audit.record(
        action="customer.change_pin",
        tenant_id=customer.tenant_id,
        actor=customer.user,
        object_type="customer",
        object_public_id=customer.public_id,
    )
    return customer


def update_customer(
    *, actor: Actor, customer: Customer, full_name: str, notes: str = "", address: str | None = None
) -> Customer:
    """Staff/manager/owner edit. ``address`` (D03.9 QA-01 P1-5) is left unchanged when None."""
    require(actor, Action.EDIT_CUSTOMER)
    full_name = (full_name or "").strip()
    if not full_name:
        raise ValidationFailed("Name is required.", details={"field": "full_name"})
    before = {"full_name": customer.full_name, "notes": customer.notes, "address": customer.address}
    customer.full_name, customer.notes = full_name, notes
    if address is not None:
        customer.address = _clean_address(address)
    customer.save(update_fields=["full_name", "notes", "address", "updated_at"])
    audit.record(
        action="customer.update",
        tenant_id=actor.tenant_id,
        actor=actor.user,
        object_type="customer",
        object_public_id=customer.public_id,
        before=before,
        after={"full_name": full_name, "notes": notes, "address": customer.address},
    )
    return customer


def _clean_address(address: str) -> str:
    address = " ".join((address or "").split())  # one line, single spaces
    if len(address) > 300:  # noqa: PLR2004
        raise ValidationFailed("Keep the address under 300 characters.", details={"field": "address"})
    return address


def self_signup(*, tenant_id: int, full_name: str, phone: str, pin: str) -> Customer:
    """Public sign-up (only when the tenant enabled it): ACTIVE customer, no pass; pays at the counter."""
    row = tenancy.get_settings(tenant_id)
    if not row.allow_self_signup:
        raise NotAllowed("Self sign-up is not enabled for this restaurant.")
    full_name = (full_name or "").strip()
    if not full_name:
        raise ValidationFailed("Name is required.", details={"field": "full_name"})
    phone = normalize_phone(phone)
    pin = validate_pin(pin, row.customer_pin_length)
    if Customer.objects.filter(phone_e164=phone).exists():
        raise ValidationFailed("This phone number is already registered. Please log in.", details={"field": "phone"})
    with transaction.atomic():
        user = accounts.get_or_create_phone_user(phone=phone, name=full_name)
        accounts.ensure_membership(user=user, tenant_id=tenant_id, role=Role.CUSTOMER)
        customer = Customer.objects.create(
            tenant_id=tenant_id,
            user=user,
            customer_code=tenancy.next_customer_code(tenant_id),
            full_name=full_name,
            phone_e164=phone,
            pin_hash=make_password(pin),
            must_change_pin=False,
        )
    audit.record(
        action="customer.self_signup",
        tenant_id=tenant_id,
        actor=user,
        object_type="customer",
        object_public_id=customer.public_id,
    )
    return customer


def list_customers(*, query: str = "", status: str = "", limit: int = 100):
    """Admin list. status: '' | active_pass | no_pass | expiring | blocked."""
    now = timezone.now()
    live = Pass.objects.filter(customer_id=OuterRef("pk"), status=Pass.Status.ACTIVE)
    queued = Pass.objects.filter(customer_id=OuterRef("pk"), status=Pass.Status.QUEUED).order_by().values("customer_id")
    qs = Customer.objects.annotate(
        has_active=Exists(live),
        has_expiring=Exists(live.filter(ends_at__lte=now + timedelta(days=3))),
        active_meals=Subquery(live.values("meals_remaining")[:1]),
        active_ends=Subquery(live.values("ends_at")[:1]),
        queued_count=Coalesce(Subquery(queued.annotate(n=Count("id")).values("n")[:1]), 0),
    )
    if status == "active_pass":
        qs = qs.filter(has_active=True)
    elif status == "no_pass":
        qs = qs.filter(has_active=False)
    elif status == "expiring":
        qs = qs.filter(has_expiring=True)
    elif status == "blocked":
        qs = qs.filter(status=Customer.Status.BLOCKED)
    query = (query or "").strip()
    if query:
        digits = "".join(ch for ch in query if ch.isdigit())
        cond = Q(customer_code__istartswith=query) | Q(full_name__icontains=query)
        if len(digits) >= 3:  # noqa: PLR2004
            cond |= Q(phone_e164__contains=digits)
        qs = qs.filter(cond)
    return qs.order_by("full_name", "id")[:limit]
