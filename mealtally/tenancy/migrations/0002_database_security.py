# SPDX-License-Identifier: AGPL-3.0-only
"""Row-level security on the tenant tables and the shared append-only trigger function (see docs/security.md)."""

from django.db import migrations

from mealtally.tenancy.rls import APPEND_ONLY_FUNCTION
from mealtally.tenancy.rls import CREATE_APPEND_ONLY_FUNCTION
from mealtally.tenancy.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0001_initial")]

    operations = [
        enable_rls("tenancy_tenant", "id"),
        enable_rls("tenancy_tenantsettings", "tenant_id"),
        migrations.RunSQL(CREATE_APPEND_ONLY_FUNCTION, reverse_sql=f"DROP FUNCTION IF EXISTS {APPEND_ONLY_FUNCTION}()"),
    ]
