# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

from django.db import transaction

from mealtally.common.country import normalize_phone
from mealtally.common.errors import NotFound

from .models import ROLE_RANK
from .models import Membership
from .models import Role
from .models import User


def get_or_create_phone_user(*, phone: str, name: str = "") -> User:
    """Global identity for a customer: re-used if that phone already exists (other tenant / staff)."""
    phone = normalize_phone(phone)
    user = User.objects.filter(phone_e164=phone).first()
    if user is None:
        user = User.objects.create_user(phone_e164=phone, name=name)
    return user


def ensure_membership(*, user: User, tenant_id: int, role: str) -> Membership:
    membership, created = Membership.objects.get_or_create(user=user, tenant_id=tenant_id, role=role)
    if not created and not membership.is_active:
        membership.is_active = True
        membership.save(update_fields=["is_active", "updated_at"])
    return membership


def active_roles(*, user: User, tenant_id: int) -> list[str]:
    return list(
        Membership.objects.filter(user=user, tenant_id=tenant_id, is_active=True).values_list("role", flat=True)
    )


def effective_role(roles: list[str]) -> str | None:
    """Highest-ranking role among a user's active memberships at one tenant."""
    valid = [r for r in roles if r in ROLE_RANK]
    return max(valid, key=lambda r: ROLE_RANK[r]) if valid else None


def create_staff_user(
    *, tenant_id: int, role: str, email: str | None = None, phone: str | None = None, password: str, name: str = ""
) -> User:
    """Create (or extend) a staff/manager/owner login for a tenant."""
    if role == Role.CUSTOMER:
        raise ValueError("Use customers.services for customers.")
    with transaction.atomic():
        user = None
        if email:
            user = User.objects.filter(email__iexact=email).first()
        if user is None and phone:
            user = User.objects.filter(phone_e164=normalize_phone(phone)).first()
        if user is None:
            user = User.objects.create_user(email=email, phone_e164=phone, password=password, name=name)
        ensure_membership(user=user, tenant_id=tenant_id, role=role)
    return user


def get_user_or_404(pk: int) -> User:
    try:
        return User.objects.get(pk=pk)
    except User.DoesNotExist as exc:
        raise NotFound("User not found.") from exc


# --- passwords, staff management -------------------------------------------------------------
import secrets  # noqa: E402

from django.contrib.auth.password_validation import validate_password  # noqa: E402
from django.core.exceptions import ValidationError as DjangoValidationError  # noqa: E402

from mealtally.audit import services as audit  # noqa: E402
from mealtally.common.errors import AuthFailed  # noqa: E402
from mealtally.common.errors import ValidationFailed  # noqa: E402

from .policy import Action  # noqa: E402
from .policy import Actor  # noqa: E402
from .policy import require  # noqa: E402


def temp_password() -> str:
    return secrets.token_urlsafe(12)


def change_password(*, user: User, old_password: str, new_password: str) -> User:
    """Used for forced first-login changes and voluntary ones. Django validators (min 10) apply."""
    if not user.check_password(old_password):
        raise AuthFailed("Your current password is incorrect.")
    if old_password == new_password:
        raise ValidationFailed("Choose a different password.", details={"field": "new_password"})
    try:
        validate_password(new_password, user)
    except DjangoValidationError as exc:
        raise ValidationFailed(" ".join(exc.messages), details={"field": "new_password"}) from exc
    user.set_password(new_password)
    user.must_change_password = False
    user.save(update_fields=["password", "must_change_password"])
    return user


def list_staff(tenant_id: int):
    return (
        Membership.objects.filter(tenant_id=tenant_id)
        .exclude(role=Role.CUSTOMER)
        .select_related("user")
        .order_by("role", "id")
    )


def add_staff_member(*, actor: Actor, name: str, email: str | None, phone: str | None, role: str) -> tuple[User, str]:
    """OWNER adds a MANAGER/STAFF with a one-time temporary password (must change at first login)."""
    require(actor, Action.MANAGE_STAFF)
    if role not in (Role.MANAGER, Role.STAFF):
        raise ValidationFailed("Role must be MANAGER or STAFF.", details={"field": "role"})
    if not (email or phone):
        raise ValidationFailed("An email or a phone number is required.", details={"field": "email"})
    if (email and User.objects.filter(email__iexact=email).exists()) or (
        phone and User.objects.filter(phone_e164=normalize_phone(phone)).exists()
    ):
        raise ValidationFailed("A user with this email or phone already exists.", details={"field": "email"})
    password = temp_password()
    user = create_staff_user(
        tenant_id=actor.tenant_id, role=role, email=email or None, phone=phone or None, password=password, name=name
    )
    user.must_change_password = True
    user.save(update_fields=["must_change_password"])
    audit.record(
        action="staff.add",
        tenant_id=actor.tenant_id,
        actor=actor.user,
        object_type="user",
        after={"user": user.pk, "role": role},
    )
    return user, password


def set_staff_active(*, actor: Actor, user_id: int, active: bool) -> Membership:
    require(actor, Action.MANAGE_STAFF)
    membership = (
        Membership.objects.filter(tenant_id=actor.tenant_id, user_id=user_id).exclude(role=Role.CUSTOMER).first()
    )
    if membership is None:
        raise NotFound("Staff member not found.")
    if membership.role == Role.OWNER and not active:
        raise ValidationFailed("The owner cannot be deactivated.")
    membership.is_active = active
    membership.save(update_fields=["is_active", "updated_at"])
    audit.record(
        action="staff.activate" if active else "staff.deactivate",
        tenant_id=actor.tenant_id,
        actor=actor.user,
        object_type="user",
        after={"user": user_id},
    )
    return membership


def reset_staff_password(*, actor: Actor, user_id: int) -> tuple[User, str]:
    require(actor, Action.MANAGE_STAFF)
    membership = (
        Membership.objects.filter(tenant_id=actor.tenant_id, user_id=user_id)
        .exclude(role=Role.CUSTOMER)
        .select_related("user")
        .first()
    )
    if membership is None:
        raise NotFound("Staff member not found.")
    password = temp_password()
    user = membership.user
    user.set_password(password)
    user.must_change_password = True
    user.save(update_fields=["password", "must_change_password"])
    audit.record(
        action="staff.reset_password",
        tenant_id=actor.tenant_id,
        actor=actor.user,
        object_type="user",
        after={"user": user.pk},
    )
    return user, password
