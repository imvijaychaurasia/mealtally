# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from mealtally.common.country import normalize_phone
from mealtally.tenancy.models import TenantOwnedModel

from .managers import UserManager


class Role(models.TextChoices):
    OWNER = "OWNER", _("Owner")
    MANAGER = "MANAGER", _("Manager")
    STAFF = "STAFF", _("Counter")  # redeems meals and sells passes at the counter
    CHEF = "CHEF", _("Chef")  # Preview role: kitchen console only
    DRIVER = "DRIVER", _("Driver")  # Preview role: driver console only
    CUSTOMER = "CUSTOMER", _("Customer")


ROLE_RANK = {Role.OWNER: 6, Role.MANAGER: 5, Role.STAFF: 4, Role.CHEF: 3, Role.DRIVER: 2, Role.CUSTOMER: 1}
STAFF_ROLES = (Role.OWNER, Role.MANAGER, Role.STAFF)


class User(AbstractBaseUser, PermissionsMixin):
    """Global identity (not tenant-scoped). Sign in with ``email`` or ``phone_e164``.

    ``is_platform_admin`` is the *only* flag the application uses for platform
    authorisation. ``is_staff``/``is_superuser`` exist solely so Django's own
    machinery (admin login form, ``createsuperuser``) works.
    """

    email = models.EmailField("email address", unique=True, null=True, blank=True)
    phone_e164 = models.CharField("phone (E.164)", max_length=16, unique=True, null=True, blank=True)
    name = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, help_text="May open the Django admin login form.")
    is_platform_admin = models.BooleanField(default=False, help_text="Platform-wide (cross-tenant) administrator.")
    date_joined = models.DateTimeField(default=timezone.now)
    must_change_password = models.BooleanField(default=False)
    # chosen in the language picker; empty = the restaurant's default, then the browser's
    preferred_language = models.CharField(max_length=10, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(email__isnull=False) | Q(phone_e164__isnull=False),
                name="user_has_email_or_phone",
            ),
        ]

    def __str__(self) -> str:
        return self.name or self.get_username()

    def get_username(self) -> str:
        return self.email or self.phone_e164 or f"user-{self.pk}"

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower() if self.email and self.email.strip() else None
        self.phone_e164 = normalize_phone(self.phone_e164) if self.phone_e164 and self.phone_e164.strip() else None
        super().save(*args, **kwargs)


class Membership(TenantOwnedModel):
    """A user's role at one tenant. One person may be a customer at several tenants."""

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="memberships")
    role = models.CharField(max_length=10, choices=Role)
    is_active = models.BooleanField(default=True)
    # D03.9 (QA-01 P1-4): a DRIVER's own delivery route and vehicle (the owner reassigns on Delivery routes).
    route_name = models.CharField(max_length=60, blank=True)
    vehicle = models.CharField(max_length=60, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "tenant", "role"], name="uniq_membership_user_tenant_role"),
        ]
        indexes = [models.Index(fields=["tenant", "user"])]

    def __str__(self) -> str:
        return f"{self.user} @ {self.tenant_id} as {self.role}"
