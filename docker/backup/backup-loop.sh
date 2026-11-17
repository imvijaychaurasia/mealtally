#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# Nightly custom-format dump of the application database; prunes dumps older than N days.
# Run once immediately with:  docker exec mealtally-backup /usr/local/bin/backup-loop.sh --once
#
# D03.9: a night is never silently lost. When the loop starts (container start, host reboot) and the newest dump is
# older than MAX_AGE_HOURS, it takes a catch-up dump at once (15-16 Nov 2026 were missed because the host and then the
# stack were down at 02:00 IST). It logs every dump and the next scheduled time, so `docker logs mealtally-backup` shows it.
set -o errexit -o nounset -o pipefail

export PGHOST="${POSTGRES_HOST:-postgres}" PGPORT="${POSTGRES_PORT:-5432}"
export PGUSER="${POSTGRES_USER}" PGPASSWORD="${POSTGRES_PASSWORD}"
DB="${POSTGRES_DB}"
KEEP="${BACKUP_RETENTION_DAYS:-14}"
AT="${BACKUP_AT_UTC:-20:30}"
MAX_AGE_HOURS="${BACKUP_MAX_AGE_HOURS:-26}"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

dump() {
  local stamp file
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  file="/backups/${DB}-${stamp}.dump"
  pg_dump -Fc --no-owner --file="${file}.partial" "${DB}"
  mv "${file}.partial" "${file}"
  chmod 600 "${file}"
  find /backups -maxdepth 1 -name "${DB}-*.dump" -mtime +"${KEEP}" -print -delete
  log "backup ok: ${file} ($(du -h "${file}" | cut -f1))"
}

if [[ "${1:-}" == "--once" ]]; then dump; exit 0; fi

# catch up a missed night (no dump newer than MAX_AGE_HOURS)
if [[ -z "$(find /backups -maxdepth 1 -name "${DB}-*.dump" -mmin -$(( MAX_AGE_HOURS * 60 )) -print -quit)" ]]; then
  log "no dump in the last ${MAX_AGE_HOURS}h: taking a catch-up backup now"
  dump || log "BACKUP FAILED (catch-up)" >&2
fi

while true; do
  now=$(date -u +%s)
  target=$(date -u -d "today ${AT}" +%s)
  (( target <= now )) && target=$(date -u -d "tomorrow ${AT}" +%s)
  log "next backup at $(date -u -d "@${target}" +%Y-%m-%dT%H:%M:%SZ)"
  sleep $(( target - now ))
  dump || log "BACKUP FAILED" >&2
done
