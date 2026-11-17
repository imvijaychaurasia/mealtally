# SPDX-License-Identifier: AGPL-3.0-only
"""Feature registry (D03): one row per module. The nav reads it; flip ``status`` to "real" when a module is built (D04+)."""

from __future__ import annotations

from dataclasses import dataclass

from mealtally.accounts.models import Role

O, M, S, C, D, U = Role.OWNER, Role.MANAGER, Role.STAFF, Role.CHEF, Role.DRIVER, Role.CUSTOMER
OM = (O, M)
OMS = (O, M, S)


@dataclass(frozen=True)
class Module:
    key: str
    title: str
    nav_group: str  # top | money | more | driver | me | none
    roles: tuple
    status: str  # real | preview
    url_name: str  # "web:..." or "preview:..."
    blurb: str = ""
    icon: str = "more"


REGISTRY: list[Module] = [
    Module("today", "Today", "top", OM, "real", "preview:today", "Orders, meals and money at a glance", "today"),
    Module("redeem", "Redeem", "top", OMS, "real", "web:staff-console", "Scan or search, redeem a meal", "redeem"),
    Module("sell", "Sell pass", "top", OMS, "real", "web:staff-sell", "Sell a meal pass at the counter", "sell"),
    Module("orders", "Orders", "top", OMS, "preview", "preview:orders", "Day board by slot with cutoff lock", "orders"),
    Module(
        "customers",
        "Customers",
        "top",
        OMS,
        "real",
        "web:admin-customers",
        "Pass customers and wallet customers",
        "customers",
    ),
    Module(
        "kitchen",
        "Kitchen",
        "top",
        (O, M, C),
        "preview",
        "preview:kitchen",
        "Cooking plan, packing, labels, pickup",
        "kitchen",
    ),
    Module(
        "delivery", "Delivery", "top", OM, "preview", "preview:delivery", "Routes, stop order and drivers", "delivery"
    ),
    Module(
        "wallets",
        "Wallets & top-ups",
        "money",
        OM,
        "preview",
        "preview:wallets",
        "Top-up requests and wallet ledgers",
        "wallet",
    ),
    Module("invoices", "Invoices", "money", OM, "preview", "preview:invoices", "Monthly invoices with PDF", "invoice"),
    Module(
        "expenses",
        "Expenses & profit",
        "money",
        OM,
        "preview",
        "preview:expenses",
        "Spend, recurring rules and margin",
        "expense",
    ),
    Module(
        "payment-setup",
        "Payment setup",
        "money",
        OM,
        "preview",
        "preview:payment-setup",
        "UPI, bank and gateway",
        "wallet",
    ),
    Module(
        "fees",
        "Platform fee statement",
        "money",
        (O,),  # D03.8: owner only
        "real",
        "web:report-fees",
        "What you owe the platform this month",
        "reports",
    ),
    Module("reports", "Reports", "top", OM, "real", "web:admin-reports", "Daily, monthly, expired", "reports"),
    Module("menu", "Menu", "more", (O, M), "preview", "preview:menu", "Meal slots, dishes, weekly planner", "menu"),
    Module("plans", "Plans", "more", OM, "real", "web:admin-plans", "Pass plans (real) and wallet plans", "plans"),
    Module(
        "subscriptions", "Subscriptions", "more", OM, "preview", "preview:subscriptions", "Wallet subscribers", "subs"
    ),
    Module(
        "holds",
        "Holds & closures",
        "more",
        OM,
        "preview",
        "preview:holds",
        "Vacation holds and business closures",
        "holds",
    ),
    Module(
        "tiffin-boxes", "Tiffin boxes", "more", OM, "preview", "preview:tiffin-boxes", "Issue/return ledger", "delivery"
    ),
    Module("branches", "Branches", "more", OM, "preview", "preview:branches", "Kitchens and pickup points", "branch"),
    Module("staff", "Staff", "more", (O,), "real", "web:admin-staff", "Logins and password resets", "customers"),
    Module(
        "roles",
        "Roles & permissions",
        "more",
        (O,),
        "preview",
        "preview:roles",
        "Permission matrix and presets",
        "roles",
    ),
    Module(
        "notifications",
        "Notifications",
        "more",
        OM,
        "preview",
        "preview:notifications",
        "Templates per event and channel",
        "bell",
    ),
    Module("website", "Website", "more", OM, "preview", "preview:website", "Your restaurant's public page", "web"),
    Module(
        "cloud-kitchen",
        "Cloud kitchen",
        "more",
        OM,
        "preview",
        "preview:cloud-kitchen",
        "A-la-carte online ordering",
        "orders",
    ),
    Module(
        "settings", "Settings", "more", (O,), "real", "web:admin-settings", "Name, colour, rules, receipts", "plans"
    ),
    Module("audit", "Audit log", "more", OM, "real", "web:admin-audit", "Who did what, and when", "history"),
    Module(
        "driver",
        "Driver console",
        "driver",
        (D, O, M),
        "preview",
        "preview:driver",
        "Today's route and proof of delivery",
        "delivery",
    ),
    Module("me-pass", "My pass", "none", (U,), "real", "web:me-home", "QR, balance and history", "qr"),
    Module(
        "language",
        "English / हिंदी",
        "none",
        (O, M, S, C, D, U),
        "real",
        "web:landing",
        "Switch screens to Hindi",
        "web",
    ),
    Module("me-meals", "Meals", "me", (U,), "preview", "preview:me-meals", "Choose today's dish, skip, hold", "meals"),
    Module("me-wallet", "Wallet", "me", (U,), "preview", "preview:me-wallet", "Balance, top-up, ledger", "wallet"),
    Module(
        "me-deliveries",
        "Deliveries",
        "none",
        (U,),
        "preview",
        "preview:me-deliveries",
        "Delivery history with proof",
        "delivery",
    ),
    Module("me-invoices", "Invoices", "none", (U,), "preview", "preview:me-invoices", "Monthly invoices", "invoice"),
    Module(
        "me-order", "Order online", "none", (U,), "preview", "preview:me-order", "Cloud kitchen, order ahead", "orders"
    ),
]
BY_KEY = {m.key: m for m in REGISTRY}
BY_URL = {m.url_name.split(":")[1]: m for m in REGISTRY}


def module_for_url(url_name: str) -> Module | None:
    return BY_URL.get(url_name)
