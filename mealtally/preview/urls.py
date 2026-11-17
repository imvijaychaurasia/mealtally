# SPDX-License-Identifier: AGPL-3.0-only
from django.urls import path

from . import views_core as core
from . import views_me as me
from . import views_money as money
from . import views_setup as setup

app_name = "preview"
t = "t/<slug:slug>/"
urlpatterns = [
    path(t + "admin/today", core.today, name="today"),
    path(t + "admin/all", core.more, name="more"),
    path(t + "admin/orders", core.orders, name="orders"),
    path(t + "admin/orders/new", core.order_new, name="orders-new"),
    path(t + "admin/orders/<int:no>", core.order_detail, name="orders-detail"),
    path(t + "admin/kitchen", core.kitchen, name="kitchen"),
    path(t + "admin/kitchen/labels", core.kitchen_labels, name="kitchen-labels"),
    path(t + "admin/delivery", core.delivery, name="delivery"),
    path(t + "admin/holds", core.holds, name="holds"),
    path(t + "admin/tiffin-boxes", core.tiffin_boxes, name="tiffin-boxes"),
    path(t + "driver/", core.driver, name="driver"),
    path(t + "admin/wallets", money.wallets, name="wallets"),
    path(t + "admin/wallet-customers/<int:sub_id>", money.wallet_customer, name="wallets-customer"),
    path(t + "admin/payment-setup", money.payment_setup, name="payment-setup"),
    path(t + "admin/invoices", money.invoices, name="invoices"),
    path(t + "admin/invoices/<str:inv>.pdf", money.invoice_pdf, name="invoices-pdf"),
    path(t + "admin/invoices/<str:inv>", money.invoice_detail, name="invoices-detail"),
    path(t + "admin/expenses", money.expenses, name="expenses"),
    path(t + "admin/expenses/profit", money.profit, name="expenses-profit"),
    path(t + "admin/menu", setup.menu, name="menu"),
    path(t + "admin/menu/planner", setup.planner, name="menu-planner"),
    path(t + "admin/plans/wallet", setup.wallet_plans, name="plans-wallet"),
    path(t + "admin/plans/wallet/new", setup.wallet_plan_form, name="plans-wallet-new"),
    path(t + "admin/subscriptions", setup.subscriptions, name="subscriptions"),
    path(t + "admin/subscriptions/new", setup.subscription_new, name="subscriptions-new"),
    path(t + "admin/subscriptions/<int:sub_id>", setup.subscription_detail, name="subscriptions-detail"),
    path(t + "admin/roles", setup.roles, name="roles"),
    path(t + "admin/branches", setup.branches, name="branches"),
    path(t + "admin/notifications", setup.notifications, name="notifications"),
    path(t + "admin/website", setup.website, name="website"),
    path(t + "admin/cloud-kitchen", setup.cloud_kitchen, name="cloud-kitchen"),
    path(t + "site", setup.public_site, name="site"),
    path(t + "me/meals", me.meals, name="me-meals"),
    path(t + "me/wallet", me.wallet, name="me-wallet"),
    path(t + "me/deliveries", me.deliveries, name="me-deliveries"),
    path(t + "me/invoices", me.invoices, name="me-invoices"),
    path(t + "me/invoices/<str:inv>.pdf", me.invoice_pdf, name="me-invoices-pdf"),
    path(t + "me/order", me.order_online, name="me-order"),
    path("platform/plans", setup.platform_plans, name="platform-plans"),
    path("signup", setup.signup_wizard, name="signup-wizard"),
]
