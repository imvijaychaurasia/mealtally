# SPDX-License-Identifier: AGPL-3.0-only
"""Fail if any tenant-scoped table lacks ENABLE+FORCE row level security or a policy."""

from django.apps import apps
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import connection

from mealtally.tenancy.models import Tenant
from mealtally.tenancy.models import TenantScopedModel
from mealtally.tenancy.rls import APPEND_ONLY_TABLES
from mealtally.tenancy.rls import POLICY_NAME


def tenant_scoped_tables() -> list[str]:
    tables = []
    for model in apps.get_models():
        if issubclass(model, TenantScopedModel) or model is Tenant or model._meta.label == "audit.AuditEvent":
            tables.append(model._meta.db_table)
    return sorted(tables)


def rls_problems() -> list[str]:
    problems = []
    with connection.cursor() as cur:
        for table in tenant_scoped_tables():
            cur.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s", [table])
            row = cur.fetchone()
            if not row or not (row[0] and row[1]):
                problems.append(f"{table}: RLS not ENABLED+FORCED")
            cur.execute(
                "SELECT count(*) FROM pg_policies WHERE tablename = %s AND policyname = %s", [table, POLICY_NAME]
            )
            if cur.fetchone()[0] != 1:
                problems.append(f"{table}: policy {POLICY_NAME} missing")
        for table in APPEND_ONLY_TABLES:
            cur.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = %s::regclass AND tgname = %s",
                [table, f"{table}_append_only"],
            )
            if cur.fetchone()[0] != 1:
                problems.append(f"{table}: append-only trigger missing")
            cur.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = %s::regclass AND tgname = %s",
                [table, f"{table}_no_truncate"],
            )
            if cur.fetchone()[0] != 1:
                problems.append(f"{table}: TRUNCATE guard missing")
    return problems


class Command(BaseCommand):
    help = "Verify RLS + append-only triggers are in place for every tenant-scoped table."

    def handle(self, *args, **options):
        problems = rls_problems()
        if problems:
            raise CommandError("\n".join(problems))
        self.stdout.write(self.style.SUCCESS(f"RLS OK on {len(tenant_scoped_tables())} tables."))
