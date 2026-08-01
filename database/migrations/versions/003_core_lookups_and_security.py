"""Core lookups, security foundation, and the shared updated_at trigger

Revision ID: 003_core_lookups_and_security
Revises: 002_shared_domains
Create Date: 2026-08-01 12:00:00.000000

Purpose:
    First slice of Phase 2 (docs/PLAN.md §23). Creates the platform lookup
    tables every later table depends on for provenance and status, the minimal
    security tables needed for `created_by` attribution, and the shared
    updated_at trigger function required by docs/DATABASE_CONVENTIONS.md §10.4.

    Deliberately kept small. This is the first revision in the project to
    create tables at all, which makes it the first real exercise of the
    ownership chain in docs/adr/0009-separate-owning-role-from-login-roles.md
    and the first execution of apply_seed(). Both are called out as Phase 2
    first-time obligations in docs/PLAN.md §23. Proving them over six tables
    is cheaper than discovering they are broken over sixteen.

Forward migration:
    - core.set_updated_at() trigger function (§10.4)
    - Lookup tables (§11): core.canon_statuses, core.lifecycle_statuses,
      core.source_types
    - Security tables (§18 of DATABASE_MODEL.md): security.users,
      security.roles, security.user_roles
    - Seeds the three lookups from database/seeds/ (§4.4, §4.5 of PLAN.md)

Rollback:
    Supported. Drops the tables in FK-dependency order, then the trigger
    function. Seeded rows go with their tables.

Data implications:
    Creates lookup rows only. No existing data to migrate — these are the
    first domain tables in the database.

Locking considerations:
    None. All tables are new and empty; no existing table is altered.

See: docs/PLAN.md §4.3 (foundation tables), §4.4 (canon lifecycle), §4.5 (provenance)
     docs/DATABASE_CONVENTIONS.md §10 (common columns), §11 (lookup tables)
     docs/architecture/DATABASE_MODEL.md §5, §18
"""

from alembic import op

from dnd_ai.persistence.seeds import apply_seed

# revision identifiers, used by Alembic.
revision = "003_core_lookups_and_security"
down_revision = "002_shared_domains"
branch_labels = None
depends_on = None


