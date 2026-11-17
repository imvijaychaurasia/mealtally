# SPDX-License-Identifier: AGPL-3.0-only
"""Template filters available everywhere (registered as builtins)."""

from django import template
from django.utils.translation import gettext_lazy as _

from mealtally.common.country import format_phone
from mealtally.common.country import mask_phone
from mealtally.common.money import format_money
from mealtally.common.money import format_money_compact as _money_compact
from mealtally.common.money import per_meal as per_meal_price

register = template.Library()


@register.simple_tag
def theme_css(tenant):
    """``:root{--primary:...}`` for PDF templates: the tenant's theme tokens (WeasyPrint reads CSS variables)."""
    from django.utils.safestring import mark_safe  # noqa: PLC0415

    from mealtally.web import themes  # noqa: PLC0415

    return mark_safe(themes.css_vars(themes.theme_for(tenant)))  # noqa: S308 (tokens come from our own themes.css)


@register.simple_tag
def theme_token(name, theme="tally"):
    """One token value of a theme, e.g. ``{% theme_token "primary" "tally" %}`` (Django admin header)."""
    from mealtally.web import themes  # noqa: PLC0415

    return themes.tokens(theme)[name]


@register.filter
def money(minor):
    """Integer minor units -> ``₹1,500.00`` / ``$1,500.00`` in the restaurant's currency. The ONLY way a ``*_minor``
    value may be rendered."""
    return format_money(minor or 0)


@register.filter
def phone_pretty(phone):
    """``+919000010001`` -> ``+91 90000 10001`` (other numbers are returned unchanged)."""
    p = str(phone or "")
    return f"+91 {p[3:8]} {p[8:]}" if p.startswith("+91") and len(p) == 13 else p  # noqa: PLR2004


@register.filter
def money_consumer(minor):
    """Customer screens: ``₹170`` for whole amounts, else ``₹170.50``. Receipts and ledgers keep ``|money``."""
    from mealtally.common.money import format_money_consumer  # noqa: PLC0415

    return format_money_consumer(minor or 0)


ROLE_LABELS = {
    "OWNER": _("Owner"),
    "MANAGER": _("Manager"),
    "STAFF": _("Counter"),
    "CHEF": _("Chef"),
    "DRIVER": _("Driver"),
    "CUSTOMER": _("Customer"),
}


@register.filter
def role_label(role):
    """One set of role names everywhere (the STAFF role is the Counter)."""
    return ROLE_LABELS.get(role, str(role).title())


@register.filter
def source_label(source):
    from mealtally.web.labels import SOURCE_LABELS  # noqa: PLC0415

    return SOURCE_LABELS.get(source, source)


@register.filter
def money_compact(minor):
    """``₹1.24L`` / ``₹82.1K`` / ``₹1.2Cr`` for tiles and axes; always pair it with a ``title`` showing ``|money``."""
    return _money_compact(minor)


@register.filter
def masked(phone):
    return mask_phone(phone or "")


@register.filter
def per_meal(plan):
    return per_meal_price(plan.price_minor, plan.meals_per_cycle)


@register.filter
def phone(value):
    """``+91 90000 30002``. Full numbers only where the screen is allowed to show them."""
    return format_phone(value or "")


@register.filter
def phone_masked(value):
    """The one staff-screen rule: ``••••• 0002``."""
    return mask_phone(value or "")


@register.filter
def pay_method(value):
    from mealtally.billing.receipts import method_label  # noqa: PLC0415

    return method_label(value or "")
