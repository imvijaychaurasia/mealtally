# SPDX-License-Identifier: AGPL-3.0-only
"""D03: create the demo tenant ``demo-tiffin`` ("Saffron Tiffins & Mess (Demo)") with REAL data through the real services.

Real: plans, 25 pass customers in mixed states, ~45 days of back-dated redemptions (with a few undos and one adjustment),
payments across Oct-Nov (cash + UPI with fake UTRs, one voided), and a staff roster. Preview data (orders, wallets, ...)
lives in ``mealtally.preview.data`` and is never written to the database.

Idempotent. Logins are generated and written ONLY to ``--credentials-file`` (mode 600); nothing secret is printed.
Demo users are created with ``must_change_password=False`` so the demo logins work first time.
"""

from __future__ import annotations

import os
import random
import re
from datetime import datetime
from datetime import time
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.utils import timezone

from mealtally.accounts import services as accounts
from mealtally.accounts.models import Role
from mealtally.accounts.models import User
from mealtally.accounts.policy import Actor
from mealtally.billing import services as billing
from mealtally.common.country import normalize_phone
from mealtally.customers import services as customers
from mealtally.customers.models import Customer
from mealtally.ledger import services as ledger
from mealtally.passes import services as passes
from mealtally.passes.models import Pass
from mealtally.plans.models import Plan
from mealtally.preview import data as pv
from mealtally.preview import personas
from mealtally.tenancy import services as tenancy
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.context import tenant_context
from mealtally.tenancy.models import Tenant
from mealtally.tenancy.models import TenantSettings

SLUG = "demo-tiffin"
NAME = "Saffron Tiffins & Mess (Demo)"
FAKE_FSSAI = "00000000000000"  # obviously fake; never a real licence number
IST = ZoneInfo("Asia/Kolkata")


def staff_rows(domain, persona=personas.DEFAULT):
    rows = [
        ("OWNER", Role.OWNER, f"owner@{domain}", "Sunita Kulkarni"),
        ("MANAGER", Role.MANAGER, f"manager@{domain}", "Prakash Joshi"),
        ("COUNTER 1", Role.STAFF, f"counter1@{domain}", "Seema Pawar"),
        ("COUNTER 2", Role.STAFF, f"counter2@{domain}", "Imran Shaikh"),
        ("CHEF", Role.CHEF, f"chef@{domain}", "Ganesh Bhosale"),
        ("DRIVER 1", Role.DRIVER, f"driver1@{domain}", "Ramesh Gawade"),
        ("DRIVER 2", Role.DRIVER, f"driver2@{domain}", "Sunil Bhor"),
    ]
    return [(a, b, c, personas.staff_name(persona, d)) for a, b, c, d in rows]


STAFF = staff_rows("saffrontiffins.example.com")


def _at(day, hh, mm):
    return timezone.make_aware(datetime.combine(day, time(hh, mm)), IST)


