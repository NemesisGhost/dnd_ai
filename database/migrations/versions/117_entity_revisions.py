"""Add core.entity_revisions (canonical definition revision history)

Revision ID: 117_entity_revisions
Revises: 116_sensitive_read_action
Create Date: 2026-10-05 15:00:00.000000

Purpose:
    Phase 15 checkpoint 15.2R (decision D-24, option a). Audit is an
    accountability record and, since checkpoint 15.2A-3, holds no narrative
    values, so it cannot be the history of what a definition said. This table is
    the canonical, GM-only store of that history: one full snapshot of the
    authored record per real change, written by the same request transaction
    that changed it, built directly from the authored record (never from
    `audit.change_log`). It feeds the prior-version and comparison features of
    checkpoint 15.3C-2; no read path exists yet.

    Edits made before this revision have no snapshot; history begins here.

Forward migration:
    `core.entity_revisions (entity_revision_id, entity_id FK core.entities ON
    DELETE CASCADE, world_id FK core.worlds, row_version, revision_kind,
    snapshot JSONB, created_by_user_id, correlation_id, created_at)` with
    `UNIQUE (entity_id, row_version)`.
    - Append-only: an UPDATE is refused for every role by trigger, and the
      application roles hold no UPDATE or DELETE privilege. A deleted draft
      entity removes its revisions through the foreign key's cascade (which runs
      with owner privileges), the one way a revision disappears.
    - `world_id` must equal the entity's world (trigger).
    - Classified GM-only: not readable by `app_read_only` (the deny-by-default
      reporting role of revision 115 gets no default SELECT on new tables).

Rollback:
    Drops the table and its functions. Revision history captured so far is lost
    (it is rebuildable only going forward); downgrade is intended for development
    databases.

Data implications:
    New empty table.

Locking considerations:
    None on existing tables beyond the foreign-key validation of an empty table.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "117_entity_revisions"
down_revision = "116_sensitive_read_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE core.entity_revisions (
            entity_revision_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_id           UUID NOT NULL
                                REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            world_id            UUID NOT NULL
                                REFERENCES core.worlds(world_id) ON DELETE CASCADE,
            row_version         BIGINT NOT NULL,
            revision_kind       TEXT NOT NULL,
            snapshot            JSONB NOT NULL,
            created_by_user_id  UUID REFERENCES security.users(user_id) ON DELETE SET NULL,
            correlation_id      UUID,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_entity_revisions_entity_version UNIQUE (entity_id, row_version),
            CONSTRAINT ck_entity_revisions_kind
                CHECK (revision_kind IN ('created', 'updated', 'lifecycle')),
            CONSTRAINT ck_entity_revisions_version_positive CHECK (row_version >= 1),
            CONSTRAINT ck_entity_revisions_snapshot_object
                CHECK (jsonb_typeof(snapshot) = 'object')
        );
    """)
    op.execute("""
        COMMENT ON TABLE core.entity_revisions IS
        'Canonical, append-only, GM-only revision history of a definition: one full '
        'snapshot of the authored record per real change (Phase 15, ADR 0016). Built from '
        'the authored record, never from audit.change_log. Never player-visible and never '
        'readable by the reporting role.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.entity_revisions.row_version IS
        'The core.entities.row_version the entity had after this change; unique per entity.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.entity_revisions.revision_kind IS
        'created (initial snapshot), updated (content edit), or lifecycle (canon/archive '
        'transition; snapshot holds the statuses).';
    """)
    op.execute("""
        COMMENT ON COLUMN core.entity_revisions.snapshot IS
        'The authored fields (GM-only data included) as of this version.';
    """)
    op.execute(
        "CREATE INDEX ix_entity_revisions_world_id ON core.entity_revisions (world_id);"
    )
    op.execute(
        "CREATE INDEX ix_entity_revisions_created_by_user_id "
        "ON core.entity_revisions (created_by_user_id) WHERE created_by_user_id IS NOT NULL;"
    )

    op.execute("""
        CREATE FUNCTION core.enforce_entity_revision_append_only()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            RAISE EXCEPTION 'core.entity_revisions is append-only: a revision cannot be updated'
                USING ERRCODE = 'integrity_constraint_violation';
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.enforce_entity_revision_append_only() IS
        'Refuses every UPDATE of core.entity_revisions (revisions are immutable history).';
    """)
    op.execute("""
        CREATE TRIGGER tr_entity_revisions_append_only
        BEFORE UPDATE ON core.entity_revisions
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_revision_append_only();
    """)

    op.execute("""
        CREATE FUNCTION core.enforce_entity_revision_world()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_world UUID;
        BEGIN
            SELECT world_id INTO v_world FROM core.entities WHERE entity_id = NEW.entity_id;
            IF v_world IS DISTINCT FROM NEW.world_id THEN
                RAISE EXCEPTION
                    'revision world % does not match entity % world %',
                    NEW.world_id, NEW.entity_id, v_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.enforce_entity_revision_world() IS
        'A revision belongs to the same world as its entity.';
    """)
    op.execute("""
        CREATE TRIGGER tr_entity_revisions_world
        BEFORE INSERT ON core.entity_revisions
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_revision_world();
    """)

    # Append-only to application roles at the grant level. A cascade from a
    # deleted draft entity runs with owner privileges and is unaffected.
    for role in ("app_read_write", "integration_worker"):
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON core.entity_revisions FROM {role};")
    op.execute("REVOKE ALL ON core.entity_revisions FROM app_read_only;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS core.entity_revisions;")
    op.execute("DROP FUNCTION IF EXISTS core.enforce_entity_revision_world();")
    op.execute("DROP FUNCTION IF EXISTS core.enforce_entity_revision_append_only();")
