"""D03.9 QA-01 P2-12: the audit log in sentences people read ("Kajal Parmar reversed Mihir Desai's 1:38 PM meal ...").

Names instead of ids, rupees instead of paise. The raw JSON stays available behind a "Details" toggle on the page.
Lookups are batched per page (one query per object kind), never one per row.
"""

from __future__ import annotations

import json
import re
from uuid import UUID

from django.utils.translation import gettext as _

from mealtally.billing.receipts import method_label
from mealtally.common.utils import format_inr

from .labels import actor_label

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _uuids(events) -> set[UUID]:
    out: set[UUID] = set()
    for e in events:
        if e.object_public_id:
            out.add(e.object_public_id)
        for blob in (e.before or {}, e.after or {}):
            for v in blob.values() if isinstance(blob, dict) else ():
                if isinstance(v, str) and _UUID.match(v):
                    out.add(UUID(v))
    return out


def build_lookups(events) -> dict:
    """{uuid: {"kind", "name", ...}} for customers, passes, payments, ledger entries, plans and staff memberships."""
    from mealtally.accounts.models import Membership  # noqa: PLC0415
    from mealtally.billing.models import Payment  # noqa: PLC0415
    from mealtally.customers.models import Customer  # noqa: PLC0415
    from mealtally.ledger.models import MealLedgerEntry  # noqa: PLC0415
    from mealtally.passes.models import Pass  # noqa: PLC0415
    from mealtally.plans.models import Plan  # noqa: PLC0415

    ids = _uuids(events)
    if not ids:
        return {}
    out: dict = {}
    for c in Customer.objects.filter(public_id__in=ids).only("public_id", "full_name"):
        out[c.public_id] = {"kind": "customer", "name": c.full_name}
    for p in Pass.objects.filter(public_id__in=ids).select_related("customer"):
        out[p.public_id] = {"kind": "pass", "name": p.plan_name, "customer": p.customer.full_name}
    for p in Payment.objects.filter(public_id__in=ids).select_related("customer"):
        out[p.public_id] = {
            "kind": "payment",
            "name": p.receipt_number or "",
            "customer": p.customer.full_name,
            "amount": p.amount_paise,
        }
    for e in MealLedgerEntry.objects.filter(public_id__in=ids).select_related("customer"):
        out[e.public_id] = {"kind": "entry", "customer": e.customer.full_name, "at": e.occurred_at}
    for p in Plan.objects.filter(public_id__in=ids).only("public_id", "name"):
        out[p.public_id] = {"kind": "plan", "name": p.name}
    for m in Membership.objects.filter(public_id__in=ids).select_related("user"):
        out[m.public_id] = {"kind": "member", "name": m.user.name or m.user.get_username()}
    return out


def _time(at, tz) -> str:
    return at.astimezone(tz).strftime("%-I:%M %p") if at else ""


def _rupees(paise) -> str:
    try:
        return format_inr(int(paise))
    except TypeError, ValueError:
        return str(paise)


