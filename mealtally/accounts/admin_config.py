from django.contrib.admin.apps import AdminConfig


class PlatformAdminConfig(AdminConfig):
    """Swap the default admin site for the tenant-context-aware platform admin site."""

    default_site = "mealtally.accounts.admin_site.PlatformAdminSite"
