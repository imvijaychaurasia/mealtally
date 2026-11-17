"""SQL for row-level security and append-only enforcement (used by migrations & checks)."""

from __future__ import annotations

from django.db import migrations

POLICY_NAME = "mealtally_tenant_isolation"

# Wrapped in scalar sub-selects so Postgres evaluates them once per statement
# (InitPlan) rather than once per row, keeping tenant indexes usable.
_TENANT = "(SELECT NULLIF(current_setting('app.tenant_id', true), '')::bigint)"
_PLATFORM = "((SELECT current_setting('app.platform', true)) = 'on')"


def rls_condition(column: str = "tenant_id") -> str:
    return f"({column} = {_TENANT} OR {_PLATFORM})"


def enable_rls(table: str, column: str = "tenant_id") -> migrations.RunSQL:
    cond = rls_condition(column)
    return migrations.RunSQL(
        sql=[
            f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY',
            f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY',
            f'CREATE POLICY {POLICY_NAME} ON "{table}" USING {cond} WITH CHECK {cond}',
        ],
        reverse_sql=[
            f'DROP POLICY IF EXISTS {POLICY_NAME} ON "{table}"',
            f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY',
            f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY',
        ],
    )


APPEND_ONLY_FUNCTION = "mealtally_reject_mutation"

CREATE_APPEND_ONLY_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {APPEND_ONLY_FUNCTION}() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'table % is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$
"""


TRUNCATE_FUNCTION = "mealtally_reject_truncate"
CREATE_TRUNCATE_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {TRUNCATE_FUNCTION}() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'table % is append-only: TRUNCATE is not allowed', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$
"""


def no_truncate(table: str) -> migrations.RunSQL:
    trigger = f"{table}_no_truncate"
    return migrations.RunSQL(
        sql=(
            f'CREATE TRIGGER {trigger} BEFORE TRUNCATE ON "{table}" '
            f"FOR EACH STATEMENT EXECUTE FUNCTION {TRUNCATE_FUNCTION}()"
        ),
        reverse_sql=f'DROP TRIGGER IF EXISTS {trigger} ON "{table}"',
    )


def append_only(table: str) -> migrations.RunSQL:
    trigger = f"{table}_append_only"
    return migrations.RunSQL(
        sql=(
            f'CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON "{table}" '
            f"FOR EACH ROW EXECUTE FUNCTION {APPEND_ONLY_FUNCTION}()"
        ),
        reverse_sql=f'DROP TRIGGER IF EXISTS {trigger} ON "{table}"',
    )


# Tables whose UPDATE/DELETE is rejected by trigger (and not even granted to the app role).
APPEND_ONLY_TABLES = (
    "ledger_mealledgerentry",
    "audit_auditevent",
    "billing_platformfeeentry",
)
