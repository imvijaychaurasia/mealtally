#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Leak scan: gitleaks + trufflehog + scripts/leak_scan.py over exactly the files git would publish
# (tracked plus new, minus .gitignore), so a local .env or backup never matters. Exit 1 on any finding.
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git ls-files -z --cached --others --exclude-standard | tar --null -T - -cf - | tar -xf - -C "$tmp"

status=0
echo "== gitleaks"
docker run --rm -v "$tmp:/scan:ro" docker.io/zricethezav/gitleaks:v8.28.0 \
  detect --no-git --source /scan --redact --no-banner || status=1
echo "== trufflehog"
docker run --rm -v "$tmp:/scan:ro" docker.io/trufflesecurity/trufflehog:3.90.8 \
  filesystem /scan --fail --no-update --results=verified,unknown || status=1
echo "== denylist"
python3 scripts/leak_scan.py "$tmp" || status=1
[ "$status" = 0 ] && echo "leak scan: clean" || echo "leak scan: FAILED"
exit "$status"
