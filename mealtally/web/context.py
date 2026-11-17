# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

from django.conf import settings
from django.urls import reverse
from django.utils.translation import gettext as _

from . import themes

# which url_names light up which nav item
GROUPS = {
    "redeem": {"staff-console"},
    "sell": {"staff-sell", "staff-sell-preview", "staff-sell-confirm"},
    "customers": {"admin-customers", "admin-customer", "staff-customers", "staff-customer-new"},
    "reports": {"admin-reports", "report-daily", "report-monthly", "report-expired", "report-statement", "report-fees"},
    "more": {
        "admin-dashboard",
        "admin-more",
        "admin-plans",
        "admin-plan-new",
        "admin-plan-edit",
        "admin-staff",
        "admin-settings",
        "admin-audit",
    },
    "home": {"me-home"},
    "qr": {"me-qr"},
    "history": {"me-history"},
    "payments": {"me-payments"},
    "profile": {"me-profile", "me-pin"},
}


def _item(key, label, url, icon, current, children=None):  # noqa: PLR0917
    return {
        "key": key,
        "label": label,
        "url": url,
        "icon": icon,
        "active": current in GROUPS.get(key, set()),
        "children": children or [],
    }


def build_nav(slug: str, role: str, current: str):
    r = lambda name, *a: reverse(f"web:{name}", args=[slug, *a])  # noqa: E731
    if role == "CUSTOMER":
        tabs = [
            _item("home", _("Home"), r("me-home"), "home", current),
            _item("qr", _("My QR"), r("me-qr"), "qr", current),
            _item("history", _("History"), r("me-history"), "history", current),
            _item("payments", _("Payments"), r("me-payments"), "payments", current),
            _item("profile", _("Profile"), r("me-profile"), "profile", current),
        ]
        return [], tabs
    redeem = _item("redeem", _("Redeem"), r("staff-console"), "redeem", current)
    sell = _item("sell", _("Sell pass"), r("staff-sell"), "sell", current)
    if role == "STAFF":
        customers = _item("customers", _("Customers"), r("staff-customers"), "customers", current)
        items = [redeem, sell, customers]
        return items, items
    customers = _item("customers", _("Customers"), r("admin-customers"), "customers", current)
    reports = _item("reports", _("Reports"), r("admin-reports"), "reports", current)
    more_children = [
        {"label": _("Dashboard"), "url": r("admin-dashboard")},
        {"label": _("Plans"), "url": r("admin-plans")},
    ]
    if role == "OWNER":
        more_children += [
            {"label": _("Staff"), "url": r("admin-staff")},
            {"label": _("Settings"), "url": r("admin-settings")},
        ]
    more_children.append({"label": _("Audit log"), "url": r("admin-audit")})
    more_top = _item("more", _("More"), r("admin-more"), "more", current, children=more_children)
    more_tab = _item("more", _("More"), r("admin-more"), "more", current)
    return [redeem, sell, customers, reports, more_top], [redeem, sell, customers, reports, more_tab]


def _help(role):
    from .help import articles_for  # noqa: PLC0415

    return articles_for(role)


def _bell():
    from django.utils import timezone  # noqa: PLC0415

    from mealtally.preview import data  # noqa: PLC0415

    return data.get(timezone.localdate())["bell"][:8]


CUSTOMER_ACTIVE = {
    "home": {"me-home", "me-meals"},
    "order": {"me-order"},
    "activity": {"me-activity", "me-history", "me-payments", "me-deliveries", "me-invoices", "me-invoices-pdf"},
    "wallet": {"me-wallet"},
    "account": {"me-account", "me-profile", "me-pin"},
}


def customer_tabs(tenant, current: str, user):
    """Home · Order · Activity · Wallet · Account (Order, Wallet only where the tenant has them), and Show QR."""
    slug = tenant.slug
    rows = [("home", _("Home"), "home", reverse("web:me-home", args=[slug]))]
    if tenant.has_demo_dataset:
        rows.append(("order", _("Order"), "orders", reverse("preview:me-order", args=[slug])))
    rows.append(("activity", _("Activity"), "history", reverse("web:me-activity", args=[slug])))
    from mealtally.customers.models import Customer  # noqa: PLC0415

    if tenant.has_demo_dataset and Customer.objects.filter(user=user, has_wallet=True).exists():
        rows.append(("wallet", _("Wallet"), "wallet", reverse("preview:me-wallet", args=[slug])))
    rows.append(("account", _("Account"), "profile", reverse("web:me-account", args=[slug])))
    tabs = [
        {"key": k, "label": label, "icon": icon, "url": url, "active": current in CUSTOMER_ACTIVE[k]}
        for k, label, icon, url in rows
    ]
    from mealtally.passes.models import Pass  # noqa: PLC0415

    show_qr = Pass.objects.filter(customer__user=user, status="ACTIVE").exists()
    return tabs, show_qr


def _plain_http_off_localhost() -> bool:
    """True when people reach the instance over plain http:// on an address other than localhost."""
    from urllib.parse import urlparse  # noqa: PLC0415

    url = urlparse(settings.MEALTALLY_BASE_URL)
    return url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1")


