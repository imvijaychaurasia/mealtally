#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# make screenshots: refresh the demo restaurants (new logins, development only) and render every role's screens into
# docs/screenshots/ with Playwright. Needs the stack running with MEALTALLY_ENV=development.
# For the platform admin's tenant list, run in multi mode and pass E2E_ADMIN_LOGIN / E2E_ADMIN_PASSWORD.
set -euo pipefail
cd "$(dirname "$0")/.."
image=${PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright/python:v1.55.0-noble}
port=$(grep -E '^MEALTALLY_PORT=' .env | cut -d= -f2 || true)
base=${E2E_BASE_URL:-http://localhost:${port:-8000}}

make demo > /dev/null
rm -rf docs/screenshots && mkdir -p docs/screenshots
docker run --rm --network host --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/w" -w /w \
  -e E2E_BASE_URL="$base" -e E2E_ADMIN_LOGIN -e E2E_ADMIN_PASSWORD "$image" \
  sh -c "pip install -q --user --no-warn-script-location playwright==1.55.0 pillow==11.3.0 pytest==8.4.2 \
         && python -m e2e.screenshots"
