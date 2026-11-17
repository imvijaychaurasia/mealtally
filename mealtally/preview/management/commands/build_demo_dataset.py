# SPDX-License-Identifier: AGPL-3.0-only
"""Write the deterministic preview dataset (relative to today) as JSON, e.g. for review or fixtures."""

import json
from datetime import date
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from mealtally.preview import data


def _default(o):
    if isinstance(o, datetime | date):
        return o.isoformat()
    return str(o)


class Command(BaseCommand):
    help = "Build the preview dataset for today and write it to mealtally/preview/fixtures/demo_tiffin.json."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="")

    def handle(self, *args, **opts):
        D = data.build(timezone.localdate())
        out = Path(opts["out"] or Path(__file__).resolve().parents[2] / "fixtures" / "demo_tiffin.json")
        slim = {k: v for k, v in D.items() if k not in ("order_by_no", "sub", "wplan", "slot", "invoice")}
        out.write_text(json.dumps(slim, default=_default, indent=1, ensure_ascii=False))
        self.stdout.write(f"Wrote {out} ({len(D['orders'])} orders, {len(D['subscribers'])} subscribers).")
