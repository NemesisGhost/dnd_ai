"""Grant schema USAGE to the login roles that need it

Revision ID: 083_schema_usage_grants
Revises: 082_item_command_idempotency
Create Date: 2026-08-16 00:00:00.000000

Purpose:
    Critical correction: `001_bootstrap` grants `app_read_write`,
    `app_read_only`, and `integration_worker` table/sequence-level DML via
    `ALTER DEFAULT PRIVILEGES`, but never grants any of them `USAGE` on the
    schemas those tables live in. PostgreSQL requires `USAGE` on a schema
    before a role can reference *any* object inside it, independent of
    that object's own grants — without it, every table/sequence grant
    001_bootstrap already issued is unreachable. Verified directly against
    a real cluster before writing this migration: a session authenticated
    as `app_read_write` got `permission denied for schema core` on a bare
    `SELECT count(*) FROM core.worlds`, despite `app_read_write` holding
    `SELECT` on that exact table per `information_schema.role_table_grants`.

    This was never caught by any earlier phase's tests because every
    existing test, and the application itself up to this point, always
    connects as the `postgres` superuser or (implicitly, before this
    correction) whatever credential `docker compose`'s `api` service
    happened to use — never as `app_read_write` itself. It surfaced only
    once Phase 10's own containerization work moved to actually
    provisioning and connecting as the constrained role, per ADR 0009 and
    docs/DATABASE_CONVENTIONS.md §27.1 ("Application roles should not own
    schemas or tables" — the *reason* a role-scoped credential exists is
    exactly to be this constrained, not merely to have a different name
    from the migration identity). `admin_maintenance` was never affected
    — 001_bootstrap already grants it `ALL PRIVILEGES ON SCHEMA` directly.

    `app_read_write`/`app_read_only` get `USAGE` on all thirteen bounded
    schemas 001_bootstrap creates — matching the table/sequence scope
    those two roles already hold via `ALTER DEFAULT PRIVILEGES` across
    every one of those same schemas. `integration_worker` gets `USAGE` on
    `integration` only — matching its own existing, narrower table-grant
    scope (001_bootstrap grants it DML on `integration` schema tables
    only); this migration does not expand what any role can *do*, only
    makes the DML grants each role already had actually reachable.

    Function `EXECUTE` privilege needed no equivalent fix: PostgreSQL
    grants `EXECUTE` on a newly created function to `PUBLIC` by default,
    and no migration in this repository has ever revoked that (confirmed:
    no `REVOKE EXECUTE ... FROM PUBLIC` appears anywhere in
    `database/migrations/versions/` or `database/functions/`) — so once
    schema `USAGE` makes a function nameable at all, every login role can
    already call it, e.g. `world.conditional_route_requirement_satisfied()`
    (`src/dnd_ai/commands/interactions.py`).

Forward migration:
    - GRANT USAGE ON SCHEMA <all thirteen> TO app_read_write, app_read_only
    - GRANT USAGE ON SCHEMA integration TO integration_worker

Rollback:
    Supported. Revokes exactly the grants this revision adds.

Data implications:
    None. Privilege-only change; no table, row, or role is created,
    dropped, or altered.

Locking considerations:
    None. `GRANT`/`REVOKE ON SCHEMA` take a lock on the schema's own
    catalog row only, held briefly — no table lock, no effect on
    concurrent readers/writers of any table within these schemas.

See: docs/DATABASE_CONVENTIONS.md §27.1 (Database roles)
     docs/adr/0009-separate-owning-role-from-login-roles.md
     database/migrations/versions/001_bootstrap.py (section 5)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "083_schema_usage_grants"
down_revision = "082_item_command_idempotency"
branch_labels = None
depends_on = None

# The same thirteen bounded schemas 001_bootstrap creates (docs/PLAN.md
# §3) — kept as a literal list here, not re-derived from any catalog
# query, so this migration's own behavior never depends on what schemas
# happen to exist at the moment it runs.
_ALL_SCHEMAS = (
    "core",
    "security",
    "rules",
    "character",
    "world",
    "campaign",
    "narrative",
    "knowledge",
    "interaction",
    "ai",
    "audit",
    "import",
    "integration",
)

_FULL_ACCESS_ROLES = ("app_read_write", "app_read_only")


def upgrade() -> None:
    """Apply the migration."""

    for schema_name in _ALL_SCHEMAS:
        for role_name in _FULL_ACCESS_ROLES:
            op.execute(f"GRANT USAGE ON SCHEMA {schema_name} TO {role_name};")

    op.execute("GRANT USAGE ON SCHEMA integration TO integration_worker;")


def downgrade() -> None:
    """Revert the migration."""

    op.execute("REVOKE USAGE ON SCHEMA integration FROM integration_worker;")

    for schema_name in _ALL_SCHEMAS:
        for role_name in _FULL_ACCESS_ROLES:
            op.execute(f"REVOKE USAGE ON SCHEMA {schema_name} FROM {role_name};")