class Command(BaseCommand):
    help = "Create/refresh the demo-tiffin tenant (real pass data) for the D03 prospect demo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--credentials-file", default="", help="Where to write demo logins (mode 600). Required on first run."
        )
        parser.add_argument(
            "--platform-admin",
            default="",
            help="Email of the platform admin recorded as onboarder (default: first one).",
        )
        parser.add_argument("--slug", default=SLUG, help="Tenant slug (default demo-tiffin).")
        parser.add_argument(
            "--allow-shared",
            action="store_true",
            help="Create customers even when their phone numbers already belong to users of another tenant.",
        )
        parser.add_argument("--name", default=NAME, help="Business name.")
        parser.add_argument(
            "--domain", default="saffrontiffins.example.com", help="Email domain of the demo staff logins."
        )
        parser.add_argument(
            "--theme",
            default="",
            choices=["", "masala", "fresh", "tally"],
            help="D03.5: tenant theme (default: masala).",
        )
        parser.add_argument(
            "--ui-shell",
            default="",
            choices=["", "classic", "console"],
            help="D03.4: set the tenant's UI shell (default: leave as is).",
        )

    # ------------------------------------------------------------------------------------------------------------
    def handle(self, *args, **opts):
        self.slug, self.name = opts["slug"], opts["name"]
        self.persona = personas.persona_for(self.slug)
        self.salt = 500 if self.persona == "green" else 0  # a different ledger story per persona
        self.staff = staff_rows(opts["domain"], self.persona)
        with platform_context():
            tenant = Tenant.objects.filter(slug=self.slug).first()
        if tenant is not None:
            self.stdout.write("demo-tiffin already exists; making sure the flags are set.")
            self._flags(tenant, opts)
            with platform_context():  # D03.1: refresh demo-only data fixes (no schema change)
                TenantSettings.objects.filter(tenant_id=tenant.id).update(food_licence_no=FAKE_FSSAI)
                for (
                    _label,
                    _role,
                    email,
                    name,
                ) in self.staff:  # D03.2: plain display names (the header already shows the role)
                    User.objects.filter(email=email).update(name=name)
            self._refresh_persona(tenant, opts)
            self._d039_roster(tenant)
            return
        creds_path = opts["credentials_file"]
        if not opts["allow_shared"]:
            self._refuse_shared_phones()
        with platform_context():
            admin = (
                User.objects.filter(email__iexact=opts["platform_admin"])
                if opts["platform_admin"]
                else User.objects.filter(is_platform_admin=True)
            ).first()
        if admin is None:
            raise CommandError("No platform admin found to record as onboarder.")
        tenant, owner, password = tenancy.onboard_tenant(
            actor_user=admin,
            name=self.name,
            slug=self.slug,
            timezone_name="Asia/Kolkata",
            owner_name=self.staff[0][3],
            owner_email=self.staff[0][2],
            is_test=True,
        )
        creds = [f"OWNER  login={self.staff[0][2]}  password={password}"]
        with platform_context():
            owner.must_change_password = False
            owner.save(update_fields=["must_change_password"])
            for label, role, email, name in self.staff[1:]:
                pw = accounts.temp_password()
                user = accounts.create_staff_user(tenant_id=tenant.id, role=role, email=email, password=pw, name=name)
                user.must_change_password = False
                user.save(update_fields=["must_change_password"])
                creds.append(f"{label}  login={email}  password={pw}")
        self._flags(tenant, opts)
        owner_actor = Actor(user=owner, role=Role.OWNER, tenant_id=tenant.id)
        with tenant_context(tenant.id):
            tenancy.update_settings(
                actor=owner_actor,
                display_name=self.name,
                brand_color="#c2410c",
                address=personas.GREEN_ADDRESS if self.persona == "green" else personas.OLD_ADDRESS,
                contact_phone=personas.GREEN_PHONE if self.persona == "green" else "+91 20 4000 1101",
                receipt_footer="Thank you — see you tomorrow!",
                food_licence_no=FAKE_FSSAI,
            )
            lunch = self._plans(tenant)
            creds += self._customers(tenant, owner, owner_actor, lunch)
        self._d039_roster(tenant)
        if creds_path:
            fd = os.open(creds_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(
                    f"# {self.slug} logins (staff: /t/{self.slug}/login/staff ; customers: /t/{self.slug}/login/customer)\n"
                )
                fh.write("\n".join(creds) + "\n")
            os.chmod(creds_path, 0o600)
            self.stdout.write(f"Credentials written to {creds_path} (mode 600).")
        self.stdout.write(self.style.SUCCESS("seed_demo_tiffin done."))

    def _refuse_shared_phones(self):
        """Users are one row per phone, so a second tenant on the same numbers would share users with the first."""
        fmt = personas.phone_format(self.persona)
        phones = [normalize_phone(fmt.format(n)) for n in range(1, len(personas.pass_names(self.persona)) + 1)]
        with platform_context():
            taken = User.objects.filter(phone_e164__in=phones, memberships__isnull=False).distinct().count()
        if taken:
            raise CommandError(
                f"{taken} of the {len(phones)} phone numbers for '{self.slug}' already belong to users of another tenant "
                "(users are one row per phone). Pick another persona or phone range, or pass --allow-shared."
            )

    def _refresh_persona(self, tenant, opts):
        """Existing non-default persona (demo-fresh): move customers/address to the persona's own identity, idempotently."""
        if self.persona == personas.DEFAULT:
            return
        fmt = personas.phone_format(self.persona)
        names = personas.pass_names(self.persona)
        with tenant_context(tenant.id):
            TenantSettings.objects.filter(tenant_id=tenant.id).update(
                address=personas.GREEN_ADDRESS, contact_phone=personas.GREEN_PHONE
            )
            for n, new in enumerate(names, start=1):
                old_phone = normalize_phone(pv.PASS_PHONE.format(n))
                new_phone = normalize_phone(fmt.format(n))
                c = Customer.objects.filter(phone_e164__in=[old_phone, new_phone]).first()
                if c is None:
                    continue
                Customer.objects.filter(pk=c.pk).update(full_name=new, phone_e164=new_phone)
                with platform_context():
                    User.objects.filter(pk=c.user_id).update(name=new, phone_e164=new_phone)
        path = Path(opts["credentials_file"]) if opts.get("credentials_file") else None
        if path and path.exists():
            lines = [
                f"# {self.slug} logins (staff: /t/{self.slug}/login/staff ; customers: /t/{self.slug}/login/customer)"
            ]
            for raw in path.read_text().splitlines()[1:]:
                m = re.match(r"CUSTOMER  (.+?)  phone=(\+91 \d{5} \d{5})  pin=(\S+)$", raw)
                n = int(m[2][-4:]) if m else 0
                lines.append(f"CUSTOMER  {names[n - 1]}  phone={fmt.format(n)}  pin={m[3]}" if m else raw)
            path.write_text("\n".join(lines) + "\n")
            path.chmod(0o600)

    # D03.9 --------------------------------------------------------------------------------------------------------
    AREAS = {
        "saffron": (
            ["Kothrud", "Karve Nagar", "Erandwane", "Warje", "Bavdhan"],
            ["Shivaji Society", "Om Residency", "Rutu Heights"],
        ),
        "green": (["Baner", "Balewadi", "Pashan", "Sus", "Aundh"], ["Lotus Court", "Palm Meadows", "Sky Vista"]),
    }
    ROUTES = {
        "saffron": (("Kothrud A", "MH12 AB 4021"), ("Kothrud B", "MH12 CD 7718")),
        "green": (("Baner A", "MH12 EF 3305"), ("Baner B", "MH12 GH 5512")),
    }

    def _d039_roster(self, tenant):
        """Idempotent D03.9 demo data (QA-01 P1-2..P1-5, §B6): wallets for about half the customers, customer addresses,
        a route + vehicle per driver, and explicit meal-time rules on the demo plans (also on passes already sold).
        Never touches the ledger; never overwrites an address, route or rule someone has already set."""
        from mealtally.accounts.models import Membership  # noqa: PLC0415
        from mealtally.plans import meal_rules  # noqa: PLC0415
        from mealtally.plans import services as plan_services  # noqa: PLC0415
        from mealtally.plans.models import MealSlot  # noqa: PLC0415

        key = "green" if self.persona == "green" else "saffron"
        areas, streets = self.AREAS[key]
        flip = 1 if key == "green" else 0  # a different half for each persona
        with tenant_context(tenant.id):
            meal_rules.ensure_default_slots(tenant.id)
            rows = list(Customer.objects.order_by("customer_code"))
            for n, c in enumerate(rows, start=1):
                changes = {"has_wallet": (n + flip) % 2 == 1}
                if not c.address:
                    changes["address"] = (
                        f"{(n * 7) % 48 + 2}, {streets[n % len(streets)]}, {areas[n % len(areas)]}, Pune"
                    )
                Customer.objects.filter(pk=c.pk).update(**changes)
            drivers = list(Membership.objects.filter(role=Role.DRIVER, tenant_id=tenant.id).order_by("id"))
            for m, (route, vehicle) in zip(drivers, self.ROUTES[key], strict=False):
                if not m.route_name:
                    Membership.objects.filter(pk=m.pk).update(route_name=route, vehicle=vehicle)
            slots = {s.name: s for s in MealSlot.objects.all()}
            # the e2e test tenant keeps rule-free plans so browser tests that redeem don't depend on the time of day
            for plan in Plan.objects.all() if self.persona != "e2e" else []:
                if plan.allowed_slots.exists():
                    continue
                wanted = ["Lunch", "Dinner"] if "Dinner" in plan.name else ["Lunch"]
                plan_services.set_allowed_slots(plan, [slots[w] for w in wanted if w in slots])
                plan.max_meals_per_slot = 1
                plan.save(update_fields=["max_meals_per_slot", "updated_at"])
                ids = sorted(plan.allowed_slots.values_list("id", flat=True))
                Pass.objects.filter(plan=plan, status__in=["ACTIVE", "QUEUED"], allowed_slot_ids=[]).update(
                    allowed_slot_ids=ids, max_meals_per_slot=1
                )
        self.stdout.write("D03.9 roster: wallets, addresses, driver routes and meal-time rules set.")

    def _flags(self, tenant, opts=None):
        with platform_context():
            Tenant.objects.filter(pk=tenant.pk).update(is_test=True, has_demo_dataset=True, show_preview_badges=True)
            if (opts or {}).get("ui_shell"):
                Tenant.objects.filter(pk=tenant.pk).update(ui_shell=opts["ui_shell"])
            if (opts or {}).get("theme"):
                Tenant.objects.filter(pk=tenant.pk).update(theme=opts["theme"])

    def _plans(self, tenant):
        base = Plan.objects.get(name="Monthly Meal Pass")
        green = self.persona == "green"
        base.name = "Monthly Bowl Pass — Lunch" if green else "Monthly Meal Pass — Lunch"
        if green:
            base.price_minor = 220000
        base.save(update_fields=["name", "price_minor", "updated_at"] if green else ["name", "updated_at"])
        ld = Plan.objects.create(
            tenant_id=tenant.id,
            name="Monthly Bowl Pass — Lunch + Dinner" if green else "Monthly Meal Pass — Lunch + Dinner",
            price_minor=340000 if green else 280000,
            meals_per_cycle=60,
            validity_mode=Plan.ValidityMode.ROLLING_DAYS,
            validity_days=30,
            max_meals_per_day=None,
        )
        trial = Plan.objects.create(
            tenant_id=tenant.id,
            name="Weekly Bowl Trial" if green else "Weekly Trial Pass",
            price_minor=52000 if green else 40000,
            meals_per_cycle=7,
            validity_mode=Plan.ValidityMode.ROLLING_DAYS,
            validity_days=7,
            max_meals_per_day=None,
        )
        self.plans = {"lunch": base, "ld": ld, "trial": trial}
        return base

    # ------------------------------------------------------------------------------------------------------------
    def _customers(self, tenant, owner, owner_actor, lunch):
        today = timezone.localdate()
        staff_users = [User.objects.get(email=r[2]) for r in self.staff[2:4]]
        staff = [Actor(user=u, role=Role.STAFF, tenant_id=tenant.id) for u in staff_users]
        lines = []
        for n, name in enumerate(personas.pass_names(self.persona), start=1):
            phone = personas.phone_format(self.persona).format(n)
            customer, pin = customers.create_customer(actor=owner_actor, full_name=name, phone=phone)
            Customer.objects.filter(pk=customer.pk).update(must_change_pin=False)
            lines.append(f"CUSTOMER  {name}  phone={phone}  pin={pin}")
            self._pass_story(n, customer, owner_actor, staff, today)
        return lines

    def _plan_for(self, n):
        if self.persona == "green":
            if n in (4, 8, 11, 15, 19):
                return self.plans["ld"]
            if n in (2, 3, 24):
                return self.plans["trial"]
            return self.plans["lunch"]
        if n in (5, 6, 9, 13, 17):
            return self.plans["ld"]
        if n in (3, 4, 24):
            return self.plans["trial"]
        return self.plans["lunch"]

    def _buy(self, actor, customer, plan, when, n, k=0):
        upi = n % 2 == 0
        return billing.record_payment(
            actor=actor,
            customer_public_id=customer.public_id,
            plan_public_id=plan.public_id,
            amount_minor=plan.price_minor,
            method="UPI_MANUAL" if upi else "CASH",
            reference=f"{random.Random(n * 31 + k + self.salt).randrange(10**11, 10**12)}" if upi else "",
            now=when,
            received_at=when,
        )

    def _redeem_series(self, staff, customer, start_day, meals, per_day, *, n, undo_at=()):
        """Redeem ``meals`` meals from ``start_day`` on, lunch (and dinner when per_day == 2), skipping an occasional day."""
        rng = random.Random(n + self.salt)
        done, day, i = 0, start_day, 0
        while done < meals:
            day_meals = per_day
            if rng.random() < 0.1:  # an occasional skipped day
                day += timedelta(days=1)
                continue
            for slot in range(day_meals):
                if done >= meals:
                    break
                at = _at(day, 12 + 0 if slot == 0 else 20, rng.randint(5, 55))
                if at > timezone.now() - timedelta(minutes=30):
                    return done
                actor = staff[(done + n) % 2]
                res = ledger.redeem(
                    actor=actor,
                    customer=customer,
                    idempotency_key=f"d03:{customer.customer_code}:{i}",
                    source="QR_SCAN" if (done + n) % 3 == 0 else "STAFF_SEARCH",
                    confirm_additional=True,
                    now=at,
                )
                i += 1
                if done in undo_at:
                    ledger.reverse_redemption(
                        actor=actor,
                        entry_public_id=res.entry.public_id,
                        reason="Scanned the wrong customer",
                        idempotency_key=f"d03:{customer.customer_code}:undo{i}",
                        now=at + timedelta(minutes=2),
                    )
                    continue
                done += 1
            day += timedelta(days=1)
        return done

    def _pass_story(self, n, customer, owner_actor, staff, today):
        plan = self._plan_for(n)
        per_day = 2 if plan.meals_per_cycle == 60 else 1
        if n <= 4:  # fresh
            p = n - 1
            rec = self._buy(owner_actor, customer, plan, _at(today - timedelta(days=p), 11, 20), n)
            self._redeem_series(
                staff, customer, today - timedelta(days=p), min(p * per_day + 1, plan.meals_per_cycle - 1), per_day, n=n
            )
            if n == 4:  # entered twice by mistake: the duplicate is voided
                dup = self._buy(owner_actor, customer, plan, _at(today - timedelta(days=p), 11, 40), n, k=1)
                billing.void_payment(
                    actor=owner_actor,
                    payment_public_id=dup.payment.public_id,
                    reason="Entered twice by mistake",
                    now=_at(today - timedelta(days=p), 11, 45),
                )
            return
        if n <= 12:  # mid-use
            p = 8 + (n % 7)
            start = today - timedelta(days=p)
            rec = self._buy(owner_actor, customer, plan, _at(start, 11, 10), n)
            self._redeem_series(
                staff, customer, start, int(p * 0.85) * per_day, per_day, n=n, undo_at=(3,) if n in (6, 9, 11) else ()
            )
            if n == 7:
                ledger.adjust(
                    actor=owner_actor,
                    pass_public_id=rec.pass_.public_id,
                    quantity=2,
                    reason="Goodwill — late delivery on 3 days",
                    idempotency_key="d03:adj:7",
                    now=timezone.now() - timedelta(days=2),
                )
            return
        if n <= 16:  # near expiry
            p = 27 + (n % 2)
            start = today - timedelta(days=p)
            self._buy(owner_actor, customer, plan, _at(start, 11, 15), n)
            self._redeem_series(staff, customer, start, 22 + (n % 5), per_day, n=n)
            return
        if n <= 19:  # expired
            start = today - timedelta(days=45)
            rec = self._buy(owner_actor, customer, plan, _at(start, 11, 5), n)
            self._redeem_series(staff, customer, start, 18, per_day, n=n)
            passes.expire(Pass.objects.get(pk=rec.pass_.pk), now=rec.pass_.ends_at + timedelta(minutes=5))
            return
        if n <= 21:  # queued behind the current pass
            start = today - timedelta(days=12)
            self._buy(owner_actor, customer, plan, _at(start, 11, 0), n)
            self._redeem_series(staff, customer, start, 9, per_day, n=n)
            self._buy(owner_actor, customer, plan, timezone.now() - timedelta(minutes=3), n, k=1)
            return
        if n <= 23:  # blocked
            start = today - timedelta(days=9)
            self._buy(owner_actor, customer, plan, _at(start, 11, 0), n)
            self._redeem_series(staff, customer, start, 8, per_day, n=n)
            customers.set_status(
                actor=owner_actor,
                customer=customer,
                status=Customer.Status.BLOCKED,
                reason="Unpaid wallet balance (demo)",
            )
            return
        # 24-25: customer exists, never bought a pass
