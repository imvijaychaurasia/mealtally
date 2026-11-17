import logging

from celery import shared_task

from mealtally.tenancy import services as tenancy
from mealtally.tenancy.context import tenant_context

from . import services

logger = logging.getLogger(__name__)


@shared_task(name="mealtally.passes.tasks.expire_and_activate_passes")
def expire_and_activate_passes() -> dict:
    """Every 5 minutes. Runs per tenant inside that tenant's context (RLS)."""
    totals = {"expired": 0, "activated": 0, "tenants": 0, "failed_tenants": 0}
    for tenant_id in tenancy.list_tenant_ids():
        try:
            with tenant_context(tenant_id):
                counts = services.run_due_transitions()
        except Exception:
            logger.exception("expiry/activation failed", extra={"tenant_id": tenant_id})
            totals["failed_tenants"] += 1
            continue
        totals["tenants"] += 1
        totals["expired"] += counts["expired"]
        totals["activated"] += counts["activated"]
    return totals
