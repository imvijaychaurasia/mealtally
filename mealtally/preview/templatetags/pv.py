# SPDX-License-Identifier: AGPL-3.0-only
"""Preview template helpers: chips, SVG charts (server-rendered: nothing inline, nothing to load)."""

from __future__ import annotations

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from mealtally.common.money import format_money
from mealtally.common.money import format_money_compact as money_compact

register = template.Library()

STATUS_CHIP = {
    "RECEIVED": ("Scheduled", "chip-expired"),
    "CONFIRMED": ("Confirmed", "chip-soon"),
    "PREPARING": ("Preparing", "chip-soon"),
    "READY": ("Ready", "chip-active"),
    "OUT_FOR_DELIVERY": ("Out for delivery", "chip-soon"),
    "DELIVERED": ("Delivered", "chip-active"),
    "PICKED_UP": ("Picked up", "chip-active"),
    "SKIPPED": ("Skipped", "chip-expired"),
    "SKIPPED_HOLD": ("On hold", "chip-expired"),
    "SKIPPED_LOW_WALLET": ("Skipped · low wallet", "chip-void"),
    "CANCELLED": ("Cancelled", "chip-void"),
    "ACTIVE": ("Active", "chip-active"),
    "PAUSED": ("Paused", "chip-soon"),
    "CANCELLED_SUB": ("Cancelled", "chip-void"),
    "EXPIRED": ("Expired", "chip-expired"),
    "PENDING": ("Pending", "chip-soon"),
    "APPROVED": ("Approved", "chip-active"),
    "REJECTED": ("Rejected", "chip-void"),
    "ACCEPTED": ("Accepted", "chip-active"),
    "PAID": ("Paid", "chip-active"),
    "DUE": ("Due", "chip-soon"),
    "VEG": ("Veg", "chip-green"),
    "NONVEG": ("Non-veg", "chip-red"),
    "VEGAN": ("Vegan", "chip-green"),
    "JAIN": ("Jain", "chip-amber"),
    "CREDIT": ("Credit", "chip-green"),
    "DEBIT": ("Debit", "chip-slate"),
}


@register.simple_tag
def chip(status):
    label, cls = STATUS_CHIP.get(status, (str(status).title(), "chip-slate"))
    return format_html('<span class="{}" data-chip data-status="{}">{}</span>', cls, status, label)


@register.filter
def signed_inr(minor):
    minor = minor or 0
    return ("−" if minor < 0 else "+") + format_money(abs(minor))


@register.filter
def raw_amount(minor):
    """Machine-readable integer minor units for JS data attributes. Never shown to people."""
    return str(int(minor or 0))


@register.filter
def getitem(mapping, key):
    try:
        return mapping[key]
    except KeyError, TypeError, IndexError:
        return ""


@register.filter
def money_class(minor):
    return "text-danger-ink" if (minor or 0) < 0 else "text-ink"


@register.filter
def initials(name):
    return "".join(p[0] for p in str(name).split()[:2]).upper()


@register.filter
def phone_last4(phone):
    return "••••• " + str(phone).replace(" ", "")[-4:]


@register.filter
def lakh(minor):
    """Axis label, one unit style: under a lakh in k, from a lakh in L (1.2L). 0 -> ₹0."""
    return money_compact(minor)


def nice_ticks(top_major: float, n: int = 4):
    """Round tick values 0..N*step where step is a 'nice' number (10k, 20k, 25k, 40k, 50k, 1L ...)."""
    for step in (10000, 20000, 25000, 40000, 50000, 100000, 200000, 250000, 400000, 500000, 1000000):
        if step * n >= top_major:
            return [step * i for i in range(n + 1)]
    return [int(top_major / n) * i for i in range(n + 1)]


@register.simple_tag
def bar_chart(months):
    """Revenue / expense bars + profit line, as inline SVG with a text alternative."""
    w, h, pad = 640, 220, 34
    ticks = nice_ticks(max(m["revenue_minor"] for m in months) / 100 * 1.02)
    top = ticks[-1] * 100
    n = len(months)
    step = (w - 2 * pad) / n
    parts = [
        f'<svg viewBox="0 -14 {w} {h + 42}" role="img" class="w-full" aria-label="Revenue, expenses and profit, last 12 months">'
    ]
    for g, t in enumerate(ticks):
        y = h - h * g / (len(ticks) - 1)
        parts.append(f'<line x1="{pad}" x2="{w - pad}" y1="{y:.0f}" y2="{y:.0f}" class="stroke-subtle"/>')
        parts.append(f'<text x="2" y="{y + 4:.0f}" font-size="10" class="fill-muted">{lakh(t * 100)}</text>')
    pts = []
    for i, m in enumerate(months):
        x = pad + i * step + step * 0.12
        bw = step * 0.34
        rh, eh = h * m["revenue_minor"] / top, h * m["expense_minor"] / top
        parts.append(
            f'<rect x="{x:.0f}" y="{h - rh:.0f}" width="{bw:.0f}" height="{rh:.0f}" rx="2" class="fill-primary"/>'
        )
        parts.append(
            f'<rect x="{x + bw + 2:.0f}" y="{h - eh:.0f}" width="{bw:.0f}" height="{eh:.0f}" rx="2" class="fill-accent"/>'
        )
        ph = h * m["profit_minor"] / top
        pts.append(f"{x + bw:.0f},{h - ph:.0f}")
        parts.append(
            f'<text x="{x + bw:.0f}" y="{h + 16}" font-size="10" text-anchor="middle" class="fill-muted">{m["label"]}</text>'
        )
    parts.append(f'<polyline points="{" ".join(pts)}" fill="none" class="stroke-ink" stroke-width="2"/>')
    parts.append("</svg>")
    return mark_safe("".join(parts))  # noqa: S308 (built from our own numbers only)


