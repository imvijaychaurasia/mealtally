"""Template filters available everywhere (registered as builtins)."""

from django import template
from django.utils.translation import gettext_lazy as _

from mealtally.common.utils import format_inr
from mealtally.common.utils import format_phone
from mealtally.common.utils import inr_compact as _inr_compact
from mealtally.common.utils import mask_phone
from mealtally.common.utils import per_meal_inr

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
def inr(paise):
    """Integer paise -> ``\u20b91,500.00``. The ONLY way a ``*_paise`` value may be rendered."""
    return format_inr(paise or 0)


@register.filter
def phone_pretty(phone):
    """``+919000010001`` -> ``+91 90000 10001`` (other numbers are returned unchanged)."""
    p = str(phone or "")
    return f"+91 {p[3:8]} {p[8:]}" if p.startswith("+91") and len(p) == 13 else p  # noqa: PLR2004


@register.filter
def inr_consumer(paise):
    """Customer screens: ``₹170`` when paise are zero, else ``₹170.50``. Receipts and ledgers keep ``|inr``."""
    text = format_inr(paise or 0)
    return text[:-3] if text.endswith(".00") else text


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
def inr_compact(paise):
    """``₹1.24L`` / ``₹82.1K`` / ``₹1.2Cr`` for tiles and axes; always pair it with a ``title`` showing ``|inr``."""
    return _inr_compact(paise)


@register.filter
def masked(phone):
    return mask_phone(phone or "")


@register.filter
def per_meal(plan):
    return per_meal_inr(plan.price_paise, plan.meals_per_cycle)


@register.filter
def phone(value):
    """``+91 90000 30002`` (D03.9 P2-8/9). Full numbers only where the screen is allowed to show them."""
    return format_phone(value or "")


@register.filter
def phone_masked(value):
    """The one staff-screen rule (D03.9 P2-9): ``••••• 0002``."""
    return mask_phone(value or "")


@register.filter
def pay_method(value):
    from mealtally.billing.receipts import method_label  # noqa: PLC0415

    return method_label(value or "")
