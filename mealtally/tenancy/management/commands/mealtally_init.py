# SPDX-License-Identifier: AGPL-3.0-only
"""First run (`make init`): the platform admin and, in single mode, the restaurant with the admin as its owner.

The admin's password is typed in (``--interactive``) or generated and printed once. Either way it must be changed at the
first login. Running it again changes nothing that already exists.
"""

from __future__ import annotations

import getpass
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.utils.text import slugify

from mealtally.accounts.models import Membership
from mealtally.accounts.models import Role
from mealtally.accounts.models import User
from mealtally.tenancy import services as tenancy
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.models import Tenant
from mealtally.tenancy.models import TenantSettings


class Command(BaseCommand):
    help = "Create the platform admin (and, in single mode, the restaurant). Safe to run again."

    def add_arguments(self, parser):
        parser.add_argument("--email", default="", help="Admin email (default: MEALTALLY_ADMIN_EMAIL).")
        parser.add_argument("--restaurant", default="", help="Restaurant name (default: MEALTALLY_RESTAURANT_NAME).")
        parser.add_argument("--interactive", action="store_true", help="Ask for the admin password.")

    def handle(self, *args, **opts):
        import os  # noqa: PLC0415

        email = (opts["email"] or os.environ.get("MEALTALLY_ADMIN_EMAIL", "")).strip().lower()
        if not email or "@" not in email:
            raise CommandError("Give the admin email with --email or MEALTALLY_ADMIN_EMAIL.")
        with platform_context(), transaction.atomic():
            admin = User.objects.filter(email=email).first()
            if admin is None:
                password = self._password(opts["interactive"])
                admin = User.objects.create_superuser(email=email, password=password, name="Admin")
                admin.must_change_password = True
                admin.save(update_fields=["must_change_password"])
                if not opts["interactive"]:
                    self.stdout.write(
                        f"Admin login: {email}\nPassword (shown once, change it at first login): {password}"
                    )
            else:
                self.stdout.write(f"Admin {email} already exists.")
            if settings.MEALTALLY_MODE == "single":
                self._restaurant(admin, opts["restaurant"] or os.environ.get("MEALTALLY_RESTAURANT_NAME", ""))
        self.stdout.write(f"Open {settings.MEALTALLY_BASE_URL}/ and sign in.")

    def _password(self, interactive: bool) -> str:
        if not interactive:
            return secrets.token_urlsafe(15)
        while True:
            first = getpass.getpass("Admin password (10+ characters): ")
            if len(first) < 10:  # noqa: PLR2004
                self.stderr.write("Too short.")
                continue
            if getpass.getpass("Again: ") == first:
                return first
            self.stderr.write("They don't match.")

    def _restaurant(self, admin: User, name: str) -> None:
        existing = Tenant.objects.exclude(status=Tenant.Status.DEACTIVATED).first()
        if existing is not None:
            self.stdout.write(f"Restaurant '{existing.name}' already exists.")
            return
        name = (name or "My Restaurant").strip()
        slug = slugify(name)[:40] or "restaurant"
        tenant = tenancy.create_tenant(name=name, slug=slug, timezone=settings.MEALTALLY_DEFAULT_TIMEZONE, actor=admin)
        TenantSettings.objects.filter(tenant_id=tenant.id).update(display_name=name)
        Membership.objects.get_or_create(user=admin, tenant=tenant, role=Role.OWNER)
        self.stdout.write(f"Restaurant '{name}' created; {admin.email} is its owner.")
