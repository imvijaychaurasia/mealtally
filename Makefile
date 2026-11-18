# SPDX-License-Identifier: AGPL-3.0-only
# Everyday commands. `make help` lists them.
SHELL := /bin/bash
COMPOSE ?= docker compose
PROD := $(COMPOSE) -f compose.prod.yml
PLAYWRIGHT_IMAGE ?= mcr.microsoft.com/playwright/python:v1.55.0-noble

.PHONY: help init up down logs demo smoke test lint migrate backup restore upgrade screenshots shell messages

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-12s %s\n", $$1, $$2}'

init: ## First run: write missing secrets to .env, start the stack, create the admin (and the restaurant in single mode)
	@scripts/init.sh

up: ## Build and start the stack (http://localhost:8000 by default)
	$(COMPOSE) up -d --build --wait

down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down

logs: ## Follow the logs of every service
	$(COMPOSE) logs -f --tail=100

demo: ## Development only: seed two demo restaurants and write their logins to ./.demo-credentials
	@umask 077; $(COMPOSE) exec -T web python manage.py mealtally_demo > .demo-credentials.tmp \
	  && mv .demo-credentials.tmp .demo-credentials && chmod 600 .demo-credentials \
	  && cat .demo-credentials || { rm -f .demo-credentials.tmp; exit 1; }

smoke: ## Playwright smoke suite against the running stack (after `make demo`); E2E_BASE_URL overrides the address
	docker run --rm --network host --user "$$(id -u):$$(id -g)" -e HOME=/tmp -v "$(CURDIR):/w:ro" -w /w \
	  -e E2E_BASE_URL="$${E2E_BASE_URL:-http://localhost:$$(grep -E '^MEALTALLY_PORT=' .env | cut -d= -f2 | grep . || echo 8000)}" \
	  -e E2E_ADMIN_LOGIN -e E2E_ADMIN_PASSWORD $(PLAYWRIGHT_IMAGE) \
	  sh -c "pip install -q --user --no-warn-script-location pytest==8.4.2 playwright==1.55.0 && python -m pytest -c e2e/pytest.ini e2e"

test: ## Run the test suite with coverage (fails under 95%)
	$(COMPOSE) --profile test run --rm --build test pytest --cov=mealtally --cov-report=term-missing:skip-covered --cov-fail-under=95 $(ARGS)

lint: ## ruff check and format check
	$(COMPOSE) --profile test run --rm --no-deps --build --entrypoint "" test sh -c "ruff check . && ruff format --check ."

migrate: ## Apply database migrations (also done on every start)
	$(COMPOSE) exec web sh -c "MEALTALLY_DB_OWNER_MODE=1 python manage.py migrate --noinput && MEALTALLY_DB_OWNER_MODE=1 python manage.py db_setup"

backup: ## Write a database dump to ./backups
	@scripts/backup.sh

restore: ## Restore a dump: make restore FILE=backups/mealtally-YYYYMMDDTHHMMSSZ.dump
	@scripts/restore.sh "$(FILE)"

upgrade: ## Production: pull the images in .env (MEALTALLY_IMAGE, MEALTALLY_POSTGRES_IMAGE), back up, then restart (migrations run on start)
	$(PROD) pull
	@COMPOSE_FILE=compose.prod.yml scripts/backup.sh
	$(PROD) up -d --wait

screenshots: ## Render docs/screenshots from a fresh `make demo` instance (needs Playwright)
	@scripts/screenshots.sh

messages: ## Extract strings into locale/*/django.po and compile the .mo files (commit both)
	$(COMPOSE) --profile test run --rm --no-deps --entrypoint "" --user "$$(id -u):$$(id -g)" -e HOME=/tmp test sh -c "python manage.py makemessages --all --ignore=.venv --no-obsolete && python manage.py compilemessages --use-fuzzy --ignore=.venv"

shell: ## Django shell in the web container
	$(COMPOSE) exec web python manage.py shell
