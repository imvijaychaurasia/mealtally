# SPDX-License-Identifier: AGPL-3.0-only
"""Theme tokens (D03.5). The single source of truth is ``static/css/themes.css``.

This module parses it so that Python surfaces (PDFs, the PWA manifest, the Django admin header, the contrast test)
read the same values and never hard-code colours.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from django.utils.translation import gettext_lazy as _

CSS_PATH = Path(__file__).resolve().parents[1] / "static" / "css" / "themes.css"
DEFAULT = "masala"
PLATFORM = "tally"

# name -> (label, one-line description) shown in Business profile and the platform admin
THEMES = {
    "masala": (_("Masala kitchen"), _("Warm cream, curry-leaf green and saffron: a classic Indian kitchen.")),
    "fresh": (_("Fresh market"), _("Cool whites, herb teal and tomato red: clean and modern.")),
    "tally": (_("Mealtally"), _("The Mealtally platform look: calm blue on white.")),
}
CHOICES = [(k, v[0]) for k, v in THEMES.items()]

_BLOCK = re.compile(r"(?P<sel>[^{}]+)\{(?P<body>[^{}]*)\}")
_VAR = re.compile(r"--(?P<k>[\w-]+)\s*:\s*(?P<v>[^;]+);")


@lru_cache(maxsize=1)
def _parsed() -> dict[str, dict[str, str]]:
    css = re.sub(r"/\*.*?\*/", "", CSS_PATH.read_text(), flags=re.S)
    css = re.sub(r"@font-face\s*\{[^}]*\}", "", css)
    shared: dict[str, str] = {}
    themes: dict[str, dict[str, str]] = {}
    for m in _BLOCK.finditer(css):
        sel = m["sel"].strip()
        variables = {v["k"]: v["v"].strip() for v in _VAR.finditer(m["body"])}
        if sel == ":root":
            shared.update(variables)
            continue
        for name in re.findall(r'\[data-theme="(\w+)"\]', sel):
            themes.setdefault(name, {}).update(variables)
    return {name: {**shared, **vars_} for name, vars_ in themes.items()}


def tokens(name: str) -> dict[str, str]:
    """Resolved tokens for a theme: ``var(--x)`` references are followed; ``color-mix`` values are left as written."""
    raw = _parsed().get(name) or _parsed()[PLATFORM]
    out = {}
    for key, first in raw.items():
        value, seen = first, 0
        while (m := re.fullmatch(r"var\(--([\w-]+)\)", value)) and seen < 5:
            value = raw.get(m.group(1), value)
            seen += 1
        out[key] = value
    return out


def theme_for(tenant) -> str:
    name = getattr(tenant, "theme", "") or DEFAULT
    return name if name in THEMES else DEFAULT


def css_vars(name: str) -> str:
    """``:root{--primary:#...;...}`` for the PDF templates (WeasyPrint understands CSS variables)."""
    body = "".join(f"--{k}:{v};" for k, v in tokens(name).items() if not v.startswith("color-mix"))
    return f":root{{{body}}}"
