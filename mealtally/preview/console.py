"""D03.4 console shell: sidebar IA per role and the alerts that feed the bell and the dashboard strip.

Template/presentation layer only: every item maps to an EXISTING view (real or preview); nothing here creates routes.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop

from mealtally.accounts.models import Role

from . import data

O, M, S, C, D = Role.OWNER, Role.MANAGER, Role.STAFF, Role.CHEF, Role.DRIVER
OM, OMS = (O, M), (O, M, S)

# (group label, [(label, url_name, roles, icon, preview?, active url_names)])
GROUPS = [
    (
        None,
        [
            (gettext_noop("Dashboard"), "preview:today", OM, "grid", False, {"today", "admin-dashboard"}),
            (gettext_noop("Business profile"), "web:admin-settings", (O,), "store", False, {"admin-settings"}),
            (
                gettext_noop("Plan & platform fees"),
                "web:report-fees",
                (O,),
                "payments",
                False,
                {"report-fees"},
            ),  # D03.7: managers do not see fee items
            (gettext_noop("Staff & roles"), "web:admin-staff", (O,), "roles", False, {"admin-staff", "roles"}),
        ],
    ),
    (
        gettext_noop("Menu"),
        [
            (gettext_noop("Meal categories"), "preview:menu", OM, "menu", True, {"menu", "menu-planner"}),
            (
                gettext_noop("Meal plans"),
                "web:admin-plans",
                OM,
                "plans",
                False,
                {"admin-plans", "admin-plan-new", "admin-plan-edit", "plans-wallet", "plans-wallet-new"},
            ),
        ],
    ),
    (
        gettext_noop("Operations"),
        [
            (gettext_noop("Redeem counter"), "web:staff-console", OMS, "qr", False, {"staff-console"}),
            (
                gettext_noop("Customers"),
                "web:admin-customers",
                OM,
                "customers",
                False,
                {"admin-customers", "admin-customer", "wallets-customer"},
            ),
            (
                gettext_noop("Subscriptions"),
                "preview:subscriptions",
                OM,
                "subs",
                True,
                {"subscriptions", "subscriptions-new", "subscriptions-detail"},
            ),
            (
                gettext_noop("Sell pass"),
                "web:staff-sell",
                (S,),
                "sell",
                False,
                {"staff-sell", "staff-sell-preview", "staff-sell-confirm"},
            ),
            (
                gettext_noop("Customers"),
                "web:staff-customers",
                (S,),
                "customers",
                False,
                {"staff-customers", "staff-customer-new"},
            ),
            (gettext_noop("Orders"), "preview:orders", OMS, "orders", True, {"orders", "orders-new", "orders-detail"}),
            (gettext_noop("Kitchen"), "preview:kitchen", (O, M, C), "kitchen", True, {"kitchen", "kitchen-labels"}),
            (
                gettext_noop("Delivery routes"),
                "preview:delivery",
                OM,
                "delivery",
                True,
                {"delivery"},
            ),
            (gettext_noop("Driver"), "preview:driver", (D, O, M), "delivery", True, {"driver"}),
            (gettext_noop("Expenses"), "preview:expenses", OM, "expense", True, {"expenses", "expenses-profit"}),
        ],
    ),
    (
        gettext_noop("Finance"),
        [
            (
                gettext_noop("Receipts & payments"),
                "web:report-monthly",
                OM,
                "invoice",
                False,
                {"report-monthly", "report-statement"},
            ),
            (gettext_noop("Wallet top-ups"), "preview:wallets", OM, "wallet", True, {"wallets", "payment-setup"}),
            (gettext_noop("Invoices"), "preview:invoices", OM, "invoice", True, {"invoices", "invoices-detail"}),
        ],
    ),
    (
        gettext_noop("Insights"),
        [
            (
                gettext_noop("Reports"),
                "web:admin-reports",
                OM,
                "reports",
                False,
                {"admin-reports", "report-daily", "report-expired"},
            ),
            (gettext_noop("Audit log"), "web:admin-audit", OM, "history", False, {"admin-audit"}),
        ],
    ),
    (
        gettext_noop("Settings"),
        [
            (gettext_noop("Settings"), "web:admin-settings", (O,), "cog", False, {"admin-settings-x"}),
            (
                gettext_noop("Customer portal"),
                "web:login-customer",
                OM,
                "web",
                False,
                {"login-customer", "tenant-home"},
            ),
            # screens outside the prescribed IA (holds, branches, notifications, website, cloud kitchen, ...) stay one click away
            (
                gettext_noop("All sections"),
                "preview:more",
                OM,
                "more",
                True,
                {"more", "holds", "tiffin-boxes", "branches", "notifications", "website", "cloud-kitchen", "roles"},
            ),
        ],
    ),
]


RAIL_SHORT = {"Redeem counter": "Redeem", "Sell pass": "Sell", "Customers": "Customers", "Orders": "Orders"}


def build_sidebar(slug: str, role: str, current: str, *, demo: bool):
    """Groups of items this role may use (same permissions as today). Preview items need the demo dataset, else they are hidden."""
    out = []
    for label, items in GROUPS:
        rows = []
        for name, url_name, roles, icon, preview, active in items:
            if role not in roles or (preview and not demo):
                continue
            if url_name == "web:report-fees" and not settings.MEALTALLY_PLATFORM_FEES:
                continue
            rows.append(
                {
                    "label": _(name),
                    "short": _(RAIL_SHORT.get(name, name)),
                    "url": reverse(url_name, args=[slug]),
                    "icon": icon,
                    "preview": preview,
                    "active": current in active,
                }
            )
        if rows:
            out.append({"label": _(label) if label else "", "items": rows})
    return out


def alerts(request, D=None):
    """Alerts for the owner/manager: [{key, text, url, tone}] with non-zero counts only."""
    from mealtally.reports import services as reports  # noqa: PLC0415

    D = D or data.for_tenant(request.tenant)
    slug = request.tenant.slug
    real = reports.dashboard(actor=request.actor)
    tomorrow = D["today"] + timedelta(days=1)
    t_orders = len([o for o in data.day_orders(D, tomorrow) if o["status"] in ("RECEIVED", "CONFIRMED")])
    pending = len([t for t in D["topups"] if t["status"] == "PENDING"])
    low = len([s for s in D["subscribers"] if s["status"] == "ACTIVE" and s["days_left"] <= 3])
    expiring = real["expiring_3_days"]
    rows = []
    if t_orders:
        rows.append(
            {
                "key": "orders",
                "tone": "info",
                "url": reverse("preview:orders", args=[slug]) + f"?date={tomorrow:%Y-%m-%d}",
                "text": _("Tomorrow has %(n)s scheduled orders.") % {"n": t_orders},
            }
        )
    if pending:
        rows.append(
            {
                "key": "topups",
                "tone": "warn",
                "url": reverse("preview:wallets", args=[slug]),
                "text": _("%(n)s top-up requests are waiting for your approval.") % {"n": pending},
            }
        )
    if expiring:
        rows.append(
            {
                "key": "expiring",
                "tone": "warn",
                "url": reverse("web:admin-customers", args=[slug]) + "?status=expiring",
                "text": _("%(n)s meal passes end within 3 days.") % {"n": expiring},
            }
        )
    if low:
        rows.append(
            {
                "key": "low",
                "tone": "danger",
                "url": reverse("preview:wallets", args=[slug]),
                "text": _("%(n)s customers are running low on wallet balance.") % {"n": low},
            }
        )
    return rows
