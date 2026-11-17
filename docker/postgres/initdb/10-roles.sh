#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# Runs once, on first initialisation of the data directory.
#   POSTGRES_USER  : bootstrap superuser. Used ONLY for provisioning, backups and tests -- never by the app.
#   mealtally_owner     : non-superuser; owns the database & tables; runs migrations (FORCE RLS applies to it).
#   mealtally_app       : non-superuser, does NOT own tables; the role the running application uses (RLS enforced).
set -o errexit -o nounset -o pipefail

: "${MEALTALLY_DB_OWNER_PASSWORD:?MEALTALLY_DB_OWNER_PASSWORD is required}"
: "${MEALTALLY_DB_APP_PASSWORD:?MEALTALLY_DB_APP_PASSWORD is required}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE mealtally_owner LOGIN PASSWORD '${MEALTALLY_DB_OWNER_PASSWORD}' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE mealtally_app   LOGIN PASSWORD '${MEALTALLY_DB_APP_PASSWORD}'   NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
ALTER DATABASE "${POSTGRES_DB}" OWNER TO mealtally_owner;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO mealtally_owner;
GRANT USAGE ON SCHEMA public TO mealtally_app;
SQL
