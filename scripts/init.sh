#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# First run: create .env from .env.example, generate every missing secret, start the stack and create the admin.
# Safe to run again: it only fills secrets that are still empty and never overwrites existing values.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { cp .env.example .env; chmod 600 .env; echo "Created .env from .env.example"; }

# a bounded read (no endless pipe, so no SIGPIPE under pipefail): 200 random bytes -> letters and digits
secret() { local s; s=$(head -c 400 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9'); printf '%s' "${s:0:${1:-40}}"; }
fill() {  # fill KEY with a generated value if it is missing or empty
  local key=$1 value
  if grep -qE "^${key}=.+" .env; then return; fi
  value=$(secret "${2:-40}")
  if grep -qE "^${key}=" .env; then
    sed -i.bak "s|^${key}=.*|${key}=${value}|" .env && rm -f .env.bak
  else
    echo "${key}=${value}" >> .env
  fi
  echo "Generated ${key}"
}
fill DJANGO_SECRET_KEY 60
fill POSTGRES_PASSWORD
fill MEALTALLY_DB_OWNER_PASSWORD
fill MEALTALLY_DB_APP_PASSWORD

# the nightly backup container writes ./backups as this user, so the dumps stay readable for `make restore`
for pair in "MEALTALLY_UID=$(id -u)" "MEALTALLY_GID=$(id -g)"; do
  key=${pair%%=*}
  grep -qE "^${key}=.+" .env && continue
  if grep -qE "^${key}=" .env; then sed -i.bak "s|^${key}=.*|${pair}|" .env && rm -f .env.bak; else echo "${pair}" >> .env; fi
done
mkdir -p backups && chmod 700 backups

set_env() {  # set KEY=value in .env, replacing an empty or missing line
  if grep -qE "^$1=" .env; then sed -i.bak "s|^$1=.*|$1=$2|" .env && rm -f .env.bak; else echo "$1=$2" >> .env; fi
}
# country, currency and time zone of new restaurants: no built-in default, so ask (or stop with a clear message)
missing=()
interactive=0; [ -t 0 ] && interactive=1
while IFS="|" read -r key question example pattern; do
  grep -qE "^${key}=.+" .env && continue
  if [ "${interactive}" = 1 ]; then
    while true; do
      read -rp "${question} (for example ${example}): " value </dev/tty
      [ "${key}" = MEALTALLY_DEFAULT_TIMEZONE ] || value=$(printf "%s" "${value}" | tr "[:lower:]" "[:upper:]")
      if [[ "${value}" =~ ${pattern} ]]; then set_env "${key}" "${value}"; break; fi
      echo "  That doesn't look right; try again."
    done
  else
    missing+=("${key} (${question}, for example ${example})")
  fi
done <<'ASK'
MEALTALLY_DEFAULT_COUNTRY|Country of your restaurant, as an ISO 3166 code|IN, US, GB, AE|^[A-Z]{2}$
MEALTALLY_DEFAULT_CURRENCY|Currency, as an ISO 4217 code|INR, USD, GBP, AED|^[A-Z]{3}$
MEALTALLY_DEFAULT_TIMEZONE|Time zone|Asia/Kolkata, America/New_York, Europe/London|^[A-Za-z_]+(/[A-Za-z0-9_+-]+)+$|^UTC$
ASK
if [ ${#missing[@]} -gt 0 ]; then
  echo "make init needs these in .env (there is no built-in default):" >&2
  printf "  %s\n" "${missing[@]}" >&2
  echo "Set them, then run make init again." >&2
  exit 1
fi

admin=$(grep -E '^MEALTALLY_ADMIN_EMAIL=' .env | cut -d= -f2- || true)
if [ -z "${admin}" ]; then
  if [ -t 0 ]; then
    read -rp "Admin email (your login): " admin
    sed -i.bak "s|^MEALTALLY_ADMIN_EMAIL=.*|MEALTALLY_ADMIN_EMAIL=${admin}|" .env && rm -f .env.bak
  else
    echo "Set MEALTALLY_ADMIN_EMAIL in .env, then run make init again." >&2; exit 1
  fi
fi

docker compose up -d --build --wait
if [ -t 0 ]; then
  docker compose exec web python manage.py mealtally_init --interactive
else
  docker compose exec -T web python manage.py mealtally_init
fi
