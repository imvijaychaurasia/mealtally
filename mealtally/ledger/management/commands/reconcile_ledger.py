"""Check SUM(ledger.quantity) == pass.meals_remaining for every pass (exit 1 on mismatch)."""

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from mealtally.ledger import services
from mealtally.tenancy import services as tenancy
from mealtally.tenancy.context import tenant_context


class Command(BaseCommand):
    help = "Reconcile the meal ledger against cached pass balances."

    def handle(self, *args, **options):
        mismatches = []
        for tenant_id in tenancy.list_tenant_ids():
            with tenant_context(tenant_id):
                mismatches.extend(services.find_mismatches())
        for row in mismatches:
            self.stderr.write(f"MISMATCH {row}")
        if mismatches:
            raise CommandError(f"{len(mismatches)} mismatching pass(es).")
        self.stdout.write(self.style.SUCCESS("Ledger reconciled: no mismatches."))