def summarize(event, lookups: dict, tz) -> str:  # noqa: C901, PLR0911, PLR0912
    """One sentence for one audit event (falls back to a tidy 'did X to Y' line for actions without a template)."""
    who = actor_label(event.actor)
    before, after = event.before or {}, event.after or {}
    obj = lookups.get(event.object_public_id, {})
    customer = obj.get("customer") or (obj.get("name") if obj.get("kind") == "customer" else "")
    a = event.action
    if a == "ledger.reverse":
        return _("%(who)s reversed %(cust)s's %(time)s meal — reason: %(reason)s") % {
            "who": who,
            "cust": customer or _("a customer"),
            "time": _time(obj.get("at"), tz),
            "reason": after.get("reason", "—"),
        }
    if a == "ledger.adjust":
        q = after.get("quantity", 0)
        return _("%(who)s adjusted %(cust)s's pass by %(q)s meals (now %(left)s) — reason: %(reason)s") % {
            "who": who,
            "cust": customer or _("a customer"),
            "q": f"{q:+d}" if isinstance(q, int) else q,
            "left": after.get("meals_remaining", "?"),
            "reason": after.get("reason", "—"),
        }
    if a == "payment.record":
        return _("%(who)s recorded %(amount)s by %(method)s from %(cust)s%(receipt)s") % {
            "who": who,
            "amount": _rupees(after.get("amount_paise")),
            "method": method_label(after.get("method", "")),
            "cust": lookups.get(_as_uuid(after.get("customer")), {}).get("name") or customer or _("a customer"),
            "receipt": f" ({obj['name']})" if obj.get("name") else "",
        }
    if a == "payment.void":
        return _("%(who)s voided %(receipt)s (%(amount)s, %(cust)s) — reason: %(reason)s") % {
            "who": who,
            "receipt": obj.get("name") or _("a payment"),
            "amount": _rupees(obj.get("amount")),
            "cust": customer or _("a customer"),
            "reason": after.get("reason", "—"),
        }
    if a == "redeem.denied":
        return _("%(who)s could not serve %(cust)s (%(channel)s): %(msg)s") % {
            "who": who,
            "cust": customer or _("a customer"),
            "channel": _("QR scan") if after.get("channel") == "QR_SCAN" else _("search"),
            "msg": after.get("message", after.get("code", "")),
        }
    if a == "redeem.override":
        entry = obj
        return _("%(who)s overrode the meal rules for %(cust)s (%(msg)s) — reason: %(reason)s") % {
            "who": who,
            "cust": entry.get("customer") or _("a customer"),
            "msg": before.get("message", before.get("code", "")),
            "reason": after.get("reason", "—"),
        }
    if a == "customer.set_status":
        verb = _("blocked") if after.get("status") == "BLOCKED" else _("unblocked")
        reason = after.get("reason") or ""
        return f"{who} {verb} {customer or _('a customer')}" + (f" — {_('reason')}: {reason}" if reason else "")
    if a in ("customer.create", "customer.self_signup"):
        return _("%(who)s added customer %(cust)s") % {"who": who, "cust": customer or after.get("full_name", "")}
    if a in ("customer.update", "customer.update_own_name"):
        changed = [k for k in after if before.get(k) != after.get(k)]
        return _("%(who)s updated %(cust)s (%(fields)s)") % {
            "who": who,
            "cust": customer or after.get("full_name", ""),
            "fields": ", ".join(changed) or _("no change"),
        }
    if a.startswith("pass."):
        verb = a.split(".", 1)[1].replace("_", " ")
        return _("%(who)s: pass %(verb)s — %(plan)s for %(cust)s") % {
            "who": who,
            "verb": verb,
            "plan": obj.get("name", ""),
            "cust": customer or _("a customer"),
        }
    if a in ("settings.update", "plan.update", "plan.create", "meal_slot.update", "meal_slot.create"):
        changed = [k for k in after if isinstance(before, dict) and before.get(k) != after.get(k)]
        label = {
            "settings.update": _("settings"),
            "plan.update": _("plan"),
            "plan.create": _("new plan"),
            "meal_slot.update": _("meal time"),
            "meal_slot.create": _("new meal time"),
        }[a]
        name = after.get("name", "")
        return _("%(who)s changed %(what)s%(name)s: %(fields)s") % {
            "who": who,
            "what": label,
            "name": f" {name}" if name else "",
            "fields": ", ".join(_field(k, before.get(k), after.get(k)) for k in changed) or _("saved, no change"),
        }
    if a == "driver.route_assign":
        return _("%(who)s assigned %(route)s to %(driver)s") % {
            "who": who,
            "route": after.get("route", ""),
            "driver": after.get("driver", ""),
        }
    # generic fallback: readable keys, rupees for *_paise, names for ids
    parts = [_field(k, before.get(k) if isinstance(before, dict) else None, v, lookups) for k, v in after.items()]
    return f"{who}: {a.replace('.', ' ').replace('_', ' ')}" + (f" — {'; '.join(parts)}" if parts else "")


def _as_uuid(value):
    try:
        return UUID(str(value))
    except TypeError, ValueError:
        return None


def _show(key: str, value, lookups=None) -> str:
    if value is None or value == "":
        return "—"
    if key.endswith("_paise"):
        return _rupees(value)
    if isinstance(value, str) and _UUID.match(value) and lookups:
        found = lookups.get(UUID(value), {})
        return found.get("name") or found.get("customer") or value[:8]
    if isinstance(value, bool):
        return _("on") if value else _("off")
    return str(value)


def _field(key: str, old, new, lookups=None) -> str:
    label = key.replace("_paise", "").replace("_", " ")
    if old is None or old == new:
        return f"{label}: {_show(key, new, lookups)}"
    return f"{label}: {_show(key, old, lookups)} → {_show(key, new, lookups)}"


def raw(event) -> str:
    return json.dumps({"before": event.before, "after": event.after}, ensure_ascii=False, indent=1, default=str)
