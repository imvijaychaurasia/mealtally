# SPDX-License-Identifier: AGPL-3.0-only
from django.urls import include
from django.urls import path

app_name = "api"
urlpatterns = [path("v1/", include("mealtally.api.v1.urls"))]
