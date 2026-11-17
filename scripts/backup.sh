#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Write a custom-format dump of the database to ./backups (mode 600).
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose); [ -n "${COMPOSE_FILE:-}" ] && compose+=(-f "${COMPOSE_FILE}")
mkdir -p backups
[ -w backups ] || { echo "backups/ is not writable by $(id -un). Fix: sudo chown -R $(id -u):$(id -g) backups" >&2; exit 1; }
file="mealtally-$(date -u +%Y%m%dT%H%M%SZ).dump"
"${compose[@]}" exec -T postgres sh -c 'pg_dump -Fc --no-owner -U "$POSTGRES_USER" "$POSTGRES_DB"' > "backups/${file}.partial"
mv "backups/${file}.partial" "backups/${file}"
chmod 600 "backups/${file}"
echo "backup written: backups/${file} ($(du -h "backups/${file}" | cut -f1))"
