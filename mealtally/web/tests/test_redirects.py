# SPDX-License-Identifier: AGPL-3.0-only
"""No redirect that takes its target from the request can leave the site (CodeQL py/url-redirection)."""

import pytest
from django.test import Client

from mealtally.web.redirects import safe_next

pytestmark = pytest.mark.django_db

OFF_SITE = ["//evil.example/", "/\\evil.example/", "https://evil.example/", "javascript:alert(1)", " //evil.example"]


@pytest.mark.parametrize("target", OFF_SITE)
def test_dismissing_the_http_notice_never_leaves_the_site(target, client):
    response = client.post("/dismiss-http-notice", {"next": target})
    assert response.status_code == 302 and response["Location"] == "/"


def test_dismissing_the_http_notice_returns_to_the_page(client):
    assert client.post("/dismiss-http-notice", {"next": "/t/x/admin/?tab=2"})["Location"] == "/t/x/admin/?tab=2"


@pytest.mark.parametrize("target", OFF_SITE)
def test_meal_rules_banner_ignores_off_site_targets(w, owner_c, u, target):
    response = owner_c.post(u + "/admin/settings/meal-rules-banner", {"next": target})
    assert response.status_code == 302 and response["Location"].startswith(u + "/")


def test_meal_rules_banner_returns_to_a_page_of_the_restaurant(w, owner_c, u):
    assert owner_c.post(u + "/admin/settings/meal-rules-banner", {"next": u + "/admin/plans"})["Location"] == (
        u + "/admin/plans"
    )


def test_sign_in_redirects_carry_an_encoded_next(w, u):
    anon = Client()
    staff_page = anon.get(u + "/admin/?tab=a&x=1")
    assert staff_page["Location"] == u + "/?next=" + u + "/admin/%3Ftab%3Da%26x%3D1"
    platform = anon.get("/platform/")
    assert platform["Location"] == "/login?next=/platform/"


def test_safe_next_helper(rf):
    request = rf.get("/")  # host: testserver
    assert safe_next(request, "/t/x/", "/") == "/t/x/"
    assert safe_next(request, "http://testserver/t/x/", "/") == "http://testserver/t/x/"
    for target in [*OFF_SITE, ""]:
        assert safe_next(request, target, "/fallback") == "/fallback"
