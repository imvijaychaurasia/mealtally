from django.urls import path

from . import views_admin as adm
from . import views_customer as cus
from . import views_marketing as mk
from . import views_platform as plat
from . import views_public as pub
from . import views_staff as stf

app_name = "web"

t = "t/<slug:slug>/"
urlpatterns = [
    path("", mk.landing, name="landing"),
    path("demo-request", mk.demo_request, name="demo-request"),
    path("privacy", mk.privacy, name="privacy"),
    path("terms", mk.terms, name="terms"),
    path("robots.txt", mk.robots, name="robots"),
    path("sitemap.xml", mk.sitemap, name="sitemap"),
    path("go", pub.go, name="go"),
    path("login", pub.global_login, name="global-login"),
    path("logout", pub.logout_view, name="logout"),
    path("offline/", pub.offline, name="offline"),
    path("sw.js", pub.service_worker, name="sw"),
    path("dismiss-http-notice", pub.dismiss_http_notice, name="dismiss-http-notice"),
    path("manifest.webmanifest", pub.manifest, name="manifest"),
    # platform
    path("platform/", plat.dashboard, name="platform-dashboard"),
    path("platform/onboard/", plat.onboard, name="platform-onboard"),
    path("platform/tenants/<slug:slug>", plat.tenant_detail, name="platform-tenant"),
    path("platform/tenants/<slug:slug>/fees", plat.tenant_fees_export, name="platform-tenant-fees"),
    path("platform/tenants/<slug:slug>/flags", plat.tenant_flags, name="platform-tenant-flags"),
    path("platform/tenants/<slug:slug>/fee-policy", plat.tenant_fee_policy, name="platform-tenant-fee-policy"),
    path("platform/tenants/<slug:slug>/status/<str:action>", plat.tenant_status, name="platform-tenant-status"),
    # tenant public
    path(t, pub.tenant_home, name="tenant-home"),
    path(t + "brand.css", pub.brand_css, name="brand-css"),
    path(t + "login/customer", pub.login_customer, name="login-customer"),
    path(t + "login/staff", pub.login_staff, name="login-staff"),
    path(t + "signup", pub.signup, name="signup"),
    path(t + "password", adm.staff_password, name="staff-password"),
    # receipts
    path(t + "receipt/<uuid:payment_id>", cus.receipt_html, name="receipt"),
    path(t + "receipt/<uuid:payment_id>.pdf", cus.receipt_pdf, name="receipt-pdf"),
    # customer app
    path(t + "me/", cus.me_home, name="me-home"),
    path(t + "me/qr", cus.me_qr, name="me-qr"),
    path(t + "me/qr/fragment", cus.me_qr_fragment, name="me-qr-fragment"),
    path(t + "me/activity", cus.me_activity, name="me-activity"),
    path(t + "me/account", cus.me_account, name="me-account"),
    path(t + "me/wallet/topup", cus.me_topup_check, name="me-topup-check"),
    path(t + "me/history", cus.me_history, name="me-history"),
    path(t + "me/payments", cus.me_payments, name="me-payments"),
    path(t + "me/profile", cus.me_profile, name="me-profile"),
    path(t + "me/pin", cus.me_pin, name="me-pin"),
    # staff
    path(t + "staff/", stf.console, name="staff-console"),
    path(t + "staff/search", stf.search, name="staff-search"),
    path(t + "staff/card/<uuid:customer_id>", stf.card, name="staff-card"),
    path(t + "staff/card-reset", stf.card_reset, name="staff-card-reset"),
    path(t + "staff/today", stf.today, name="staff-today"),
    path(t + "staff/redeem", stf.redeem, name="staff-redeem"),
    path(t + "staff/scan", stf.scan, name="staff-scan"),
    path(t + "staff/undo", stf.undo, name="staff-undo"),
    path(t + "staff/reverse", stf.reverse, name="staff-reverse"),
    path(t + "staff/sell", stf.sell, name="staff-sell"),
    path(t + "staff/sell/search", stf.sell_search, name="staff-sell-search"),
    path(t + "staff/sell/preview", stf.sell_preview, name="staff-sell-preview"),
    path(t + "staff/sell/confirm", stf.sell_confirm, name="staff-sell-confirm"),
    path(t + "staff/customers", stf.customers_lookup, name="staff-customers"),
    path(t + "staff/customers/new", stf.customer_new, name="staff-customer-new"),
    # admin
    path(t + "admin/", adm.dashboard, name="admin-dashboard"),
    path(t + "admin/more", adm.more, name="admin-more"),
    path(t + "admin/customers", adm.customer_list, name="admin-customers"),
    path(t + "admin/customers/<uuid:customer_id>", adm.customer_detail, name="admin-customer"),
    path(t + "admin/customers/<uuid:customer_id>/<str:action>", adm.customer_action, name="admin-customer-action"),
    path(t + "admin/plans", adm.plan_list, name="admin-plans"),
    path(t + "admin/plans/new", adm.plan_form, name="admin-plan-new"),
    path(t + "admin/plans/<uuid:plan_id>", adm.plan_form, name="admin-plan-edit"),
    path(t + "admin/staff", adm.staff_list, name="admin-staff"),
    path(t + "admin/staff/<int:user_id>/<str:action>", adm.staff_action, name="admin-staff-action"),
    path(t + "admin/settings", adm.settings_view, name="admin-settings"),
    path(t + "admin/settings/theme", adm.theme_set_view, name="admin-settings-theme"),
    path(t + "admin/settings/meal-times", adm.meal_times, name="admin-meal-times"),
    path(t + "admin/drivers/assign", adm.driver_assign, name="admin-driver-assign"),
    path(t + "admin/settings/meal-rules-banner", adm.meal_rules_banner, name="admin-meal-rules-banner"),
    path(t + "admin/reports", adm.reports_index, name="admin-reports"),
    path(t + "admin/reports/daily", adm.report_daily, name="report-daily"),
    path(t + "admin/reports/monthly", adm.report_monthly, name="report-monthly"),
    path(t + "admin/reports/expired", adm.report_expired, name="report-expired"),
    path(t + "admin/reports/statement/<uuid:customer_id>", adm.report_statement, name="report-statement"),
    path(t + "admin/reports/fees", adm.report_fees, name="report-fees"),
    path(t + "admin/reports/refused", adm.report_refused, name="report-refused"),
    path(t + "admin/audit", adm.audit_view, name="admin-audit"),
]
