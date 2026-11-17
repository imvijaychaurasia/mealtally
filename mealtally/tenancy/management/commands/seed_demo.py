# SPDX-License-Identifier: AGPL-3.0-only
"""Pilot reseed (D02 section 9): rename the pilot's display name and add 5 demo customers in different pass states.

Idempotent. Demo PINs are generated and printed ONCE (customers must change them at first login).
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.utils import timezone

from mealtally.accounts.models import Membership
from mealtally.accounts.models import Role
from mealtally.accounts.policy import Actor
from mealtally.billing import services as billing
from mealtally.customers import services as customers
from mealtally.customers.models import Customer
from mealtally.ledger import services as ledger
from mealtally.passes import services as passes
from mealtally.passes.models import Pass
from mealtally.plans.models import Plan
from mealtally.tenancy import services as tenancy
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.context import tenant_context
from mealtally.tenancy.models import Tenant

DEMO = (
    ("Demo Fresh", "+919000000001"),
    ("Demo Mid-use", "+919000000002"),
    ("Demo Near expiry", "+919000000003"),
    ("Demo Expired", "+919000000004"),
    ("Demo Queued", "+919000000005"),
)


class Command(BaseCommand):
    help = "Rename the pilot tenant's display name and add 5 demo customers with passes in different states."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="pilot-tiffin")
        parser.add_argument("--display-name", default="Pilot Tiffin (test)")

    def handle(self, *args, **opts):
        with platform_context():
            tenant = Tenant.objects.filter(slug=opts["slug"]).first()
            if tenant is None:
                raise CommandError("Unknown tenant.")
            owner = (
                Membership.objects.filter(tenant=tenant, role=Role.OWNER, is_active=True).select_related("user").first()
            )
            if owner is None:
                raise CommandError("The tenant has no owner.")
        with tenant_context(tenant.id):
            current = tenancy.get_settings(tenant.id)
            tenancy.update_settings(
                actor=Actor(user=owner.user, role=Role.OWNER, tenant_id=tenant.id),
                display_name=opts["display_name"],
                # dummy contact details so receipts are reviewed with real-looking content (D02.1 #23)
                address=current.address or "12 MG Road, Indiranagar, Bengaluru 560038",
                contact_phone=current.contact_phone or "+91 80 4000 0000",
            )
            actor = Actor(user=owner.user, role=Role.OWNER, tenant_id=tenant.id)
            plan = Plan.objects.filter(name="Monthly Meal Pass", is_active=True).first()
            now = timezone.now()
            self.stdout.write(f"Display name -> {opts['display_name']}")
            for name, phone in DEMO:
                if Customer.objects.filter(phone_e164=phone).exists():
                    self.stdout.write(f"{name}: already exists")
                    continue
                customer, pin = customers.create_customer(actor=actor, full_name=name, phone=phone)
                self._build(actor, customer, plan, name, now)
                self.stdout.write(
                    self.style.WARNING(f"DEMO CREDENTIALS (shown once)  {name}  phone={phone}  pin={pin}")
                )
        self.stdout.write(self.style.SUCCESS("seed_demo done."))

    def _redeem(self, actor, customer, n, start, spacing_hours=20):
        for i in range(n):
            at = start + timedelta(hours=spacing_hours * (i + 1))
            ledger.redeem(
                actor=actor,
                customer=customer,
                idempotency_key=f"demo:{customer.customer_code}:{i}",
                source="STAFF_SEARCH",
                confirm_additional=True,
                now=at,
            )

    def _buy(self, actor, customer, plan, at):
        return billing.record_payment(
            actor=actor,
            customer_public_id=customer.public_id,
            plan_public_id=plan.public_id,
            amount_minor=plan.price_minor,
            method="CASH",
            now=at,
            received_at=at,
        )

    def _build(self, actor, customer, plan, name, now):
        if name == "Demo Fresh":
            self._buy(actor, customer, plan, now - timedelta(minutes=5))
        elif name == "Demo Mid-use":
            start = now - timedelta(days=10)
            self._buy(actor, customer, plan, start)
            self._redeem(actor, customer, 12, start, spacing_hours=19)
        elif name == "Demo Near expiry":
            start = now - timedelta(days=28)
            self._buy(actor, customer, plan, start)
            self._redeem(actor, customer, 27, start, spacing_hours=24)
        elif name == "Demo Expired":
            start = now - timedelta(days=45)
            rec = self._buy(actor, customer, plan, start)
            self._redeem(actor, customer, 10, start, spacing_hours=24)
            passes.expire(Pass.objects.get(pk=rec.pass_.pk), now=rec.pass_.ends_at + timedelta(minutes=5))
        elif name == "Demo Queued":
            start = now - timedelta(days=3)
            self._buy(actor, customer, plan, start)
            self._redeem(actor, customer, 4, start, spacing_hours=15)
            self._buy(actor, customer, plan, now - timedelta(minutes=1))
