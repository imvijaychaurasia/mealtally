# SPDX-License-Identifier: AGPL-3.0-only
"""TRUNCATE guards on the append-only tables (row triggers don't fire on TRUNCATE)."""

from django.db import migrations

from mealtally.tenancy.rls import APPEND_ONLY_TABLES
from mealtally.tenancy.rls import CREATE_TRUNCATE_FUNCTION
from mealtally.tenancy.rls import TRUNCATE_FUNCTION
from mealtally.tenancy.rls import no_truncate


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0002_database_security"),
        ("ledger", "0002_database_security"),
        ("audit", "0002_database_security"),
        ("billing", "0002_database_security"),
    ]

    operations = [
        migrations.RunSQL(CREATE_TRUNCATE_FUNCTION, reverse_sql=f"DROP FUNCTION IF EXISTS {TRUNCATE_FUNCTION}()"),
        *[no_truncate(t) for t in APPEND_ONLY_TABLES],
    ]
