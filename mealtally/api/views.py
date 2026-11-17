from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django_redis import get_redis_connection


@require_GET
def healthz(request):
    """Liveness/readiness: Postgres + Valkey reachable. No auth, no tenant data."""
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001
        checks["database"] = "error"
    try:
        get_redis_connection("default").ping()
        checks["valkey"] = "ok"
    except Exception:  # noqa: BLE001
        checks["valkey"] = "error"
    ok = all(v == "ok" for v in checks.values())
    return JsonResponse({"status": "ok" if ok else "error", **checks}, status=200 if ok else 503)