# classes assembled dynamically below (kept literal so the Tailwind scanner emits them):
# fill-primary fill-accent fill-tile-1 fill-muted bg-primary bg-accent bg-tile-1 bg-muted


@register.simple_tag
def split_bar(pickup, delivery, dine_in):
    return donut([pickup, delivery, dine_in], ["Pick-up", "Delivery", "Dine-in (counter)"])


def donut(values, labels):
    """Simple stacked horizontal bar (pickup / delivery / dine-in) with legend."""
    total = sum(values) or 1
    colors = ["primary", "accent", "tile-1", "muted"]
    x = 0
    out = ['<svg viewBox="0 0 300 18" class="w-full" role="img" aria-label="Split">']
    for v, c in zip(values, colors, strict=False):
        wd = 300 * v / total
        out.append(f'<rect x="{x:.1f}" y="0" width="{wd:.1f}" height="18" class="fill-{c}"/>')
        x += wd
    out.append("</svg><ul class='mt-2 flex flex-wrap gap-x-4 text-sm text-ink-soft'>")
    for v, lab, c in zip(values, labels, colors, strict=False):
        out.append(f"<li><span class='mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-{c}'></span>{lab} {v}</li>")
    out.append("</ul>")
    return mark_safe("".join(out))  # noqa: S308


@register.simple_tag
def line_chart(months):
    """D03.4 dashboard: revenue / expenses / profit as three lines with L/K ticks. Colours come from theme tokens (classes)."""
    w, h, left, bottom = 640, 230, 46, 26
    ticks = nice_ticks(max(m["revenue_minor"] for m in months) / 100 * 1.02)
    top = ticks[-1] * 100
    n = len(months)
    step = (w - left - 10) / (n - 1)
    parts = [
        (
            f'<svg viewBox="0 0 {w} {h + bottom}" role="img" class="w-full" '
            'aria-label="Revenue, expenses and profit, last 12 months">'
        )
    ]
    for g, t in enumerate(ticks):
        y = 8 + (h - 8) * (1 - g / (len(ticks) - 1))
        parts.append(f'<line x1="{left}" x2="{w - 6}" y1="{y:.0f}" y2="{y:.0f}" class="stroke-subtle"/>')
        parts.append(
            f'<text x="{left - 6}" y="{y + 4:.0f}" font-size="11" text-anchor="end" class="fill-muted">{lakh(t * 100)}</text>'
        )
    series = (
        ("revenue_minor", "stroke-primary", "fill-primary"),
        ("expense_minor", "stroke-tile-4", "fill-tile-4"),
        ("profit_minor", "stroke-chart-3", "fill-chart-3"),
    )
    for key, stroke, fill in series:
        pts = [(left + i * step, 8 + (h - 8) * (1 - m[key] / top)) for i, m in enumerate(months)]
        coords = " ".join(f"{x:.0f},{y:.0f}" for x, y in pts)
        parts.append(
            f'<polyline points="{coords}" fill="none" stroke-width="2.5" stroke-linejoin="round" class="{stroke}"/>'
        )
        x, y = pts[-1]
        parts.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="4" class="{fill}"/>')
    for i, m in enumerate(months):
        if i % 2 == 0 or i == n - 1:
            parts.append(
                f'<text x="{left + i * step:.0f}" y="{h + 18}" font-size="11" text-anchor="middle" '
                f'class="fill-muted">{m["label"]}</text>'
            )
    parts.append("</svg>")
    return mark_safe("".join(parts))  # noqa: S308 (our own numbers only)


@register.simple_tag
def donut_chart(delivered, pending):
    """Today's deliveries: delivered vs pending, total in the middle."""
    total = delivered + pending
    r = 52
    circ = 2 * 3.14159265 * r
    done = circ * (delivered / total) if total else 0
    return mark_safe(  # noqa: S308
        f'<svg viewBox="0 0 140 140" role="img" class="mx-auto h-44 w-44" aria-label="{delivered} of {total} delivered">'
        f'<circle cx="70" cy="70" r="{r}" fill="none" stroke-width="16" class="stroke-chart-pending"/>'
        f'<circle cx="70" cy="70" r="{r}" fill="none" stroke-width="16" class="stroke-primary" '
        f'stroke-dasharray="{done:.1f} {circ:.1f}" transform="rotate(-90 70 70)"/>'
        f'<text x="70" y="66" text-anchor="middle" font-size="11" class="fill-muted">Today total</text>'
        f'<text x="70" y="90" text-anchor="middle" font-size="26" font-weight="700" class="fill-ink">{total}</text></svg>'
    )
