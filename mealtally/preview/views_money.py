# SPDX-License-Identifier: AGPL-3.0-only
"""Preview: wallets & top-ups, invoices (PDF real from demo data), expenses & profit, payment setup."""

from __future__ import annotations

from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET

from mealtally.common import country

from . import data
from . import util
from .access import preview_view


@preview_view("wallets")
@require_GET
def wallets(request, D):
    pending = [t for t in D["topups"] if t["status"] == "PENDING"]
    subs = sorted(D["subscribers"], key=lambda s: s["balance_minor"])
    total = sum(s["balance_minor"] for s in D["subscribers"])
    return render(
        request,
        "preview/wallets.html",
        {
            "D": D,
            "topups": D["topups"],
            "pending": pending,
            "subs": subs,
            "total": total,
            "low": len([s for s in subs if s["days_left"] <= 3 and s["status"] == "ACTIVE"]),
            "negative": len([s for s in subs if s["balance_minor"] < 0]),
        },
    )


@preview_view("wallets")
@require_GET
def wallet_customer(request, D, sub_id):
    s = D["sub"].get(sub_id)
    if s is None:
        raise Http404
    ledger = list(reversed(D["ledgers"][sub_id]))[:60]
    orders = data.sub_orders(D, sub_id, limit=15)
    return render(
        request,
        "preview/wallet_customer.html",
        {
            "D": D,
            "s": s,
            "plan": D["wplan"][s["plan"]],
            "ledger": ledger,
            "orders": orders,
            "lifetime": len([o for o in D["orders"] if o["sub_id"] == sub_id and o["off"] <= 0]),
            "boxes": s["tiffin_boxes"],
            "invoices": [i for i in D["invoices"] if i["sub_id"] == sub_id],
            "cycle_minor": D["wplan"][s["plan"]]["monthly_minor"],
            "branch": D["branches"][0]["name"],
        },
    )


@preview_view("payment-setup")
@require_GET
def payment_setup(request, D):
    return render(
        request, "preview/payment_setup.html", {"D": D, "cfg_vpa": D["website"]["domain"].split(".")[0] + "@upi"}
    )


@preview_view("invoices")
@require_GET
def invoices(request, D):
    return render(
        request,
        "preview/invoices.html",
        {
            "D": D,
            "invoices": D["invoices"],
            "month": D["invoices"][0]["month"] if D["invoices"] else "",
            "due": sum(i["total_minor"] for i in D["invoices"] if i["status"] == "DUE"),
            "paid": sum(i["total_minor"] for i in D["invoices"] if i["status"] == "PAID"),
        },
    )


@preview_view("invoices")
@require_GET
def invoice_detail(request, D, inv):
    i = D["invoice"].get(inv)
    if i is None:
        raise Http404
    return render(request, "preview/invoice_detail.html", {"D": D, "i": i, "share": request.build_absolute_uri()})


@preview_view("invoices")
@require_GET
def invoice_pdf(request, D, inv):
    i = D["invoice"].get(inv)
    if i is None:
        raise Http404
    return render_invoice_pdf(request, D, i)


def render_invoice_pdf(request, D, i):
    from weasyprint import HTML  # noqa: PLC0415 (heavy import, only when a PDF is requested)

    html = render_to_string(
        "preview/invoice_pdf.html",
        {
            "D": D,
            "i": i,
            "cfg": request.cfg,
            "tenant": request.tenant,
            "licence_label": country.food_licence_label(request.tenant.country),
        },
    )
    resp = HttpResponse(HTML(string=html, base_url=None).write_pdf(), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{i["id"]}.pdf"'
    return resp


@preview_view("expenses")
@require_GET
def expenses(request, D):
    from .views_core import _passes_30d  # noqa: PLC0415

    _months, _last, exps, recurring = util.money_series(D, _passes_30d(D))
    cats = sorted({e["category"] for e in exps})
    total = sum(e["amount_minor"] for e in exps if (D["today"] - e["date"]).days < 30)
    return render(
        request,
        "preview/expenses.html",
        {"D": D, "expenses": exps, "cats": cats, "recurring": recurring, "total30": total},
    )


@preview_view("expenses")
@require_GET
def profit(request, D):
    from .views_core import _passes_30d  # noqa: PLC0415

    months, last, exps, _rec = util.money_series(D, _passes_30d(D))
    m, passes, wallet = months[-1], last["passes"], last["wallet"]
    margin = round(100 * m["profit_minor"] / m["revenue_minor"], 1)
    by_cat: dict = {}
    for e in exps:
        if (D["today"] - e["date"]).days < 30:
            by_cat[e["category"]] = by_cat.get(e["category"], 0) + e["amount_minor"]
    return render(
        request,
        "preview/profit.html",
        {
            "D": D,
            "m": m,
            "passes": passes,
            "wallet": wallet,
            "margin": margin,
            "months": months,
            "by_cat": sorted(by_cat.items(), key=lambda kv: -kv[1]),
        },
    )
