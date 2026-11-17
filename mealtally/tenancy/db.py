"""Provisioning of database roles / privileges (idempotent). See ADR 0002."""

from __future__ import annotations

from django.db import connection
from psycopg import sql

from .rls import APPEND_ONLY_TABLES


def ensure_login_role(name: str, password: str) -> None:
    """Create (or re-password) a plain LOGIN role: no superuser, no BYPASSRLS."""
    with connection.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [name])
        verb = "ALTER" if cur.fetchone() else "CREATE"
        stmt = sql.SQL("{} ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE").format(
            sql.SQL(verb), sql.Identifier(name), sql.Literal(password)
        )
        cur.execute(stmt.as_string(connection.connection))


def grant_app_privileges(app_role: str, *, harden_append_only: bool = True, allow_truncate: bool = False) -> None:
    """Give the (non-owner) app role DML rights; append-only tables get INSERT/SELECT only."""
    role = sql.Identifier(app_role).as_string(connection.connection)
    privileges = "SELECT, INSERT, UPDATE, DELETE" + (", TRUNCATE" if allow_truncate else "")
    with connection.cursor() as cur:
        cur.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        cur.execute(f"GRANT {privileges} ON ALL TABLES IN SCHEMA public TO {role}")
        cur.execute(f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {role}")
        if harden_append_only:
            for table in APPEND_ONLY_TABLES:
                cur.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON "{table}" FROM {role}')
