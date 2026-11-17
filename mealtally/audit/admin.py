from django.contrib import admin

from mealtally.accounts.admin_site import ReadOnlyAdmin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(ReadOnlyAdmin):
    list_display = ("id", "created_at", "tenant", "actor", "action", "object_type", "object_public_id")
    list_filter = ("tenant", "action", "object_type")
    search_fields = ("object_public_id", "action")
