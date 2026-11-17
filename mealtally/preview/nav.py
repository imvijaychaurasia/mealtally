"""Registry-driven navigation for tenants that have the demo dataset (D03 section 3)."""

from __future__ import annotations

from django.urls import reverse
from django.utils.translation import gettext as _

from mealtally.accounts.models import Role

from .registry import BY_KEY
from .registry import REGISTRY

# real url names -> registry key (so real pages light up the right item)
REAL_ACTIVE = {
    "redeem": {"staff-console"},
    "sell": {"staff-sell", "staff-sell-preview", "staff-sell-confirm"},
    "customers": {"admin-customers", "admin-customer", "staff-customers", "staff-customer-new"},
    "reports": {"admin-reports", "report-daily", "report-monthly", "report-expired", "report-statement"},
    "fees": {"report-fees"},
    "plans": {"admin-plans", "admin-plan-new", "admin-plan-edit"},
    "staff": {"admin-staff"},
    "settings": {"admin-settings"},
    "audit": {"admin-audit"},
    "today": {"admin-dashboard"},
}


def is_active(key: str, current: str) -> bool:
    if current in REAL_ACTIVE.get(key, ()):
        return True
    return current == key or current.startswith(key + "-")


def module_url(m, slug):
    ns, name = m.url_name.split(":")
    return reverse(f"{ns}:{name}", args=[slug])


def _item(m, slug, current, children=None):
    kids = children or []
    return {
        "key": m.key,
        "label": _(m.title),
        "url": module_url(m, slug) if not kids else "#",
        "icon": m.icon,
        "active": is_active(m.key, current) or any(c["active"] for c in kids),
        "children": kids,
        "preview": m.status == "preview",
    }


def _group(role, group, slug, current):
    return [
        {
            "label": _(m.title),
            "url": module_url(m, slug),
            "active": is_active(m.key, current),
            "key": m.key,
            "preview": m.status == "preview",
        }
        for m in REGISTRY
        if m.nav_group == group and role in m.roles
    ]


def build_demo_nav(slug: str, role: str, current: str):
    """Returns (top_items, tab_items). Mirrors D03 section 3."""

    def one(key):
        return _item(BY_KEY[key], slug, current)

    if role == Role.CUSTOMER:
        from mealtally.web.context import build_nav  # noqa: PLC0415

        _top, tabs = build_nav(slug, role, current)
        by = {t["key"]: t for t in tabs}
        meals, wallet = _item(BY_KEY["me-meals"], slug, current), _item(BY_KEY["me-wallet"], slug, current)
        # Home · Meals · Wallet · My QR · Profile  (History/Payments stay one tap away from Home)
        for k in ("me-meals", "me-wallet"):
            pass
        meals["active"] = current.startswith("me-meals") or current in ("me-deliveries", "me-order")
        wallet["active"] = current in ("me-wallet", "me-invoices")
        return [], [by["home"], meals, wallet, by["qr"], by["profile"]]
    if role == Role.CHEF:
        k = one("kitchen")
        return [k], []
    if role == Role.DRIVER:
        d = one("driver")
        return [d], []
    if role == Role.STAFF:
        items = [one("redeem"), one("sell"), one("orders"), one("customers")]
        items[3]["url"] = reverse("web:staff-customers", args=[slug])
        items[1]["label"] = _("Sell pass")
        return items, items
    # OWNER / MANAGER
    money_kids = _group(role, "money", slug, current)
    more_kids = _group(role, "more", slug, current)
    money = {
        "key": "money",
        "label": _("Money"),
        "url": "#",
        "icon": "wallet",
        "children": money_kids,
        "active": any(c["active"] for c in money_kids),
    }
    more_top = {
        "key": "more",
        "label": _("More"),
        "url": reverse("preview:more", args=[slug]),
        "icon": "more",
        "children": more_kids,
        "active": current == "more" or any(c["active"] for c in more_kids),
    }
    top = [
        one("today"),
        one("redeem"),
        one("sell"),
        one("orders"),
        one("customers"),
        one("kitchen"),
        one("delivery"),
        money,
        one("reports"),
        more_top,
    ]
    more_tab = {
        "key": "more",
        "label": _("More"),
        "url": reverse("preview:more", args=[slug]),
        "icon": "more",
        "active": more_top["active"] or money["active"],
        "children": [],
    }
    tabs = [one("today"), one("redeem"), one("orders"), one("customers"), more_tab]
    return top, tabs
