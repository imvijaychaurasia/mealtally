#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Restore a dump into the running database. It REPLACES the current data: take a backup first (make backup).
set -euo pipefail
cd "$(dirname "$0")/.."
file=${1:-}
[ -n "${file}" ] && [ -f "${file}" ] || { echo "usage: make restore FILE=backups/mealtally-....dump" >&2; exit 2; }
compose=(docker compose); [ -n "${COMPOSE_FILE:-}" ] && compose+=(-f "${COMPOSE_FILE}")
if [ -t 0 ]; then
  read -rp "This replaces all data in the database with ${file}. Type 'restore' to continue: " ok
  [ "${ok}" = restore ] || { echo "cancelled"; exit 1; }
fi
"${compose[@]}" stop web worker beat
"${compose[@]}" exec -T postgres sh -c 'pg_restore --clean --if-exists --no-owner --role=mealtally_owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "${file}"
"${compose[@]}" start web worker beat
echo "restored ${file}"