# Lookup tables all share the shape in DATABASE_CONVENTIONS.md §11:
# <lookup>_id, code, display_name, description, sort_order, is_active.
LOOKUPS = [
    (
        "core",
        "canon_statuses",
        "canon_status_id",
        "How authoritative a definition is. Independent of lifecycle status — "
        "see docs/ENTITY_LIFECYCLE.md §2.",
    ),
    (
        "core",
        "lifecycle_statuses",
        "lifecycle_status_id",
        "Whether an entity is currently usable by the platform. Independent of "
        "canon status — see docs/ENTITY_LIFECYCLE.md §2.",
    ),
    (
        "core",
        "source_types",
        "source_type_id",
        "Where an authored or imported fact came from — see docs/PLAN.md §4.5.",
    ),
]


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. Shared updated_at trigger
    # ==========================================================================
    # DATABASE_CONVENTIONS.md §10.4 requires ONE shared trigger function rather
    # than near-identical copies per domain. Defined inline rather than read
    # from database/functions/ because a revision must reproduce the same
    # result on every replay — reading an external file that can change later
    # would break that.
    #
    # now() is deliberate, not an oversight: it returns transaction start time,
    # so every row touched by one command shares an updated_at, which is what
    # makes "changed by this command" a coherent query. clock_timestamp() would
    # give each statement a different value. The consequence is that updated_at
    # does NOT advance between two updates in the same transaction — see the
    # trigger test, which asserts the override rather than a moving clock.
    op.execute("""
        CREATE OR REPLACE FUNCTION core.set_updated_at()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.set_updated_at() IS
        'Shared BEFORE UPDATE trigger function maintaining updated_at. '
        'Use this rather than adding a per-domain copy (conventions §10.4).';
    """)

    # ==========================================================================
    # 2. Lookup tables
    # ==========================================================================
    for schema, table, pk, comment in LOOKUPS:
        op.execute(f"""
            CREATE TABLE {schema}.{table} (
                {pk}          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                code          TEXT NOT NULL,
                display_name  TEXT NOT NULL,
                description   TEXT,
                sort_order    core.nonnegative_integer NOT NULL DEFAULT 0,
                is_active     BOOLEAN NOT NULL DEFAULT true,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ux_{table}_code UNIQUE (code),
                CONSTRAINT ck_{table}_code_length CHECK (char_length(code) <= 100),
                CONSTRAINT ck_{table}_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
            );
        """)
        op.execute(f"COMMENT ON TABLE {schema}.{table} IS '{comment}';")
        op.execute(f"""
            COMMENT ON COLUMN {schema}.{table}.code IS
            'Stable machine-readable identifier. Application logic may reference '
            'codes, but foreign keys use IDs (conventions §11.1).';
        """)
        op.execute(f"""
            CREATE TRIGGER tr_{table}_set_updated_at
            BEFORE UPDATE ON {schema}.{table}
            FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
        """)

    # ==========================================================================
    # 3. Security tables
    # ==========================================================================
    # Minimal for now: enough to attribute created_by/updated_by on the domain
    # tables that follow. Permissions, campaign membership, and service accounts
    # (DATABASE_MODEL.md §18) are deliberately not here — they arrive with the
    # features that need them rather than as speculative scaffolding.
    op.execute("""
        CREATE TABLE security.users (
            user_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username      TEXT NOT NULL,
            email         TEXT,
            display_name  TEXT NOT NULL,
            is_active     BOOLEAN NOT NULL DEFAULT true,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_users_username UNIQUE (username),
            CONSTRAINT ck_users_username_length CHECK (char_length(username) BETWEEN 1 AND 100)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.users IS
        'A person who can author or approve world content. Authentication itself '
        'is handled outside the database; this is identity for attribution and '
        'authorization.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.users.email IS
        'Nullable: service-linked or imported accounts may have no address.';
    """)
    op.execute("""
        CREATE TRIGGER tr_users_set_updated_at
        BEFORE UPDATE ON security.users
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    op.execute("""
        CREATE TABLE security.roles (
            role_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code          TEXT NOT NULL,
            display_name  TEXT NOT NULL,
            description   TEXT,
            sort_order    core.nonnegative_integer NOT NULL DEFAULT 0,
            is_active     BOOLEAN NOT NULL DEFAULT true,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_roles_code UNIQUE (code),
            CONSTRAINT ck_roles_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.roles IS
        'Platform-level role a user can hold. Intentionally unseeded: the role '
        'vocabulary is not yet specified in the domain docs, and inventing it '
        'here would preempt that decision.';
    """)
    op.execute("""
        CREATE TRIGGER tr_roles_set_updated_at
        BEFORE UPDATE ON security.roles
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    op.execute("""
        CREATE TABLE security.user_roles (
            user_id             UUID NOT NULL
                                REFERENCES security.users(user_id) ON DELETE CASCADE,
            role_id             UUID NOT NULL
                                REFERENCES security.roles(role_id) ON DELETE RESTRICT,
            granted_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            granted_by_user_id  UUID REFERENCES security.users(user_id) ON DELETE SET NULL,
            PRIMARY KEY (user_id, role_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.user_roles IS
        'Role assignment. ON DELETE RESTRICT against roles so a role in use '
        'cannot be removed out from under its holders.';
    """)

    # Index every foreign key (conventions §19.1), naming per §19.2. The
    # (user_id, role_id) primary key already covers user_id as a leading
    # column, so only the other two FKs need their own index.
    op.execute("CREATE INDEX ix_user_roles_role_id ON security.user_roles (role_id);")
    op.execute(
        "CREATE INDEX ix_user_roles_granted_by_user_id ON security.user_roles (granted_by_user_id);"
    )

    # ==========================================================================
    # 4. Seed the lookups
    # ==========================================================================
    # First execution of apply_seed() in the project's history. Idempotent by
    # ON CONFLICT (code) DO NOTHING — re-running this revision, or running the
    # seeds again later, must be a no-op.
    apply_seed(op, "core", "canon_statuses")
    apply_seed(op, "core", "lifecycle_statuses")
    apply_seed(op, "core", "source_types")


def downgrade() -> None:
    """Revert the migration."""

    # FK dependency order: user_roles references both users and roles.
    op.execute("DROP TABLE IF EXISTS security.user_roles;")
    op.execute("DROP TABLE IF EXISTS security.roles;")
    op.execute("DROP TABLE IF EXISTS security.users;")

    for schema, table, _pk, _comment in reversed(LOOKUPS):
        op.execute(f"DROP TABLE IF EXISTS {schema}.{table};")

    # Dropped last: the lookup and security tables' triggers depend on it.
    op.execute("DROP FUNCTION IF EXISTS core.set_updated_at();")
