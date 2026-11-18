# SPDX-License-Identifier: AGPL-3.0-only
"""Public landing page content. The feature grid is generated from the preview feature registry so a badge can
never say "Live" for something the product does not do: a feature is Live only when EVERY registry module it needs is ``real``.
"""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

from mealtally.billing import services as billing_services
from mealtally.preview.registry import BY_KEY


def status_for(*keys: str) -> str:
    """'live' when every module is real in the registry, else 'soon'. An unknown key is never Live."""
    return "live" if keys and all(k in BY_KEY and BY_KEY[k].status == "real" for k in keys) else "soon"


# (registry keys, icon, title, one sentence)
FEATURES = [
    (
        ("redeem",),
        "redeem",
        _("QR meal redemption"),
        _("Scan a customer's QR or search by name or phone. Meals left update at once."),
    ),
    (
        ("sell", "plans"),
        "sell",
        _("Meal passes and renewals"),
        _("Sell a pass at the counter and queue the renewal."),
    ),
    (
        ("wallets",),
        "wallet",
        _("Wallet and top-ups"),
        _("Customers top up a wallet and each meal is debited from it."),
    ),
    (
        ("orders",),
        "orders",
        _("Automatic daily orders"),
        _("Orders are created for you at the cutoff, so nobody re-types the day's list."),
    ),
    (
        ("kitchen",),
        "kitchen",
        _("Kitchen prep and packing"),
        _("A cooking plan, packing lists and labels with allergen flags."),
    ),
    (
        ("delivery",),
        "delivery",
        _("Delivery routes and driver app"),
        _("Plan routes for drivers and collect photo proof of delivery."),
    ),
    (
        ("holds",),
        "holds",
        _("Holds and vacations"),
        _("Customers pause meals, and you schedule closures and holidays."),
    ),
    (
        ("me-pass",),
        "profile",
        _("Customer self-service"),
        _("An installable web app where customers show their QR and see their meals left."),
    ),
    (("sell",), "invoice", _("Receipts"), _("A numbered receipt for every payment, shareable as a PDF.")),
    (
        ("invoices",),
        "invoice",
        _("Monthly invoices"),
        _("Month-end invoices for wallet customers with a PDF to share."),
    ),
    (("expenses",), "expense", _("Expenses and profit"), _("Record spend and see profit by month.")),
    (
        ("staff",),
        "roles",
        _("Staff roles and permissions"),
        _("Each staff role sees only the screens it needs."),
    ),
    (("branches",), "branch", _("Branches"), _("Kitchens and pick-up points under one restaurant.")),
    (("notifications",), "bell", _("Notifications"), _("Alerts for low balances, expiring passes and new orders.")),
]
HINDI = (("language",), "web", _("Multiple languages"), _("Staff and customers choose their own screen language."))


def features() -> list[dict]:
    rows = [(*f,) for f in FEATURES] + [HINDI]
    return [{"icon": i, "title": t, "text": s, "status": status_for(*keys)} for keys, i, t, s in rows]


def audiences() -> list[dict]:
    return [
        {
            "title": _("Tiffin services"),
            "text": _("Home delivery with a daily menu and driver routes."),
            "status": status_for("redeem", "delivery", "wallets"),
            "icon": "delivery",
        },
        {
            "title": _("Mess and dine-in"),
            "text": _("Monthly meal passes redeemed with a QR scan at the counter."),
            "status": status_for("redeem", "sell"),
            "icon": "redeem",
        },
        {
            "title": _("Cloud kitchens"),
            "text": _("Orders and prep for kitchens without a dining room."),
            "status": status_for("cloud-kitchen"),
            "icon": "store",
        },
        {
            "title": _("Canteens and corporate meals"),
            "text": _("Prepaid meals for teams, with reports for the manager."),
            "status": status_for("redeem", "sell", "reports"),
            "icon": "customers",
        },
    ]


FAQ = [
    (
        _("Customers don't need to install an app"),
        _(
            "Customers use a web app in their phone browser and can add it to their home screen. There is nothing to download from an app store."
        ),
    ),
    (
        _("The counter needs an internet connection"),
        _(
            "Redeeming a meal needs a connection, because each redemption is checked against the meals left on the pass."
        ),
    ),
    (
        _("Passes and wallets"),
        _(
            "Meal passes (a fixed number of meals) work today. Wallet subscriptions appear in the product as a preview and are coming soon."
        ),
    ),
    (
        _("Unused meals"),
        _(
            "A pass has an end date. When it ends, the remaining meals expire. The owner can queue a renewal or adjust meals with a reason, and each change goes into the audit log."
        ),
    ),
    (
        _("Your name and colours"),
        _(
            "Your restaurant name and address appear on the sign-in screens, receipts and the customer app. You can pick one of three themes. Custom logos and brand colours are planned."
        ),
    ),
    (
        _("Your data is not shared with other restaurants"),
        _("Each restaurant's data is kept separate, and the database enforces this as well as the application."),
    ),
    (
        _("Supported payments"),
        _("Your team records cash and other manual payments today. Online payment gateways are coming soon."),
    ),
    (
        _("Languages"),
        _("Staff and customers can choose their screen language. Languages still being reviewed are marked Beta."),
    ),
    (
        _("Getting started"),
        _("Book a demo. We will show you the product and set up your restaurant, plans and staff accounts."),
    ),
]

TRUST = [
    (
        _("Separate data for each restaurant"),
        _("The database keeps each restaurant's data apart, so one restaurant can't read another's."),
    ),
    (
        _("Append-only ledger"),
        _(
            "Meals and payments go into an append-only ledger with an audit trail. Mistakes are corrected with a new entry, not erased."
        ),
    ),
    (_("No double redemption"), _("Even with two counters scanning at once, a meal is only redeemed once.")),
    (_("Daily backups"), _("The database is backed up every day.")),
    (
        _("Privacy"),
        _("We hold only the data needed to run your meal service."),
    ),
]


# role, frame, image size, registry keys that decide the badge, title, alt text, three bullets


def pricing() -> dict:
    """The mode is a PLATFORM SETTING (platform admin, no restart); the percentages are the default platform
    fee policy that billing applies to every new restaurant, so the page can never drift from what is charged."""
    from mealtally.tenancy.models import PlatformSettings  # noqa: PLC0415

    cfg = PlatformSettings.load()
    out = {"mode": cfg.marketing_pricing_mode, "headline": cfg.pricing_headline, "footnote": cfg.pricing_footnote}
    if cfg.marketing_pricing_mode == PlatformSettings.PricingMode.PERCENTAGE:
        out["platform_pct"] = billing_services.DEFAULT_PLATFORM_PCT.normalize()
        out["gateway_pct"] = billing_services.DEFAULT_GATEWAY_PCT.normalize()
    return out
