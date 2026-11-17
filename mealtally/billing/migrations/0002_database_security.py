# SPDX-License-Identifier: AGPL-3.0-only
"""Row-level security and the append-only trigger for this app's tenant tables."""

from django.db import migrations

from mealtally.tenancy.rls import append_only
from mealtally.tenancy.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial"), ("tenancy", "0002_database_security")]

    operations = [
        enable_rls("billing_payment", "tenant_id"),
        enable_rls("billing_feepolicy", "tenant_id"),
        enable_rls("billing_platformfeeentry", "tenant_id"),
        append_only("billing_platformfeeentry"),
    ]
