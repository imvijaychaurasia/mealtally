"""Public landing page content (D03.6 Part B). The feature grid is generated from the preview feature registry so a badge can
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
        _("Scan a customer's QR or search by name or phone; the balance updates at once."),
    ),
    (
        ("sell", "plans"),
        "sell",
        _("Meal passes and renewals"),
        _("Sell a pass at the counter, queue a renewal and see what is left."),
    ),
    (
        ("wallets",),
        "wallet",
        _("₹ wallet and top-ups"),
        _("Customers top up by UPI; each meal is debited from the wallet."),
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
        _("Plan stops, hand routes to drivers and collect photo proof of delivery."),
    ),
    (
        ("holds",),
        "holds",
        _("Holds and vacations"),
        _("Customers pause meals; closures and holidays are handled in one place."),
    ),
    (
        ("me-pass",),
        "profile",
        _("Customer self-service"),
        _("An installable web app (PWA): show the QR, see the balance and history."),
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
        _("Owner, manager, counter, chef and driver, each seeing only what they need."),
    ),
    (("branches",), "branch", _("Branches"), _("Kitchens and pickup points under one business.")),
    (("notifications",), "bell", _("Notifications"), _("Alerts for low balances, expiring passes and new orders.")),
]
HINDI = (("language",), "web", _("English and हिंदी"), _("Switch the screens between English and Hindi in one tap."))


def features() -> list[dict]:
    rows = [(*f,) for f in FEATURES] + [HINDI]
    return [{"icon": i, "title": t, "text": s, "status": status_for(*keys)} for keys, i, t, s in rows]


def audiences() -> list[dict]:
    return [
        {
            "title": _("Tiffin services"),
            "text": _("Home delivery with a daily menu, routes and drivers."),
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
            "text": _("Orders, prep and dispatch for kitchens without a dining room."),
            "status": status_for("cloud-kitchen"),
            "icon": "store",
        },
        {
            "title": _("Canteens and corporate meals"),
            "text": _("Prepaid meals for teams, with simple reports for the manager."),
            "status": status_for("redeem", "sell", "reports"),
            "icon": "customers",
        },
    ]


FAQ = [
    (
        _("Do customers need an app?"),
        _(
            "No. Customers use a web app in their phone browser and can add it to their home screen. There is nothing to download from an app store."
        ),
    ),
    (
        _("Does it work without internet at the counter?"),
        _(
            "No. The counter needs an internet connection to redeem a meal, because every redemption is checked against the live balance."
        ),
    ),
    (
        _("Can I use both passes and wallets?"),
        _(
            "Yes. Meal passes (a fixed number of meals) are live today. Wallet subscriptions are shown in the product as a preview and are coming soon."
        ),
    ),
    (
        _("What happens to unused meals?"),
        _(
            "A pass has a validity period. When it ends, the remaining meals expire. The owner can queue a renewal or adjust meals with a reason, and every change goes into the audit log."
        ),
    ),
    (
        _("Can I use my own name and colours?"),
        _(
            "Your business name and address appear on the sign-in screens, receipts and the customer app, and you can pick one of three looks. Custom logos and brand colours are planned."
        ),
    ),
    (
        _("Is my data shared with other businesses?"),
        _(
            "No. Each business's data is kept separate, and the database itself enforces that, not just the application."
        ),
    ),
    (
        _("Which payments are supported?"),
        _("UPI (recorded by your team) and cash today. Online payment gateways are coming soon."),
    ),
    (
        _("Is there Hindi support?"),
        _(
            "Yes. Staff and customer screens can be switched between English and Hindi. We are still extending the Hindi coverage."
        ),
    ),
    (
        _("How do I start?"),
        _("Book a demo. We will walk you through it and set up your business, plans and logins for you."),
    ),
]

TRUST = [
    (
        _("Your data stays yours"),
        _("Each business's data is isolated by the database itself, so one restaurant can never read another's."),
    ),
    (
        _("An honest ledger"),
        _(
            "Meals and payments are written to an append-only ledger with a full audit trail. Mistakes are reversed, never erased."
        ),
    ),
    (_("No double redemption"), _("Even with two counters scanning at once, a meal is only redeemed once.")),
    (_("Daily backups"), _("The database is backed up every day.")),
    (
        _("Privacy by design"),
        _(
            "Built with India's data protection law (the DPDP Act) in mind. We hold only what we need to run your meals."
        ),
    ),
]


# role, frame, image size, registry keys that decide the badge, title, alt text, three bullets


def pricing() -> dict:
    """D03.9 §A2: the mode is a PLATFORM SETTING (platform admin, no restart); the percentages are the default platform
    fee policy that billing applies to every new restaurant, so the page can never drift from what is charged."""
    from mealtally.tenancy.models import PlatformSettings  # noqa: PLC0415

    cfg = PlatformSettings.load()
    out = {"mode": cfg.marketing_pricing_mode, "headline": cfg.pricing_headline, "footnote": cfg.pricing_footnote}
    if cfg.marketing_pricing_mode == PlatformSettings.PricingMode.PERCENTAGE:
        out["platform_pct"] = billing_services.DEFAULT_PLATFORM_PCT.normalize()
        out["gateway_pct"] = billing_services.DEFAULT_GATEWAY_PCT.normalize()
    return out
