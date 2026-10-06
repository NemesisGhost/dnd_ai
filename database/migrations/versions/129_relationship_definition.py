"""Add versioning and lifecycle to world.relationships

Revision ID: 129_relationship_definition
Revises: 128_dungeon_state_event
Create Date: 2026-10-06 18:00:00.000000

Purpose:
    Phase 15 checkpoint 15.3A-2a (decision D-18, ADR 0017). A world relationship is authored
    through commands, so it needs what every authored aggregate has: an optimistic-concurrency
    token, an operational lifecycle (active or archived, never physically deleted once
    referenced), and the author. This resolves ADR 0015 decision 8 with option (a): add
    `row_version` and an archive lifecycle to the relationship, and project it to readers only
    when they can see every participant and its subtype allows (`is_public`); full canon status
    for edges is not adopted.

Forward migration:
    - `world.relationships.row_version` (BIGINT, default 1, positive check, bumped by
      `core.bump_row_version()` on every UPDATE).
    - `world.relationships.lifecycle_status_id` (NOT NULL, `core.lifecycle_statuses`, existing
      rows set to `active`, defaulted to `active` on insert), `archived_at`,
      `created_by_user_id` (nullable, `ON DELETE SET NULL`), with indexes.

Rollback:
    Supported: drops the triggers, function, indexes, constraint and columns.

Data implications:
    Existing relationships become `active` at version 1 with no recorded author.

Locking considerations:
    ADD COLUMN with a constant default is metadata-only; the `lifecycle_status_id` backfill is
    one UPDATE of `world.relationships`, which is small.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "129_relationship_definition"
down_revision = "128_dungeon_state_event"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE world.relationships
        ADD COLUMN row_version BIGINT NOT NULL DEFAULT 1,
        ADD CONSTRAINT ck_relationships_row_version_positive CHECK (row_version >= 1),
        ADD COLUMN lifecycle_status_id UUID
            REFERENCES core.lifecycle_statuses(lifecycle_status_id) ON DELETE RESTRICT,
        ADD COLUMN archived_at TIMESTAMPTZ,
        ADD COLUMN created_by_user_id UUID
            REFERENCES security.users(user_id) ON DELETE SET NULL;
    """)
    op.execute("""
        UPDATE world.relationships
        SET lifecycle_status_id = (
            SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'
        );
    """)
    op.execute("ALTER TABLE world.relationships ALTER COLUMN lifecycle_status_id SET NOT NULL;")
    op.execute("""
        COMMENT ON COLUMN world.relationships.row_version IS
        'Optimistic-concurrency token, incremented by every UPDATE '
        '(core.bump_row_version()). Authoring commands require the caller''s '
        'expected_row_version to equal it under a row lock and reject a stale write.';
    """)
    op.execute("""
        COMMENT ON COLUMN world.relationships.lifecycle_status_id IS
        'Operational lifecycle (active or archived). An archived relationship stays in history, '
        'is hidden from readers who cannot edit canon, and takes no authoring or state writes '
        'until restored.';
    """)
    op.execute("""
        COMMENT ON COLUMN world.relationships.archived_at IS
        'When the relationship was archived; NULL while active.';
    """)
    op.execute("""
        COMMENT ON COLUMN world.relationships.created_by_user_id IS
        'The authenticated human who created the relationship through the authoring command; '
        'NULL for relationships created before revision 129 or by operator tooling.';
    """)
    op.execute(
        "CREATE INDEX ix_relationships_lifecycle_status_id "
        "ON world.relationships (lifecycle_status_id);"
    )
    op.execute(
        "CREATE INDEX ix_relationships_created_by_user_id ON world.relationships "
        "(created_by_user_id) WHERE created_by_user_id IS NOT NULL;"
    )
    op.execute("""
        CREATE TRIGGER tr_relationships_bump_row_version
        BEFORE UPDATE ON world.relationships
        FOR EACH ROW EXECUTE FUNCTION core.bump_row_version();
    """)
    op.execute("""
        CREATE FUNCTION world.default_relationship_lifecycle()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF NEW.lifecycle_status_id IS NULL THEN
                SELECT lifecycle_status_id INTO NEW.lifecycle_status_id
                FROM core.lifecycle_statuses WHERE code = 'active';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.default_relationship_lifecycle() IS
        'A relationship inserted without a lifecycle status starts active.';
    """)
    op.execute("""
        CREATE TRIGGER tr_relationships_default_lifecycle
        BEFORE INSERT ON world.relationships
        FOR EACH ROW EXECUTE FUNCTION world.default_relationship_lifecycle();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tr_relationships_default_lifecycle ON world.relationships;")
    op.execute("DROP FUNCTION IF EXISTS world.default_relationship_lifecycle();")
    op.execute("DROP TRIGGER IF EXISTS tr_relationships_bump_row_version ON world.relationships;")
    op.execute("DROP INDEX IF EXISTS world.ix_relationships_created_by_user_id;")
    op.execute("DROP INDEX IF EXISTS world.ix_relationships_lifecycle_status_id;")
    op.execute("""
        ALTER TABLE world.relationships
        DROP COLUMN IF EXISTS created_by_user_id,
        DROP COLUMN IF EXISTS archived_at,
        DROP COLUMN IF EXISTS lifecycle_status_id,
        DROP CONSTRAINT IF EXISTS ck_relationships_row_version_positive,
        DROP COLUMN IF EXISTS row_version;
    """)
