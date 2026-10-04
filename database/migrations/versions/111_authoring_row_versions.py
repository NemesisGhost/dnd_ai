"""Add row versions, the supersession link, and strict timeline-lineage immutability

Revision ID: 111_authoring_row_versions
Revises: 110_world_authoring_authority
Create Date: 2026-10-03 12:30:00.000000

Purpose:
    Phase 14 authoring kernel (docs/DATABASE_CONVENTIONS.md §26.3). Three
    independent, history-safety changes the authoring commands depend on.

Forward migration:
    1. Optimistic concurrency. `row_version BIGINT NOT NULL DEFAULT 1`
       (`CHECK (row_version >= 1)`) on `core.worlds`, `campaign.timelines`,
       `campaign.campaigns`, and `core.entities`, bumped by one shared
       `BEFORE UPDATE` trigger function, `core.bump_row_version()`. Every
       authoring edit, archive, restore, and lifecycle transition compares an
       `expected_row_version` against it under a row lock. A constant-default
       ADD COLUMN is metadata-only on PostgreSQL 18 (no table rewrite).

    2. The supersession link. `core.entities.superseded_by_entity_id`
       (nullable, self-referencing, ON DELETE RESTRICT) records which entity
       replaced a superseded one (docs/ENTITY_LIFECYCLE.md §16.4). Guards:
       `ck_entities_not_self_superseded`, and `core.enforce_entity_supersession()`
       -- the replacement must share the entity's world and entity type, the
       entity's canon status must be `superseded` whenever the link is set, and
       the link is write-once (NULL -> value only).

    3. Timeline lineage immutability. `campaign.timelines.parent_timeline_id`
       and `branch_world_time_id` were mutable by UPDATE, which would silently
       rewrite what a branch inherits. `campaign.enforce_timeline_lineage_
       immutable()` now rejects any change to either (NULL included), and any
       change to `branch_event_id` once it is non-NULL (NULL -> value stays
       allowed once, per revision 058). The trigger is named so it sorts before
       `tr_timelines_enforce_branch`: with lineage frozen, a reparenting UPDATE
       is reported as an immutability violation rather than reaching the cycle
       walk, and cycles become structurally impossible (an INSERT cannot create
       one and an UPDATE can no longer reparent).

Rollback:
    Supported. Drops the three triggers/functions and the four `row_version`
    columns and the supersession column. Supersession links and row versions
    are lost, which is lossy but not canon-destroying: every superseded
    entity keeps `canon_status = superseded`.

Data implications:
    Existing rows get `row_version = 1`. Existing timelines already satisfy the
    lineage guard (it only constrains future UPDATEs). No entity has a
    supersession link yet.

Locking considerations:
    ADD COLUMN with a constant default takes a brief ACCESS EXCLUSIVE lock on
    each of the four tables and does not rewrite them.

See: docs/DATABASE_CONVENTIONS.md §26.3
     docs/ENTITY_LIFECYCLE.md §16.4 (supersession)
     docs/architecture/DATABASE_MODEL.md §6.1
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "111_authoring_row_versions"
down_revision = "110_world_authoring_authority"
branch_labels = None
depends_on = None

_VERSIONED = (
    ("core", "worlds", "worlds"),
    ("campaign", "timelines", "timelines"),
    ("campaign", "campaigns", "campaigns"),
    ("core", "entities", "entities"),
)


def upgrade() -> None:
    """Apply the migration."""
    op.execute("""
        CREATE OR REPLACE FUNCTION core.bump_row_version()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.row_version := OLD.row_version + 1;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.bump_row_version() IS
        'BEFORE UPDATE trigger function: increments row_version by one on every UPDATE, '
        'overriding any value the statement supplied. Backs the optimistic-concurrency '
        'tokens that authoring commands compare as expected_row_version '
        '(docs/DATABASE_CONVENTIONS.md §26.3).';
    """)
    for schema, table, short in _VERSIONED:
        op.execute(f"""
            ALTER TABLE {schema}.{table}
            ADD COLUMN row_version BIGINT NOT NULL DEFAULT 1,
            ADD CONSTRAINT ck_{short}_row_version_positive CHECK (row_version >= 1);
        """)
        op.execute(f"""
            COMMENT ON COLUMN {schema}.{table}.row_version IS
            'Optimistic-concurrency token, incremented by every UPDATE '
            '(core.bump_row_version()). Authoring commands require the caller''s '
            'expected_row_version to equal it under a row lock and reject a stale write.';
        """)
        op.execute(f"""
            CREATE TRIGGER tr_{short}_bump_row_version
            BEFORE UPDATE ON {schema}.{table}
            FOR EACH ROW EXECUTE FUNCTION core.bump_row_version();
        """)

    op.execute("""
        ALTER TABLE core.entities
        ADD COLUMN superseded_by_entity_id UUID
            REFERENCES core.entities(entity_id) ON DELETE RESTRICT,
        ADD CONSTRAINT ck_entities_not_self_superseded
            CHECK (superseded_by_entity_id IS NULL OR superseded_by_entity_id <> entity_id);
    """)
    op.execute("""
        COMMENT ON COLUMN core.entities.superseded_by_entity_id IS
        'The entity that replaced this one when it was superseded (docs/ENTITY_LIFECYCLE.md '
        '§16.4). Set only together with canon_status = superseded, to an entity of the same '
        'world and entity type, and write-once. NULL for every entity that has not been '
        'superseded through the supersede_entity command.';
    """)
    op.execute(
        "CREATE INDEX ix_entities_superseded_by_entity_id "
        "ON core.entities (superseded_by_entity_id) "
        "WHERE superseded_by_entity_id IS NOT NULL;"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION core.enforce_entity_supersession()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_world        UUID;
            v_type         UUID;
            v_status_code  TEXT;
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.superseded_by_entity_id IS NOT NULL
               AND NEW.superseded_by_entity_id IS DISTINCT FROM OLD.superseded_by_entity_id THEN
                RAISE EXCEPTION
                    'entities.superseded_by_entity_id is write-once and cannot be changed '
                    'or cleared on entity %', OLD.entity_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.superseded_by_entity_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT code INTO v_status_code
            FROM core.canon_statuses WHERE canon_status_id = NEW.canon_status_id;
            IF v_status_code IS DISTINCT FROM 'superseded' THEN
                RAISE EXCEPTION
                    'Entity % has a supersession link but its canon status is %, not superseded',
                    NEW.entity_id, v_status_code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT world_id, entity_type_id INTO v_world, v_type
            FROM core.entities WHERE entity_id = NEW.superseded_by_entity_id;
            IF v_world IS DISTINCT FROM NEW.world_id OR v_type IS DISTINCT FROM NEW.entity_type_id THEN
                RAISE EXCEPTION
                    'Entity % must be superseded by an entity of the same world and entity type',
                    NEW.entity_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.enforce_entity_supersession() IS
        'Guards core.entities.superseded_by_entity_id: write-once, only alongside canon '
        'status superseded, and only to a replacement in the same world with the same '
        'entity type. Cross-row, so not expressible as a CHECK.';
    """)
    op.execute("""
        CREATE TRIGGER tr_entities_enforce_supersession
        BEFORE INSERT OR UPDATE ON core.entities
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_supersession();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_timeline_lineage_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.parent_timeline_id IS DISTINCT FROM OLD.parent_timeline_id THEN
                RAISE EXCEPTION
                    'timelines.parent_timeline_id is immutable on campaign.timelines '
                    'and cannot be changed once set (timeline %)', OLD.timeline_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.branch_world_time_id IS DISTINCT FROM OLD.branch_world_time_id THEN
                RAISE EXCEPTION
                    'timelines.branch_world_time_id is immutable on campaign.timelines '
                    'and cannot be changed once set (timeline %)', OLD.timeline_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.branch_event_id IS NOT NULL
               AND NEW.branch_event_id IS DISTINCT FROM OLD.branch_event_id THEN
                RAISE EXCEPTION
                    'timelines.branch_event_id is immutable on campaign.timelines '
                    'once set (timeline %)', OLD.timeline_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_timeline_lineage_immutable() IS
        'A timeline''s lineage defines which parent history it inherits, so reparenting or '
        're-pointing the branch time would silently rewrite history: parent_timeline_id '
        'and branch_world_time_id never change after insert (NULL included), and '
        'branch_event_id may go NULL -> value once. Also makes parent-chain cycles '
        'structurally impossible.';
    """)
    op.execute("""
        CREATE TRIGGER tr_timelines_check_lineage_immutable
        BEFORE UPDATE ON campaign.timelines
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_timeline_lineage_immutable();
    """)


def downgrade() -> None:
    """Revert the migration."""
    op.execute("DROP TRIGGER IF EXISTS tr_timelines_check_lineage_immutable ON campaign.timelines;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_timeline_lineage_immutable();")

    op.execute("DROP TRIGGER IF EXISTS tr_entities_enforce_supersession ON core.entities;")
    op.execute("DROP FUNCTION IF EXISTS core.enforce_entity_supersession();")
    op.execute("DROP INDEX IF EXISTS core.ix_entities_superseded_by_entity_id;")
    op.execute("""
        ALTER TABLE core.entities
        DROP CONSTRAINT IF EXISTS ck_entities_not_self_superseded,
        DROP COLUMN IF EXISTS superseded_by_entity_id;
    """)

    for schema, table, short in reversed(_VERSIONED):
        op.execute(f"DROP TRIGGER IF EXISTS tr_{short}_bump_row_version ON {schema}.{table};")
        op.execute(f"""
            ALTER TABLE {schema}.{table}
            DROP CONSTRAINT IF EXISTS ck_{short}_row_version_positive,
            DROP COLUMN IF EXISTS row_version;
        """)
    op.execute("DROP FUNCTION IF EXISTS core.bump_row_version();")
