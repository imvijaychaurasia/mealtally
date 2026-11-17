# SPDX-License-Identifier: AGPL-3.0-only
from django.apps import AppConfig


class TenancyConfig(AppConfig):
    name = "mealtally.tenancy"
    label = "tenancy"
    verbose_name = "Tenancy"

    def ready(self):
        from . import checks  # noqa: F401, PLC0415  (registers the locale-defaults system check)
