# SPDX-License-Identifier: AGPL-3.0-only
"""Fail if the tree contains anything that must never be published (run by scripts/leak-scan.sh and CI).

Checks, case-insensitive:
- denylisted words (internal hosts, people, companies, competitors). They are stored only as SHA-256 prefixes, so the
  list itself discloses nothing; every substring of every word is hashed and compared.
- denylisted network prefixes (also hashed).
- e-mail addresses on a `.example` domain other than the documentation's sample domain `example.com`.
- private filesystem paths (home directories, macOS temp folders).
- phone numbers that don't look synthetic (a human then checks the hits).

Usage: python scripts/leak_scan.py [ROOT]   -> exit 1 and a list of hits when anything is found.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

# sha256(term)[:16] -> term length. To add a term, print its prefix with:
#   python -c "import hashlib;print(hashlib.sha256(b'term').hexdigest()[:16])"
DENY_WORDS = {
    "1d533b46fb7dad80": 6,
    "0246f8cd6cb85fca": 11,
    "0a11acccb5fd1334": 10,
    "e2995431a7dd0ec6": 7,
    "4214b18c4c3912e2": 4,
    "c318c58cc154559c": 9,
    "8903cc49ea29b338": 5,
    "bceac524abed3b7f": 9,
    "4b8c24f1f5d5f6d9": 13,
    "6424a816804794de": 6,
    "678ab690bad55a11": 7,
    "56ac6d03efde0ad2": 7,
    "42de16fcba876506": 16,
}
DENY_NET_PREFIXES = {"dca98ffb6493d6d7", "56829fe73c1204a3"}  # first three octets

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".ruff_cache", ".pytest_cache", "staticfiles", "backups"}
SKIP_FILES = {"uv.lock", "LICENSE"}
BINARY = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".pdf", ".mo", ".zip"}

WORD = re.compile(r"[a-z0-9]+")
IPV4 = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.\d{1,3}\b")
EXAMPLE_EMAIL = re.compile(r"[\w.+-]+@([\w-]+\.)*example\b(?!\.)", re.IGNORECASE)
PRIVATE_PATH = re.compile(r"(/Users/[A-Za-z][\w.-]+/|/home/(?!mealtally\b)[a-z][\w.-]+/|/private/tmp/)")
PHONE = re.compile(r"\+?91[ -]?([6-9]\d{4})[ -]?(\d{5})\b")


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def denied_words(line: str) -> list[str]:
    hits = []
    lengths = set(DENY_WORDS.values())
    for word in WORD.findall(line.lower()):
        for n in lengths:
            for i in range(len(word) - n + 1):
                if DENY_WORDS.get(_h(word[i : i + n])) == n:
                    hits.append(word)
    return hits


def synthetic_phone(a: str, b: str) -> bool:
    digits = a + b
    return bool(
        digits.startswith("9000")  # the demo and test range (+91 9000x xxxxx)
        or re.search(r"(\d)\1{3}", digits)  # 4+ repeated digits: 98777 77777
        or "12345" in digits
        or "98765" in digits
        or "54321" in digits
    )


def scan(root: Path) -> list[str]:
    problems = []
    for path in sorted(root.rglob("*")):
        # the scanner's own patterns would match themselves
        if not path.is_file() or path.relative_to(root).as_posix() == "scripts/leak_scan.py" or path.suffix.lower() in BINARY or path.name in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        rel = path.relative_to(root)
        if any(word in rel.as_posix().lower() for word in denied_words(rel.as_posix())):
            problems.append(f"{rel}: denylisted word in the file name")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for word in denied_words(line):
                problems.append(f"{rel}:{n}: denylisted word ({word})")
            for m in IPV4.finditer(line):
                if _h(".".join(m.groups())) in DENY_NET_PREFIXES:
                    problems.append(f"{rel}:{n}: denylisted network address")
            for m in EXAMPLE_EMAIL.finditer(line):
                problems.append(f"{rel}:{n}: e-mail on a .example domain other than example.com ({m.group(0)})")
            for m in PRIVATE_PATH.finditer(line):
                problems.append(f"{rel}:{n}: private path ({m.group(0)})")
            for m in PHONE.finditer(line):
                if not synthetic_phone(*m.groups()):
                    problems.append(f"{rel}:{n}: phone number that doesn't look synthetic ({m.group(0)})")
    return problems


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    problems = scan(root)
    for p in problems:
        print(p)
    print(f"leak scan: {len(problems)} problem(s) in {root.name}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
