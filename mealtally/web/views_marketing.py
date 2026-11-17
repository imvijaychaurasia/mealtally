"""Public landing page, demo request form, privacy/terms drafts, sitemap and robots (D03.6 Part B). Platform-scoped: no tenant."""

from __future__ import annotations

import re

from django.conf import settings
from django.core.cache import cache
from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from mealtally.accounts.models import Membership
from mealtally.accounts.models import Role
from mealtally.common.country import normalize_phone
from mealtally.tenancy.context import platform_context
from mealtally.tenancy.models import DemoRequest

from . import features
from . import marketing
from .access import home_url

RATE_LIMIT = 5  # demo requests per hour per IP
RATE_WINDOW = 3600
HONEYPOT = "company_website"


def _ip(request) -> str:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")) or "unknown"


def dashboard_url(user) -> str:
    """Where a signed-in user's dashboard is (the landing page shows this instead of redirecting)."""
    if not getattr(user, "is_authenticated", False):
        return ""
    if user.is_platform_admin:
        return reverse("web:platform-dashboard")
    with platform_context():
        row = (
            Membership.objects.filter(user=user, is_active=True, tenant__status="ACTIVE")
            .order_by("-id")
            .values_list("tenant__slug", "role", "tenant__has_demo_dataset")
            .first()
        )
    if not row:
        return ""
    slug, role, demo = row
    return reverse("web:me-home", args=[slug]) if role == Role.CUSTOMER else home_url(slug, role, demo=demo)


def render_home(request, *, status=200, **extra):
    ctx = {
        "features": marketing.features(),
        "audiences": marketing.audiences(),
        "faq": marketing.FAQ,
        "trust": marketing.TRUST,
        "pricing": marketing.pricing(),
        "business_types": DemoRequest.BusinessType.choices,
        "dashboard_url": dashboard_url(request.user),
        "canonical": request.build_absolute_uri(reverse("web:landing")),
        "sent": request.GET.get("demo") == "sent",
        "form": {},
        "errors": {},
    }
    ctx.update(extra)
    return render(request, "web/marketing/home.html", ctx, status=status)


@require_GET
def landing(request):
    """The root URL. Marketing site when switched on; otherwise single mode goes straight to the restaurant and multi
    mode shows the restaurant finder."""
    if features.marketing():
        return render_home(request)
    if not features.multi():
        from mealtally.tenancy.models import Tenant  # noqa: PLC0415

        with platform_context():
            tenant = Tenant.objects.exclude(status=Tenant.Status.DEACTIVATED).order_by("id").first()
        if tenant is not None:
            return redirect("web:tenant-home", slug=tenant.slug)
        return render(request, "web/not_initialised.html", status=503)
    return render(request, "web/root_finder.html", {"dashboard_url": dashboard_url(request.user)})


def _clean(data) -> tuple[dict, dict]:
    form = {
        k: (data.get(k, "") or "").strip()
        for k in ("name", "business_name", "city", "phone", "business_type", "message")
    }
    errors = {}
    for key, label, limit in (
        ("name", _("your name"), 120),
        ("business_name", _("your business name"), 160),
        ("city", _("your city"), 80),
    ):
        if not form[key]:
            errors[key] = _("Please enter %(what)s.") % {"what": label}
        elif len(form[key]) > limit:
            errors[key] = _("That is too long.")
    try:
        form["phone_e164"] = normalize_phone(form["phone"])
    except Exception:  # noqa: BLE001  (ValidationFailed)
        errors["phone"] = _("Enter a valid phone number.")
    if form["business_type"] not in DemoRequest.BusinessType.values:
        errors["business_type"] = _("Choose a business type.")
    if len(form["message"]) > 1000:  # noqa: PLR2004
        errors["message"] = _("Please keep the message under 1000 characters.")
    if form["message"] and re.search(r"https?://", form["message"]):
        errors["message"] = _("Please leave links out of the message.")
    return form, errors


@require_POST
@features.requires(features.marketing)
def demo_request(request):
    if request.POST.get(HONEYPOT):  # a bot filled the hidden field: pretend it worked, store nothing
        return redirect(reverse("web:landing") + "?demo=sent#book-a-demo")
    key = f"demo-rate:{_ip(request)}"
    cache.add(key, 0, RATE_WINDOW)
    try:
        count = cache.incr(key)
    except ValueError:
        count, _unused = 1, cache.set(key, 1, RATE_WINDOW)
    if count > RATE_LIMIT:
        resp = render_home(
            request,
            status=429,
            errors={"all": _("Too many requests from this network. Please try again in an hour.")},
            form=request.POST,
        )
        resp["Retry-After"] = str(RATE_WINDOW)
        return resp
    form, errors = _clean(request.POST)
    if errors:
        return render_home(request, status=400, errors=errors, form=form)
    with platform_context():
        DemoRequest.objects.create(
            name=form["name"],
            business_name=form["business_name"],
            city=form["city"],
            phone=form["phone_e164"],
            business_type=form["business_type"],
            message=form["message"],
        )
    return redirect(reverse("web:landing") + "?demo=sent#book-a-demo")


def legal_pages_live() -> bool:
    """The legal pages exist only when switched on AND every required field is filled (never filler text)."""
    from mealtally.tenancy.models import PlatformSettings  # noqa: PLC0415

    if not settings.MEALTALLY_LEGAL_PAGES:
        return False
    with platform_context():
        return not PlatformSettings.load().missing_legal_fields()


def _legal_page(request, name: str, title: str):
    import markdown  # noqa: PLC0415

    from mealtally.tenancy.models import PlatformSettings  # noqa: PLC0415

    if not legal_pages_live():
        raise Http404
    with platform_context():
        cfg = PlatformSettings.load()
    # values are HTML-escaped by the template engine before Markdown sees them
    text = render_to_string(f"legal/{name}.md", {f: getattr(cfg, f) for f in PlatformSettings.LEGAL_FIELDS})
    body = mark_safe(markdown.markdown(text, output_format="html"))  # noqa: S308 (repo template + escaped values)
    return render(
        request,
        "web/legal_page.html",
        {"body": body, "title": title, "canonical": request.build_absolute_uri(request.path)},
    )


@require_GET
def privacy(request):
    return _legal_page(request, "privacy", _("Privacy notice"))


@require_GET
def terms(request):
    return _legal_page(request, "terms", _("Terms of use"))


@require_GET
def robots(request):
    if not features.marketing():  # an instance without a public site asks not to be indexed at all
        return HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain")
    lines = [
        "User-agent: *",
        "Allow: /$",
        "Allow: /privacy",
        "Disallow: /t/",
        "Disallow: /platform/",
        "Disallow: /api/",
        "Disallow: /accounts/",
        "Allow: /terms",
        "Disallow: /login",
        f"Sitemap: {request.build_absolute_uri(reverse('web:sitemap'))}",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


@require_GET
def sitemap(request):
    if not features.marketing():
        raise Http404
    urls = [request.build_absolute_uri(reverse("web:landing"))]
    if legal_pages_live():
        urls += [request.build_absolute_uri(reverse("web:privacy")), request.build_absolute_uri(reverse("web:terms"))]
    body = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'
    return HttpResponse(xml, content_type="application/xml")
