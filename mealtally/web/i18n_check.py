# SPDX-License-Identifier: AGPL-3.0-only
"""Find template text that people read but that isn't marked for translation (used by a test and by translators).

A template's visible text is what remains after removing Django tags and variables, HTML tags, comments, <script> and
<style> blocks and the {% trans %} / {% blocktrans %} parts. Anything with letters left over is untranslated, unless it
is a brand name, a unit or a code that reads the same in every language (ALLOWED).
"""

from __future__ import annotations

import re
from pathlib import Path

ALLOWED = {
    "Mealtally",
    "UPI",
    "QR",
    "PDF",
    "CSV",
    "OK",
    "UTR",
    "ID",
    "API",
    "PIN",
    "Aa",
    "kg",
    "km",
    # product and protocol names, key caps, Indian identifiers shown only to Indian restaurants
    "WhatsApp",
    "SMS",
    "Razorpay",
    "Cashfree",
    "Django",
    "Enter",
    "Esc",
    "IFSC",
    "FSSAI",
}
_BLOCKTRANS = re.compile(r"{%\s*blocktrans.*?%}.*?{%\s*endblocktrans\s*%}", re.S)
_COMMENT_BLOCK = re.compile(r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}", re.S)
_TAG = re.compile(r"{%.*?%}|{{.*?}}|{#.*?#}", re.S)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_SCRIPT_STYLE = re.compile(r"<(script|style|svg|pre|code)\b.*?</\1>", re.S | re.I)
_HTML_TAG = re.compile(
    r"<(?:[^>\"']|\"[^\"]*\"|'[^']*')*>", re.S
)  # a ">" inside a quoted attribute stays inside the tag
_ATTRS_WITH_TEXT = re.compile(r"\b(?:aria-label|title|placeholder|alt)=\"([^\"{]*[A-Za-z][^\"{]*)\"")
_WORD = re.compile(r"[A-Za-z][A-Za-z'\u2019-]+")


def untranslated(text: str) -> list[str]:
    hits = [
        m.group(1) for m in _ATTRS_WITH_TEXT.finditer(text) if "@" not in m.group(1) and m.group(1) not in ALLOWED
    ]  # example addresses
    body = _COMMENT_BLOCK.sub(" ", text)
    body = _BLOCKTRANS.sub(" ", body)
    body = _SCRIPT_STYLE.sub(" ", body)
    body = _HTML_COMMENT.sub(" ", body)
    body = _TAG.sub(" ", body)
    body = _HTML_TAG.sub(" ", body)
    for chunk in re.split(r"\s{2,}|\n", body):
        words = [w for w in _WORD.findall(chunk) if w not in ALLOWED]
        if words and len("".join(words)) > 1:
            hits.append(chunk.strip())
    return [h for h in hits if h]


def scan(root: Path) -> dict[str, list[str]]:
    out = {}
    for path in sorted(root.rglob("*.html")):
        hits = untranslated(path.read_text(encoding="utf-8"))
        if hits:
            out[str(path.relative_to(root))] = hits
    return out
