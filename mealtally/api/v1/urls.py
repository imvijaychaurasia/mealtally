from django.urls import include
from django.urls import path
from drf_spectacular.views import SpectacularAPIView
from drf_spectacular.views import SpectacularSwaggerView

from . import views_admin as adm
from . import views_auth
from . import views_me
from . import views_platform
from . import views_staff

tenant_patterns = [
    path("auth/customer/login", views_auth.CustomerLoginView.as_view(), name="customer-login"),
    path("auth/customer/logout", views_auth.LogoutView.as_view(), name="customer-logout"),
    # customer self-service
    path("me", views_me.MeView.as_view(), name="me"),
    path("me/ledger", views_me.MeLedgerView.as_view(), name="me-ledger"),
    path("me/payments", views_me.MePaymentsView.as_view(), name="me-payments"),
    path("me/qr-token", views_me.MeQrTokenView.as_view(), name="me-qr-token"),
    path("me/qr.svg", views_me.MeQrSvgView.as_view(), name="me-qr-svg"),
    # staff
    path("customers", views_staff.CustomerListCreateView.as_view(), name="customers"),
    path("customers/<uuid:customer_id>", views_staff.CustomerDetailView.as_view(), name="customer-detail"),
    path(
        "customers/<uuid:customer_id>/reset-pin", views_staff.CustomerResetPinView.as_view(), name="customer-reset-pin"
    ),
    path("plans", views_staff.PlanListView.as_view(), name="plans"),
    path("payments", views_staff.PaymentCreateView.as_view(), name="payments"),
    path("payments/<uuid:payment_id>/void", views_staff.PaymentVoidView.as_view(), name="payment-void"),
    path("redeem", views_staff.RedeemView.as_view(), name="redeem"),
    path("redeem/qr", views_staff.RedeemQrView.as_view(), name="redeem-qr"),
    path("ledger/<uuid:entry_id>/reverse", views_staff.LedgerReverseView.as_view(), name="ledger-reverse"),
    path("passes/<uuid:pass_id>/adjust", views_staff.PassAdjustView.as_view(), name="pass-adjust"),
    path("passes/<uuid:pass_id>/suspend", views_staff.PassSuspendView.as_view(), name="pass-suspend"),
    path("passes/<uuid:pass_id>/resume", views_staff.PassResumeView.as_view(), name="pass-resume"),
    path("passes/<uuid:pass_id>/cancel", views_staff.PassCancelView.as_view(), name="pass-cancel"),
    path("reports/daily", views_staff.DailyReportView.as_view(), name="report-daily"),
    path("auth/customer/signup", adm.CustomerSignupView.as_view(), name="customer-signup"),
    path("me/change-pin", adm.MeChangePinView.as_view(), name="me-change-pin"),
    path("customers/admin-list", adm.CustomerAdminListView.as_view(), name="customers-admin"),
    path("customers/<uuid:customer_id>/update", adm.CustomerUpdateView.as_view(), name="customer-update"),
    path("customers/<uuid:customer_id>/block", adm.CustomerBlockView.as_view(), name="customer-block"),
    path("customers/<uuid:customer_id>/unblock", adm.CustomerUnblockView.as_view(), name="customer-unblock"),
    path("customers/<uuid:customer_id>/statement", adm.CustomerStatementView.as_view(), name="customer-statement"),
    path("plans/manage", adm.PlanAdminView.as_view(), name="plans-manage"),
    path("plans/<uuid:plan_id>", adm.PlanDetailView.as_view(), name="plan-detail"),
    path("staff", adm.StaffListView.as_view(), name="staff"),
    path("staff/<int:user_id>/<str:action>", adm.StaffActionView.as_view(), name="staff-action"),
    path("settings", adm.SettingsView.as_view(), name="settings"),
    path("reports/dashboard", adm.DashboardView.as_view(), name="report-dashboard"),
    path("reports/daily-consumption", adm.DailyConsumptionView.as_view(), name="report-daily-consumption"),
    path("reports/monthly", adm.MonthlySubscriptionsView.as_view(), name="report-monthly"),
    path("reports/expired", adm.ExpiredUnusedView.as_view(), name="report-expired"),
    path("audit", adm.AuditLogView.as_view(), name="audit"),
    path("sales/preview", adm.SalePreviewView.as_view(), name="sales-preview"),
    path("payments/<uuid:payment_id>", adm.PaymentDetailView.as_view(), name="payment-detail"),
    path("payments/<uuid:payment_id>/receipt.pdf", adm.ReceiptPdfView.as_view(), name="payment-receipt-pdf"),
    path("reports/fees", views_staff.FeeReportView.as_view(), name="report-fees"),
]

platform_patterns = [
    path("tenants", views_platform.TenantListCreateView.as_view(), name="platform-tenants"),
    path("onboard", adm.PlatformOnboardView.as_view(), name="platform-onboard"),
    path("dashboard", adm.PlatformDashboardView.as_view(), name="platform-dashboard"),
    path("tenants/<slug:slug>/suspend", views_platform.TenantSuspendView.as_view(), name="platform-tenant-suspend"),
    path("tenants/<slug:slug>/activate", views_platform.TenantActivateView.as_view(), name="platform-tenant-activate"),
    path(
        "tenants/<slug:slug>/deactivate",
        views_platform.TenantDeactivateView.as_view(),
        name="platform-tenant-deactivate",
    ),
    path("tenants/<slug:slug>/fee-policy", views_platform.FeePolicyView.as_view(), name="platform-fee-policy"),
]

app_name = "v1"
urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api:v1:schema"), name="docs"),
    path("auth/csrf", views_auth.CsrfView.as_view(), name="csrf"),
    path("auth/login", views_auth.StaffLoginView.as_view(), name="login"),
    path("auth/logout", views_auth.LogoutView.as_view(), name="logout"),
    path("auth/change-password", adm.ChangePasswordView.as_view(), name="change-password"),
    path("platform/", include(platform_patterns)),
    path("t/<slug:tenant_slug>/", include(tenant_patterns)),
]
