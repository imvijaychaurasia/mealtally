# SPDX-License-Identifier: AGPL-3.0-only
"""Grant the application role its privileges after migrations (idempotent)."""

import os

from django.core.management.base import BaseCommand

from mealtally.tenancy.db import grant_app_privileges


class Command(BaseCommand):
    help = "GRANT DML privileges on all tables to the non-owner application role (run after migrate)."

    def handle(self, *args, **options):
        # the role docker/postgres/initdb/10-roles.sh creates; override for a managed database
        role = os.environ.get("MEALTALLY_APP_DB_USER", "mealtally_app")
        grant_app_privileges(role)
        self.stdout.write(self.style.SUCCESS(f"Privileges granted to role {role!r}."))
