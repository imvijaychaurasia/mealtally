# SPDX-License-Identifier: AGPL-3.0-only
import uuid

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from mealtally.tenancy.managers import TenantManager


class AuditEvent(models.Model):
    """Append-only audit trail. ``tenant`` is NULL for platform-level actions."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    tenant = models.ForeignKey("tenancy.Tenant", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    action = models.CharField(max_length=64)
    object_type = models.CharField(max_length=64)
    object_public_id = models.UUIDField(null=True, blank=True)
    before = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    after = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        indexes = [models.Index(fields=["tenant", "-created_at"]), models.Index(fields=["object_public_id"])]
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"{self.action} {self.object_type}"
