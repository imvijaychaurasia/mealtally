# SPDX-License-Identifier: AGPL-3.0-only
import logging

from celery import shared_task

from mealtally.tenancy import services as tenancy
from mealtally.tenancy.context import tenant_context

from . import services

logger = logging.getLogger(__name__)


@shared_task(name="mealtally.ledger.tasks.reconcile_ledgers")
def reconcile_ledgers() -> dict:
    """Nightly: SUM(quantity) == meals_remaining for every pass of every tenant."""
    total = 0
    for tenant_id in tenancy.list_tenant_ids():
        with tenant_context(tenant_id):
            total += len(services.find_mismatches())
    if total:
        logger.error("ledger reconciliation found mismatches", extra={"count": total})
    return {"mismatches": total}
