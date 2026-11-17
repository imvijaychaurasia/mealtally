# SPDX-License-Identifier: AGPL-3.0-only
"""Row-level security and the append-only trigger for this app's tenant tables."""

from django.db import migrations

from mealtally.tenancy.rls import append_only
from mealtally.tenancy.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [("ledger", "0001_initial"), ("tenancy", "0002_database_security")]

    operations = [
        enable_rls("ledger_mealledgerentry", "tenant_id"),
        append_only("ledger_mealledgerentry"),
    ]
