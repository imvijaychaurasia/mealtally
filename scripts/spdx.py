#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Every source file starts with an SPDX licence line. `--check` (CI) lists the files without one; no flag adds it.

Covers Python, shell, JavaScript, CSS and YAML files tracked by git. Vendored third-party files keep their own licence
headers and are skipped, as is generated CSS.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TAG = "SPDX-License-Identifier: AGPL-3.0-only"
COMMENT = {".py": "# {}", ".sh": "# {}", ".yml": "# {}", ".yaml": "# {}", ".js": "/* {} */", ".css": "/* {} */"}
SKIP_PARTS = {"vendor"}
SKIP_NAMES = {"app.css"}


def tracked() -> list[Path]:
    out = subprocess.run(  # noqa: S603
        ["git", "ls-files", "-co", "--exclude-standard"],  # noqa: S607  (git from PATH, fixed arguments)
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode == 0:
        return [Path(p) for p in out.stdout.splitlines()]
    ignore = {".git", ".venv", ".ruff_cache", ".pytest_cache", "__pycache__", "staticfiles", "node_modules", "backups"}
    return [p for p in Path().rglob("*") if not ignore.intersection(p.parts)]  # outside a git checkout


def wants_header(path: Path) -> bool:
    return (
        path.suffix in COMMENT
        and path.is_file()
        and not SKIP_PARTS.intersection(path.parts)
        and path.name not in SKIP_NAMES
        and path.stat().st_size > 0
    )


def add(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    line = COMMENT[path.suffix].format(TAG) + "\n"
    if text.startswith("#!"):
        first, _, rest = text.partition("\n")
        path.write_text(first + "\n" + line + rest, encoding="utf-8")
    else:
        path.write_text(line + text, encoding="utf-8")


def main() -> int:
    missing = [p for p in tracked() if wants_header(p) and TAG not in p.read_text(encoding="utf-8")[:500]]
    if "--check" in sys.argv:
        for p in missing:
            print(f"missing SPDX header: {p}")
        return 1 if missing else 0
    for p in missing:
        add(p)
    print(f"added SPDX headers to {len(missing)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
