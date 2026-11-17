# SPDX-License-Identifier: AGPL-3.0-only
"""Preview: menu, wallet plans, subscriptions, roles, branches, notifications, website, cloud kitchen, platform plans, sign-up."""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from mealtally.web.views_platform import platform_view

from . import data
from .access import preview_view


@preview_view("menu")
@require_GET
def menu(request, D):
    return render(
        request,
        "preview/menu.html",
        {"D": D, "slots": D["slots"], "dishes": D["dishes"], "diets": ["VEG", "NONVEG", "VEGAN", "JAIN"]},
    )


@preview_view("menu")
@require_GET
def planner(request, D):
    pid = request.GET.get("plan") or "HT-LD"
    plan = D["wplan"].get(pid) or D["wplan"]["HT-LD"]
    grid = []
    for slot in D["slots"]:
        if slot["key"] not in plan["slots"] and slot["key"] != "BREAKFAST":
            continue
        row = {"slot": slot, "days": []}
        for wd in range(6):
            opts = plan["menu"][wd].get(slot["key"], [])
            row["days"].append(opts)
        grid.append(row)
    return render(
        request,
        "preview/planner.html",
        {
            "D": D,
            "plan": plan,
            "plans": D["wallet_plans"],
            "grid": grid,
            "days": D["weekdays"][:6],
            "dishes": D["dishes"],
        },
    )


@preview_view("plans")
@require_GET
def wallet_plans(request, D):
    return render(request, "preview/wallet_plans.html", {"D": D, "plans": D["wallet_plans"]})


@preview_view("plans")
@require_GET
def wallet_plan_form(request, D):
    return render(
        request,
        "preview/wallet_plan_form.html",
        {"D": D, "days": list(enumerate(D["weekdays"])), "dishes": D["dishes"], "slots": D["slots"]},
    )


@preview_view("subscriptions")
@require_GET
def subscriptions(request, D):
    return render(request, "preview/subscriptions.html", {"D": D, "subs": D["subscribers"]})


@preview_view("subscriptions")
@require_GET
def subscription_new(request, D):
    return render(
        request,
        "preview/subscription_new.html",
        {
            "D": D,
            "days": list(enumerate(D["weekdays"])),
            "customers": D["subscribers"],
            "today": D["today"].isoformat(),
        },
    )


@preview_view("subscriptions")
@require_GET
def subscription_detail(request, D, sub_id):
    s = D["sub"].get(sub_id)
    if s is None:
        raise Http404
    plan = D["wplan"][s["plan"]]
    return render(
        request,
        "preview/subscription_detail.html",
        {
            "D": D,
            "s": s,
            "plan": plan,
            "weekday_qty": [(D["weekdays"][wd], s["qty"].get(wd, 0)) for wd in range(7)],
            "holds": [h for h in D["holds"] if h["sub_id"] == sub_id],
            "recent": data.sub_orders(D, sub_id, limit=6),
            "cycle_minor": plan["monthly_minor"] if s["billing"] == "MONTHLY" else plan["weekly_minor"],
            "today": D["today"].isoformat(),
        },
    )


@preview_view("roles")
@require_GET
def roles(request, D):
    preset = request.GET.get("preset") or "Manager"
    if preset not in D["perm_presets"]:
        preset = "Manager"
    return render(
        request,
        "preview/roles.html",
        {
            "D": D,
            "presets": list(D["perm_presets"]),
            "preset": preset,
            "matrix": D["perm_presets"][preset],
            "modules": D["perm_modules"],
            "acts": D["perm_acts"],
        },
    )


@preview_view("branches")
@require_GET
def branches(request, D):
    return render(request, "preview/branches.html", {"D": D, "branches": D["branches"]})


@preview_view("notifications")
@require_GET
def notifications(request, D):
    return render(
        request,
        "preview/notifications.html",
        {"D": D, "events": D["events"], "placeholders": D["placeholders"], "bell": D["bell"]},
    )


@preview_view("website")
@require_GET
def website(request, D):
    return render(
        request,
        "preview/website.html",
        {
            "D": D,
            "w": D["website"],
            "tabs": [
                ("domain", "Domain"),
                ("theme", "Theme"),
                ("content", "Content sections"),
                ("seo", "SEO"),
                ("policies", "Policies"),
            ],
        },
    )


@preview_view("cloud-kitchen")
@require_GET
def cloud_kitchen(request, D):
    return render(
        request,
        "preview/cloud_kitchen.html",
        {"D": D, "items": D["ck_items"], "rules": D["ck_rules"], "orders": D["ck_orders"]},
    )


@preview_view("website", public=True, roles=())
@require_GET
def public_site(request, D):
    plans = D["wallet_plans"]
    day = D["today"]
    menu_week = [{"day": D["weekdays"][wd], "lunch": plans[0]["menu"][wd]["LUNCH"]} for wd in range(6)]
    return render(
        request,
        "preview/site.html",
        {
            "D": D,
            "w": D["website"],
            "plans": plans,
            "menu_week": menu_week,
            "day": day,
            "branch": D["branches"][0],
            "theme": _preview_theme(request),
        },
    )


def _theme_choices():
    from mealtally.web.themes import THEMES  # noqa: PLC0415

    return [(key, label, desc) for key, (label, desc) in THEMES.items()]


def _preview_theme(request):
    from mealtally.web.themes import THEMES  # noqa: PLC0415

    wanted = request.GET.get("theme", "")
    return wanted if wanted in THEMES else request.tenant.theme


@platform_view
@require_GET
def platform_plans(request):
    from .data import SEED  # noqa: F401, PLC0415

    return render(request, "preview/platform_plans.html", {"plans": data.get(util_today())["saas_plans"]})


def util_today():
    from django.utils import timezone  # noqa: PLC0415

    return timezone.localdate()


@require_GET
def signup_wizard(request):
    return render(request, "preview/signup_wizard.html", {})
