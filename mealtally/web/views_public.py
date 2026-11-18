# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import time

from django.contrib.auth import login
from django.contrib.auth import logout
from django.http import HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from mealtally.accounts import services as accounts
from mealtally.accounts.models import Membership
from mealtally.accounts.models import Role
from mealtally.api.v1.views_auth import authenticate_with_lockout
from mealtally.common.errors import DomainError
from mealtally.customers import services as customers
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.models import Tenant
from mealtally.web.redirects import safe_next

from .access import home_url
from .access import tenant_view
from .copy import friendly

STAFF_SESSION_SECONDS = 12 * 3600
CUSTOMER_SESSION_SECONDS = 30 * 24 * 3600


def _safe_next(request, fallback):
    return safe_next(request, request.POST.get("next") or request.GET.get("next") or "", fallback)


@require_GET
def landing(request):
    return render(request, "web/landing.html")


@require_POST
def go(request):
    code = slugify(request.POST.get("code", ""))
    if not code:
        from . import features  # noqa: PLC0415
        from .views_marketing import render_home  # noqa: PLC0415

        error = _("Enter your restaurant code.")
        if features.marketing():
            return render_home(request, status=400, go_error=error)
        return render(request, "web/root_finder.html", {"go_error": error}, status=400)
    return redirect("web:tenant-home", slug=code)


@require_http_methods(["GET", "POST"])
def global_login(request):
    """Staff login without knowing the restaurant: picks the tenant for you."""
    if request.method == "GET":
        return render(request, "web/global_login.html", {"next": request.GET.get("next", "")})
    try:
        user = authenticate_with_lockout(
            request, login=request.POST.get("login", ""), password=request.POST.get("password", "")
        )
    except DomainError as exc:
        return render(request, "web/global_login.html", {"error": friendly(exc)}, status=400)
    login(request, user, backend="mealtally.accounts.backends.IdentifierPasswordBackend")
    request.session.set_expiry(STAFF_SESSION_SECONDS)
    if user.is_platform_admin:
        return redirect("web:platform-dashboard")
    with platform_context():
        rows = list(
            Membership.objects.filter(user=user, is_active=True, tenant__status="ACTIVE")
            .exclude(role=Role.CUSTOMER)
            .values_list("tenant__slug", "tenant__name", "role")
        )
        demo_slugs = set(Tenant.objects.filter(has_demo_dataset=True).values_list("slug", flat=True))
    by_slug: dict = {}
    for slug, name, role in rows:
        best = accounts.effective_role([role, by_slug.get(slug, ("", ""))[1]]) if slug in by_slug else role
        by_slug[slug] = (name, best)
    if not by_slug:
        logout(request)
        return render(
            request,
            "web/global_login.html",
            {"error": _("This account has no staff access to any restaurant.")},
            status=403,
        )
    if len(by_slug) == 1:
        slug, (_name, role) = next(iter(by_slug.items()))
        return redirect(home_url(slug, role, demo=slug in demo_slugs))
    choices = [
        {"slug": s, "name": n, "role": Role(r).label, "url": home_url(s, r, demo=s in demo_slugs)}
        for s, (n, r) in sorted(by_slug.items())
    ]
    return render(request, "web/tenant_picker.html", {"choices": choices})


@tenant_view(public=True)
@require_GET
def tenant_home(request):
    if request.user.is_authenticated and request.role:
        return redirect(home_url(request.tenant.slug, request.role, demo=request.tenant.has_demo_dataset))
    return render(request, "web/tenant_home.html", {"next": request.GET.get("next", "")})


@tenant_view(public=True)
@require_http_methods(["GET", "POST"])
def login_customer(request):
    ctx = {"next": request.POST.get("next") or request.GET.get("next", "")}
    if request.method == "GET":
        return render(request, "web/login_customer.html", ctx)
    phone = request.POST.get("phone", "")
    try:
        user = authenticate_with_lockout(
            request, tenant_slug=request.tenant.slug, phone=phone, password=request.POST.get("pin", "")
        )
    except DomainError as exc:
        return render(request, "web/login_customer.html", {**ctx, "error": friendly(exc), "phone": phone}, status=400)
    login(request, user, backend="mealtally.accounts.backends.CustomerPinBackend")
    request.session.set_expiry(CUSTOMER_SESSION_SECONDS)
    request.session["pin_login_at"] = time.time()
    return redirect(_safe_next(request, reverse("web:me-home", args=[request.tenant.slug])))


