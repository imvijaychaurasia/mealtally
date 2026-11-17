from django.conf import settings
from django.contrib import admin
from django.urls import include
from django.urls import path

from mealtally.api.views import healthz
from mealtally.web import views_language

handler400 = "mealtally.web.errors.bad_request"
handler403 = "mealtally.web.errors.permission_denied"
handler404 = "mealtally.web.errors.not_found"
handler500 = "mealtally.web.errors.server_error"

urlpatterns = [
    path("", include("mealtally.preview.urls")),
    path("", include("mealtally.web.urls")),
    path("healthz", healthz, name="healthz"),
    path("i18n/setlang/", views_language.set_language, name="set_language"),
    # Django admin == platform admin (platform administrators only)
    path(settings.ADMIN_URL, admin.site.urls),
    # Web login pages (allauth). Closed signup; staff are created by admins.
    path("accounts/", include("allauth.urls")),
    # Versioned API: /api/v1/t/<slug>/... and /api/v1/platform/...
    path("api/", include("mealtally.api.urls")),
]
