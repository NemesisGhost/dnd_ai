"""Audit change log

Revision ID: 007_audit_change_log
Revises: 006_calendars_world_times
Create Date: 2026-08-01 19:00:00.000000

Purpose:
    Completes the Phase 2 table list (docs/PLAN.md §4.3) with audit.change_log,
    the append-only record of who changed what and why.

    Phase 2 only needs creation and lifecycle-transition records. The causal
    event rule — that a state change must reference the event that caused it
    (rule 6 in CLAUDE.md) — is not fully exercised until Phase 6, when
    narrative.events exists. The column is here and nullable so audit rows
    written now can be linked later; a foreign key is added by the revision
    that creates the events table.

Forward migration:
    - audit.change_actions — lookup for what kind of change occurred
    - audit.change_log — the append-only log itself
    - Revokes UPDATE and DELETE from the application roles, so the log is
      append-only to them rather than only by convention (conventions §24.2)

Rollback:
    Supported. Drops both tables.

Data implications:
    Seeds six change actions. No other rows created.

Locking considerations:
    None. Both tables are new and empty.

See: docs/DATABASE_CONVENTIONS.md §24 (audit conventions)
     docs/ENTITY_LIFECYCLE.md §19 (required audit data)
     docs/architecture/DATABASE_MODEL.md §18
"""

from alembic import op

from dnd_ai.persistence.seeds import apply_seed

# revision identifiers, used by Alembic.
revision = "007_audit_change_log"
down_revision = "006_calendars_world_times"
branch_labels = None
depends_on = None

