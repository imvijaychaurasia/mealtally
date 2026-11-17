# SPDX-License-Identifier: AGPL-3.0-only
"""Customer Home extras for demo tenants: wallet, today's meal, coming up and alerts, from the preview dataset."""

from __future__ import annotations

from django.utils import timezone

from . import data
from .views_me import _me
from .views_me import _next_meal


def summary(request) -> dict:
    D = data.for_tenant(request.tenant)
    s = _me(D, request)
    if s is None:  # not a wallet subscriber -> no wallet card, no deliveries
        return {"D": D, "no_wallet": True}
    plan = D["wplan"][s["plan"]]
    # only meals still to come; today's delivered/picked-up meal belongs in Activity
    done = ("DELIVERED", "PICKED_UP", "CANCELLED", "SKIPPED", "SKIPPED_HOLD")
    now = timezone.localtime().replace(tzinfo=None)
    upcoming = [
        o
        for o in D["orders"]
        if o["sub_id"] == s["id"]
        and 0 <= o["off"] <= 5  # noqa: PLR2004
        and o["status"] not in done
        and (o["off"] > 0 or (o.get("end_dt") or now) > now)
    ][:3]
    alerts = []
    if s["balance_minor"] < 0 or s["days_left"] <= 3:  # noqa: PLR2004
        alerts.append({"tone": "danger", "text": "low_balance", "days": s["days_left"]})
    pending = [t for t in D["topups"] if t["sub_id"] == s["id"] and t["status"] == "PENDING"]
    if pending:
        alerts.append({"tone": "warn", "text": "pending_topup", "amount": pending[0]["amount_minor"]})
    return {"D": D, "s": s, "plan": plan, "nxt": _next_meal(D, s), "upcoming": upcoming, "alerts": alerts}
