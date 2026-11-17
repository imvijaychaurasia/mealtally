# SPDX-License-Identifier: AGPL-3.0-only
# Everyday commands. `make help` lists them.
SHELL := /bin/bash
COMPOSE ?= docker compose
PROD := $(COMPOSE) -f compose.prod.yml

.PHONY: help init up down logs demo test lint migrate backup restore upgrade screenshots shell

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

upgrade: ## Production: pull the image in MEALTALLY_IMAGE, back up, then restart (migrations run on start)
	$(PROD) pull web worker beat
	@COMPOSE_FILE=compose.prod.yml scripts/backup.sh
	$(PROD) up -d --wait

screenshots: ## Render docs/screenshots from a fresh `make demo` instance (needs Playwright)
	@scripts/screenshots.sh

shell: ## Django shell in the web container
	$(COMPOSE) exec web python manage.py shell