@tenant_view(public=True)
@require_http_methods(["GET", "POST"])
def login_staff(request):
    ctx = {"next": request.POST.get("next") or request.GET.get("next", "")}
    if request.method == "GET":
        return render(request, "web/login_staff.html", ctx)
    ident = request.POST.get("login", "")
    try:
        user = authenticate_with_lockout(request, login=ident, password=request.POST.get("password", ""))
    except DomainError as exc:
        return render(request, "web/login_staff.html", {**ctx, "error": friendly(exc), "login": ident}, status=400)
    roles = [r for r in accounts.active_roles(user=user, tenant_id=request.tenant.id) if r != Role.CUSTOMER]
    role = accounts.effective_role(roles)
    if role is None:
        return render(
            request,
            "web/login_staff.html",
            {**ctx, "error": _("This account does not have staff access here."), "login": ident},
            status=403,
        )
    login(request, user, backend="mealtally.accounts.backends.IdentifierPasswordBackend")
    request.session.set_expiry(STAFF_SESSION_SECONDS)
    return redirect(_safe_next(request, home_url(request.tenant.slug, role, demo=request.tenant.has_demo_dataset)))


@tenant_view(public=True)
@require_http_methods(["GET", "POST"])
def signup(request):
    if not request.cfg.allow_self_signup:
        return render(request, "web/signup_closed.html", status=404)
    if request.method == "GET":
        return render(request, "web/signup.html")
    data = request.POST
    try:
        customers.self_signup(
            tenant_id=request.tenant.id,
            full_name=data.get("full_name", ""),
            phone=data.get("phone", ""),
            pin=data.get("pin", ""),
        )
    except DomainError as exc:
        return render(request, "web/signup.html", {"error": friendly(exc), "form": data}, status=400)
    return render(request, "web/signup_done.html")


@require_POST
def logout_view(request):
    slug = request.POST.get("slug", "")
    logout(request)
    return redirect("web:tenant-home", slug=slug) if slug else redirect("web:landing")


@tenant_view(public=True)
@require_GET
def brand_css(request):
    colour = request.cfg.brand_color
    response = HttpResponse(f":root{{--brand:{colour};}}", content_type="text/css")
    response["Cache-Control"] = "public, max-age=300"
    return response


@require_GET
def manifest(request):
    import json  # noqa: PLC0415

    from . import themes  # noqa: PLC0415

    wanted = request.GET.get("theme", "")
    tok = themes.tokens(wanted if wanted in themes.THEMES else themes.PLATFORM)
    data = {
        "name": "Mealtally",
        "short_name": "Mealtally",
        "start_url": "/",
        "display": "standalone",
        "background_color": tok["card"],
        "theme_color": tok["primary"],
        "icons": [
            {"src": "/static/brand/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/brand/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/brand/app-icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return HttpResponse(json.dumps(data), content_type="application/manifest+json")


@require_POST
def dismiss_http_notice(request):
    """Hide the plain-HTTP notice for the rest of this session."""
    request.session["http_notice_dismissed"] = True
    return redirect(safe_next(request, request.POST.get("next", "/"), "/"))


@require_GET
def service_worker(request):
    """Minimal SW: shows /offline/ only when a GET page load cannot reach the server at all (a network failure).

    Any response the server gives -- 200, 302, 404, 405, 500 -- is shown as it is: never "You're offline".
    POST navigations (form resubmits on Back) are left entirely to the browser. Nothing is cached but the offline page.
    """
    js = (
        "const C='mealtally-offline-v2';\n"
        "self.addEventListener('install',e=>{e.waitUntil(caches.open(C).then(c=>c.add('/offline/')));self.skipWaiting();});\n"
        "self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C)"
        ".map(k=>caches.delete(k)))).then(()=>self.clients.claim()));});\n"
        "self.addEventListener('fetch',e=>{const r=e.request;if(r.mode!=='navigate'||r.method!=='GET')return;"
        "e.respondWith(fetch(r).catch(err=>caches.match('/offline/').then(p=>p||Promise.reject(err))));});\n"
    )
    response = HttpResponse(js, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


@require_GET
def offline(request):
    return render(request, "web/offline.html")
