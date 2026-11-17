import pytest

pytestmark = pytest.mark.django_db


def csp(resp):
    return {
        p.split(" ", 1)[0]: p.split(" ", 1)[1] if " " in p else "" for p in resp["Content-Security-Policy"].split("; ")
    }


def test_strict_policy_everywhere_except_the_two_scoped_prefixes(client):
    site = csp(client.get("/"))
    assert (
        site["script-src"] == "'self'"
        and site["style-src"] == "'self'"
        and "unsafe-inline" not in client.get("/")["Content-Security-Policy"]
    )
    assert "unsafe-eval" not in client.get("/")["Content-Security-Policy"]
    admin = csp(client.get("/platform/admin/login/"))
    assert (
        admin["style-src"] == "'self' 'unsafe-inline'" and admin["script-src"] == "'self'"
    )  # only styles relaxed for the admin
    docs = csp(client.get("/api/v1/docs/"))
    assert "'unsafe-inline'" in docs["script-src"]  # swagger bootstrap (scoped override, platform-admin-only page)
    assert csp(client.get("/api/v1/auth/csrf"))["script-src"] == "'self'"
