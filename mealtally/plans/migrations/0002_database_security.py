# SPDX-License-Identifier: AGPL-3.0-only
"""Row-level security for this app's tenant tables."""

from django.db import migrations

from mealtally.tenancy.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [("plans", "0001_initial"), ("tenancy", "0002_database_security")]

    operations = [
        enable_rls("plans_plan", "tenant_id"),
        enable_rls("plans_mealslot", "tenant_id"),
        enable_rls("plans_planmealslot", "tenant_id"),
    ]
