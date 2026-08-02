"""Timeline scoping for entity names

Revision ID: 012_entity_name_timelines
Revises: 011_sessions
Create Date: 2026-08-02 12:00:00.000000

Purpose:
    Closes the deferral revision 005 recorded when core.entity_names was
    created: a name may only exist after some historical event, which needs
    campaign.timelines to express — and that table did not exist until
    revision 008 (docs/PLAN.md Phase 3 first-time obligations).

    A NULL timeline_id means a global name, valid regardless of which
    timeline is being viewed — the default, and what every existing row
    keeps. A set timeline_id scopes the name to that timeline and (by the
    same reasoning as every other cross-world guard in this project) must
    belong to the same world as the named entity.

Forward migration:
    - core.entity_names.timeline_id, nullable, FK to campaign.timelines
    - core.enforce_entity_name_world(), extended to also check timeline
      world agreement when timeline_id is set

Rollback:
    Supported. Drops the trigger, its function, and the column, leaving the
    table exactly as revision 005 left it.

Data implications:
    Existing rows get timeline_id = NULL, i.e. they remain global names. No
    row is forced into the primary timeline — a blanket backfill would assert
    something no author claimed.

Locking considerations:
    ADD COLUMN ... NULL is metadata-only in PostgreSQL; it does not rewrite
    the table or take a long-lived lock even if core.entity_names is
    populated.

See: docs/PLAN.md Phase 3 first-time obligations, §5.2 (timelines)
     database/migrations/versions/005_names_and_tags.py (the original deferral)
     docs/architecture/DATABASE_MODEL.md §5.4
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "012_entity_name_timelines"
down_revision = "011_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        ALTER TABLE core.entity_names
        ADD COLUMN timeline_id UUID
            REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE;
    """)
    op.execute("""
        COMMENT ON COLUMN core.entity_names.timeline_id IS
        'NULL means the name is global — valid regardless of which timeline is being '
        'viewed, and what every name defaults to. A set value scopes the name to that '
        'timeline, for names that only exist after some historical event; it must '
        'belong to the same world as the named entity.';
    """)
    op.execute(
        "CREATE INDEX ix_entity_names_timeline_id "
        "ON core.entity_names (timeline_id) "
        "WHERE timeline_id IS NOT NULL;"
    )

    # Same class of guard as core.enforce_entity_tag_world: compares across
    # rows and tables, so it cannot be a CHECK. NULL timeline_id short-circuits
    # immediately, same as tags' NULL-world platform case.
    op.execute("""
        CREATE OR REPLACE FUNCTION core.enforce_entity_name_timeline_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world UUID;
            v_entity_world   UUID;
        BEGIN
            IF NEW.timeline_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_entity_world
            FROM core.entities WHERE entity_id = NEW.entity_id;

            IF v_entity_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Timeline % belongs to world %, but entity % belongs to world %',
                    NEW.timeline_id, v_timeline_world, NEW.entity_id, v_entity_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.enforce_entity_name_timeline_world() IS
        'Keeps a timeline-scoped name from referencing a timeline outside the named '
        'entity''s world. A NULL timeline_id (global name) is exempt.';
    """)
    op.execute("""
        CREATE TRIGGER tr_entity_names_enforce_timeline_world
        BEFORE INSERT OR UPDATE ON core.entity_names
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_name_timeline_world();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "DROP TRIGGER IF EXISTS tr_entity_names_enforce_timeline_world ON core.entity_names;"
    )
    op.execute("DROP FUNCTION IF EXISTS core.enforce_entity_name_timeline_world();")
    op.execute("ALTER TABLE core.entity_names DROP COLUMN IF EXISTS timeline_id;")
