# SPDX-License-Identifier: AGPL-3.0-only
# PostgreSQL with the role setup Mealtally needs (see docker/postgres/initdb/10-roles.sh).
FROM docker.io/postgres:18
COPY docker/postgres/initdb/ /docker-entrypoint-initdb.d/
RUN chmod +x /docker-entrypoint-initdb.d/*.sh