def web(request):
    tenant = getattr(request, "tenant", None)
    role = getattr(request, "role", None)
    ctx = {
        "tenant": tenant,
        "cfg": getattr(request, "cfg", None),
        "role": role,
        "is_staff_role": role in ("OWNER", "MANAGER", "STAFF"),
        "is_admin_role": role in ("OWNER", "MANAGER"),
        "nav_top": [],
        "nav_tabs": [],
        "who": "",
        "home_href": "/",
        "pv_badge": bool(tenant and tenant.show_preview_badges),
        "pv_module": getattr(request, "pv_module", None),
        "help_articles": [],
        "shell_template": "web/base_classic.html",
        "sidebar": [],
        "console_alerts": [],
        "theme": themes.PLATFORM,
        "theme_color": themes.tokens(themes.PLATFORM)["primary"],
        "email_enabled": settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend"
        or settings.EMAIL_HOST not in ("", "localhost", "127.0.0.1"),
        "whatsapp_number": getattr(settings, "WHATSAPP_SUPPORT_NUMBER", ""),
        "legal_live": False,
        "language_choices": [
            (code, name, code in settings.MEALTALLY_BETA_LANGUAGES) for code, name in settings.LANGUAGES
        ],
        "mode_multi": settings.MEALTALLY_MODE == "multi",
        "fees_on": settings.MEALTALLY_PLATFORM_FEES,
    }
    ctx["http_notice"] = (
        (role in ("OWNER", "MANAGER") or bool(getattr(getattr(request, "user", None), "is_platform_admin", False)))
        and _plain_http_off_localhost()
        and not request.session.get("http_notice_dismissed")
    )
    if settings.MEALTALLY_LEGAL_PAGES:
        from .views_marketing import legal_pages_live  # noqa: PLC0415

        ctx["legal_live"] = legal_pages_live()
    if tenant and not request.path.startswith("/platform"):  # platform surfaces are always tally (D03.5)
        ctx["theme"] = themes.theme_for(tenant)
        ctx["theme_color"] = themes.tokens(ctx["theme"])["primary"]
    cfg = ctx["cfg"]
    ctx["brand_name"] = (getattr(cfg, "display_name", "") or (tenant.name if tenant else "")) or "Mealtally"
    if tenant and not request.path.startswith("/platform"):
        ctx["brand_tagline"] = getattr(cfg, "tagline", "") or ""
        ctx["brand_address"] = getattr(cfg, "address", "") or ""
    else:
        ctx["brand_name"] = "Mealtally"
        ctx["brand_tagline"] = _("Prepaid meals, simplified.")
        ctx["brand_address"] = ""
    user = getattr(request, "user", None)
    match = getattr(request, "resolver_match", None)
    current = match.url_name if match else ""
    if tenant and role and user is not None and user.is_authenticated:
        from .access import home_url  # noqa: PLC0415

        if tenant.has_demo_dataset:
            from mealtally.preview.nav import build_demo_nav  # noqa: PLC0415

            ctx["nav_top"], ctx["nav_tabs"] = build_demo_nav(tenant.slug, role, current)
            ctx["pv_nav"] = True
            ctx["pv_bell"] = _bell()
        else:
            ctx["nav_top"], ctx["nav_tabs"] = build_nav(tenant.slug, role, current)
        ctx["help_articles"] = _help(role)
        if role == "OWNER" and cfg is not None and not cfg.meal_rules_banner_dismissed:
            from mealtally.plans.models import Plan  # noqa: PLC0415

            # D03.9 §B6: one-time nudge while any active plan has no meal-time rule and no daily limit
            ctx["meal_rules_banner"] = Plan.objects.filter(
                is_active=True, allowed_slots__isnull=True, max_meals_per_day__isnull=True
            ).exists()
        if role == "CUSTOMER":  # D03.7: one consumer app shell for customers, never the admin frame
            ctx["shell_template"] = "web/base_customer.html"
            ctx["cust_tabs"], ctx["show_qr"] = customer_tabs(tenant, current, user)
            ctx["pv_nav"] = False
        if (
            tenant.ui_shell == "console" and role != "CUSTOMER"
        ):  # D03.4: the console shell; customers keep the app layout
            from mealtally.preview import console  # noqa: PLC0415

            ctx["shell_template"] = "web/base_console.html"
            ctx["sidebar"] = console.build_sidebar(tenant.slug, role, current, demo=tenant.has_demo_dataset)
            ctx["pv_nav"] = False
            if role in ("OWNER", "MANAGER") and tenant.has_demo_dataset:
                ctx["console_alerts"] = console.alerts(request)
            if role in ("CHEF", "DRIVER"):  # D03.7 station shell: device-first, no sidebar, large type
                ctx["sidebar"] = []
                ctx["station"] = True
                if role == "DRIVER" and tenant.has_demo_dataset:
                    ctx["station_tabs"] = [
                        {
                            "label": _("Stops"),
                            "icon": "delivery",
                            "url": reverse("preview:driver", args=[tenant.slug]),
                            "active": current == "driver",
                        },
                        {
                            "label": _("Done"),
                            "icon": "redeem",
                            "url": reverse("preview:driver", args=[tenant.slug]) + "#delivered-group",
                            "active": False,
                        },
                        {
                            "label": _("Account"),
                            "icon": "profile",
                            "url": reverse("web:staff-password", args=[tenant.slug]),
                            "active": current == "staff-password",
                        },
                    ]
        ctx["home_href"] = home_url(tenant.slug, role, demo=tenant.has_demo_dataset)
        name = user.name or user.email or user.phone_e164 or ""
        if role == "CUSTOMER":
            from mealtally.customers.models import Customer  # noqa: PLC0415

            cust = Customer.objects.filter(user=user).only("full_name").first()
            name = cust.full_name if cust else name
        from .templatetags.mealtally_extras import role_label  # noqa: PLC0415

        ctx["who"] = f"{name} · {role_label(role)}"
    elif user is not None and getattr(user, "is_authenticated", False):
        label = _("Platform admin") if user.is_platform_admin else _("Counter")
        shown = user.name or user.email
        same = str(shown).strip().lower() == str(label).lower()
        ctx["who"] = shown if same else f"{shown} · {label}"
        ctx["who_chip"] = label if same else ""
    return ctx