APPLICATION_ROLES = ("app_read_write", "integration_worker")


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. audit.change_actions
    # ==========================================================================
    op.execute("""
        CREATE TABLE audit.change_actions (
            change_action_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code              TEXT NOT NULL,
            display_name      TEXT NOT NULL,
            description       TEXT,
            sort_order        core.nonnegative_integer NOT NULL DEFAULT 0,
            is_active         BOOLEAN NOT NULL DEFAULT true,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_change_actions_code UNIQUE (code),
            CONSTRAINT ck_change_actions_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE audit.change_actions IS
        'What kind of change an audit row records. Covers the operations in '
        'docs/DATABASE_CONVENTIONS.md §24.1.';
    """)
    op.execute("""
        COMMENT ON COLUMN audit.change_actions.code IS
        'Stable machine-readable identifier. Application logic may reference '
        'codes, but foreign keys use IDs (conventions §11.1).';
    """)
    op.execute("""
        CREATE TRIGGER tr_change_actions_set_updated_at
        BEFORE UPDATE ON audit.change_actions
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    # ==========================================================================
    # 2. audit.change_log
    # ==========================================================================
    # Append-only, so it takes recorded_at/recorded_by rather than the
    # created/updated pair mutable records use (conventions §10.3), and gets no
    # updated_at trigger — there is nothing to update.
    #
    # BIGINT identity rather than a UUID primary key: this is a high-volume
    # internal append-only table with no need for globally portable identity,
    # which is exactly the case conventions §5.2 carves out.
    #
    # entity_id carries no foreign key on purpose. Audit records outlive what
    # they describe — that is the point of an audit log — so a reference that
    # cascades or restricts would either destroy history or block legitimate
    # deletion. Same reasoning for actor and correlation columns.
    op.execute("""
        CREATE TABLE audit.change_log (
            change_log_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            change_action_id     UUID NOT NULL
                                 REFERENCES audit.change_actions(change_action_id)
                                 ON DELETE RESTRICT,

            -- What changed. Deliberately unconstrained; see the note above.
            schema_name          TEXT NOT NULL,
            table_name           TEXT NOT NULL,
            record_id            UUID,
            entity_id            UUID,
            world_id             UUID,

            -- Lifecycle transition, when the change was one (ENTITY_LIFECYCLE.md §19).
            previous_status      TEXT,
            new_status           TEXT,

            -- Who, and why.
            actor_user_id        UUID REFERENCES security.users(user_id) ON DELETE SET NULL,
            actor_service        TEXT,
            source_id            UUID REFERENCES core.sources(source_id) ON DELETE SET NULL,
            reason               TEXT,

            -- Tracing (conventions §24.4). No foreign keys: the things these
            -- point at may not exist yet, or ever, in this database.
            correlation_id       UUID,
            causation_id         UUID,
            command_name         TEXT,
            event_id             UUID,
            ai_proposal_id       UUID,

            -- What actually changed, when a field-level diff is worth keeping.
            changed_fields       JSONB,

            recorded_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT ck_change_log_actor_present
                CHECK (actor_user_id IS NOT NULL OR actor_service IS NOT NULL),
            CONSTRAINT ck_change_log_schema_format CHECK (schema_name ~ '^[a-z][a-z0-9_]*$'),
            CONSTRAINT ck_change_log_table_format CHECK (table_name ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE audit.change_log IS
        'Append-only record of who changed what and why. Rows outlive the records they '
        'describe, so the columns identifying those records carry no foreign keys — a '
        'cascade would destroy history and a restrict would block legitimate deletion.';
    """)
    op.execute("""
        COMMENT ON COLUMN audit.change_log.change_log_id IS
        'BIGINT identity rather than UUID: high-volume internal append-only data with no '
        'need for globally portable identity (conventions §5.2).';
    """)
    op.execute("""
        COMMENT ON COLUMN audit.change_log.record_id IS
        'Primary key of the changed row, in whatever table schema_name.table_name names. '
        'Unconstrained by design.';
    """)
    op.execute("""
        COMMENT ON COLUMN audit.change_log.entity_id IS
        'The core.entities row this change concerns, when there is one. Denormalized from '
        'record_id so entity history can be queried without knowing which subtype table '
        'the change landed in.';
    """)
    op.execute("""
        COMMENT ON COLUMN audit.change_log.actor_service IS
        'Set instead of actor_user_id when the actor is a service, integration, or AI agent '
        'rather than a person (conventions §24.3). At least one of the two is required.';
    """)
    op.execute("""
        COMMENT ON COLUMN audit.change_log.event_id IS
        'The narrative event that caused this change, once narrative.events exists in '
        'Phase 6. Unconstrained until then; rule 6 in CLAUDE.md is what makes it matter.';
    """)
    op.execute("""
        COMMENT ON COLUMN audit.change_log.changed_fields IS
        'Field-level diff when one is worth keeping. JSONB here is a deliberate use for '
        'genuinely variable shape, not a substitute for relational modelling (§18).';
    """)

    op.execute(
        "CREATE INDEX ix_change_log_change_action_id ON audit.change_log (change_action_id);"
    )
    op.execute("CREATE INDEX ix_change_log_actor_user_id ON audit.change_log (actor_user_id);")
    op.execute("CREATE INDEX ix_change_log_source_id ON audit.change_log (source_id);")
    # The queries this table exists to answer: what happened to this entity, in
    # this world, or under this correlation id — each most-recent-first.
    op.execute("""
        CREATE INDEX ix_change_log_entity_id_recorded_at
        ON audit.change_log (entity_id, recorded_at DESC);
    """)
    op.execute("""
        CREATE INDEX ix_change_log_world_id_recorded_at
        ON audit.change_log (world_id, recorded_at DESC);
    """)
    op.execute("CREATE INDEX ix_change_log_correlation_id ON audit.change_log (correlation_id);")

    # ==========================================================================
    # 3. Append-only enforcement
    # ==========================================================================
    # Conventions §24.2: audit tables are append-only to normal application
    # roles. Making this a grant rather than a trigger keeps it visible in \dp
    # and means a mistaken UPDATE fails outright rather than being silently
    # swallowed.
    #
    # Both verbs are stated explicitly rather than leaning on 001_bootstrap's
    # default privileges, because those do not produce the right result here:
    # app_read_write picks up the full DML set in every schema, but
    # integration_worker is only granted DML in the `integration` schema and so
    # arrives at this table with no privileges whatsoever. A bare REVOKE would
    # therefore have left it unable to append — while the test asserting
    # append-only passed, because having no privileges trivially satisfies
    # "cannot UPDATE". §24.1 requires integration writes to be audited, so the
    # role that performs them has to be able to record them.
    for role in APPLICATION_ROLES:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{role}') THEN
                    GRANT SELECT, INSERT ON audit.change_log TO {role};
                    REVOKE UPDATE, DELETE, TRUNCATE ON audit.change_log FROM {role};
                END IF;
            END
            $$;
        """)

    # ==========================================================================
    # 4. Seeds
    # ==========================================================================
    apply_seed(op, "audit", "change_actions")


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS audit.change_log;")
    op.execute("DROP TABLE IF EXISTS audit.change_actions;")
