# SPDX-License-Identifier: AGPL-3.0-only
from django.apps import AppConfig


class TenancyConfig(AppConfig):
    name = "mealtally.tenancy"
    label = "tenancy"
    verbose_name = "Tenancy"
