"""D03.9 §D3: rotate a tenant's logins -- every staff member gets a new random password (and must change it at the next
login); the customers named with ``--customer-phone`` get a new PIN (also must-change).

The new logins go to ``--out`` (mode 600, never printed). Every reset is audit-logged with the platform admin as actor.

    python manage.py rotate_tenant_credentials --slug pilot-tiffin --out /app/.pilot-credentials.txt \\
        --platform-admin admin@example.com --customer-phone +919999900001
"""

from __future__ import annotations

import os
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction

from mealtally.accounts import services as accounts
from mealtally.accounts.models import Role
from mealtally.accounts.models import User
from mealtally.accounts.policy import Actor
from mealtally.common.utils import normalize_phone
from mealtally.customers import services as customers
from mealtally.customers.models import Customer
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.context import tenant_context
from mealtally.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Force new random passwords for a tenant's staff (and new PINs for named customers); logins to a 600 file."

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True)
        parser.add_argument("--out", required=True, help="Credentials file to write (mode 600). Never printed.")
        parser.add_argument("--platform-admin", default="", help="Email of the platform admin recorded as actor.")
        parser.add_argument("--customer-phone", action="append", default=[], help="Rotate this customer's PIN too.")
        parser.add_argument("--customer-code", action="append", default=[], help="...or name the customer by code.")

    def handle(self, *args, **opts):
        with platform_context():
            tenant = Tenant.objects.filter(slug=opts["slug"]).first()
            admin = (
                User.objects.filter(email__iexact=opts["platform_admin"])
                if opts["platform_admin"]
                else User.objects.filter(is_platform_admin=True)
            ).first()
        if tenant is None:
            raise CommandError(f"No tenant '{opts['slug']}'.")
        if admin is None:
            raise CommandError("No platform admin to record as the actor.")
        # the platform admin acts with OWNER rights inside this one tenant (audit shows who really did it)
        actor = Actor(user=admin, role=Role.OWNER, tenant_id=tenant.id)
        base = f"/t/{tenant.slug}/login"
        lines = [f"# {tenant.slug} logins rotated (staff: {base}/staff ; customers: {base}/customer)"]
        with tenant_context(tenant.id), transaction.atomic():
            for m in accounts.list_staff(tenant.id).filter(is_active=True):
                user, password = accounts.reset_staff_password(actor=actor, user_id=m.user_id)
                lines.append(
                    f"{m.role}  login={user.get_username()}  password={password}  (must change at first login)"
                )
            wanted = [("phone", raw) for raw in opts["customer_phone"]] + [("code", c) for c in opts["customer_code"]]
            for kind, raw in wanted:
                lookup = {"phone_e164": normalize_phone(raw)} if kind == "phone" else {"customer_code": raw.upper()}
                customer = Customer.objects.filter(**lookup).first()
                if customer is None:
                    raise CommandError(f"No customer with {kind} {raw} at {tenant.slug}.")
                pin = customers.reset_pin(actor=actor, customer=customer)
                lines.append(f"CUSTOMER  {customer.full_name}  phone={customer.phone_e164}  pin={pin}  (must change)")
        fd = os.open(opts["out"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        Path(opts["out"]).chmod(0o600)
        staff = sum(1 for line in lines if "password=" in line)
        pins = sum(1 for line in lines if line.startswith("CUSTOMER"))
        self.stdout.write(
            f"Rotated {staff} staff password(s) and {pins} customer PIN(s); written to {opts['out']} (600)."
        )
