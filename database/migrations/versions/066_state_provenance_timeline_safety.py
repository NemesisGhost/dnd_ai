"""Timeline-safe state provenance, and character-state event provenance

Revision ID: 066_state_event_timeline_safe
Revises: 065_recorded_event_immutable
Create Date: 2026-08-05 18:30:00.000000

Purpose:
    Corrective revision (Phase 6 exit-review correction pass), two related
    gaps in the same column:

    1. The five Phase-5 dungeon-domain campaign.*_state tables' last_event_id
       (revision 060) accepted any narrative.events row at all — nothing
       checked that the referenced event actually belongs to the same
       timeline as the state row it is cited as provenance for. A state row
       on timeline A could cite an event that happened on timeline B,
       silently breaking the "current state and event history remain
       consistent" exit criterion revision 060 was supposed to help satisfy.

    2. docs/architecture/DATABASE_MODEL.md §17 already called out
       campaign.character_state/.character_conditions/.character_resources
       as needing the same last_event_id column "here" (i.e. once
       narrative.events exists) — Phase 6 delivered narrative.events and
       gave five dungeon-state tables their column (revision 060) but never
       circled back to the three character-state tables the same note
       named, even while Phase 6 was being marked complete. This revision
       closes that specific deferral.

    One shared trigger function handles both the five existing tables and
    the three newly-added ones: they all share the same (timeline_id,
    last_event_id) column shape, so a single BEFORE INSERT OR UPDATE
    function checking "when last_event_id is set, its event's timeline_id
    must equal this row's own timeline_id" is correct for all eight without
    five (or eight) near-duplicate trigger bodies.

Forward migration:
    - campaign.enforce_state_event_timeline(): BEFORE INSERT OR UPDATE
      trigger function. No-op when NEW.last_event_id IS NULL. Otherwise
      looks up narrative.events.timeline_id for that event and rejects the
      write if it disagrees with NEW.timeline_id.
    - Attached to the five existing tables: campaign.location_state,
      .area_connection_state, .area_feature_state, .hazard_state,
      .interactable_state.
    - campaign.character_state.last_event_id, .character_conditions.
      last_event_id, .character_resources.last_event_id — same shape as
      revision 060's five columns (UUID REFERENCES narrative.events
      ON DELETE SET NULL, partial index, matching COMMENT), then the same
      trigger attached to all three.

Rollback:
    Supported. Drops all eight triggers and the shared function, then the
    three new columns (and their indexes, dropped implicitly with them).

Data implications:
    No existing campaign.*_state row anywhere has a non-NULL last_event_id
    yet (revision 060 added the column but nothing has ever written to it —
    src/dnd_ai/commands has no character-state-mutating command, and the one
    command that does write it, resolve_check(), was only added in Phase 6
    increment 5 and only ever cites an event on the same timeline it just
    created that event on). The new trigger has nothing to reject on
    upgrade. The three new character-state columns default to NULL for
    every existing row, exactly like revision 060's five.

Locking considerations:
    Eleven CREATE TRIGGER/ALTER TABLE statements. No table this touches is
    large; ADD COLUMN with no default is metadata-only.

See: docs/architecture/DATABASE_MODEL.md §17 (typed timeline state)
     docs/DATABASE_CONVENTIONS.md §13.4 (causality)
     database/migrations/versions/060_state_event_provenance.py (the
     original last_event_id columns this revision both hardens and extends)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "066_state_event_timeline_safe"
down_revision = "065_recorded_event_immutable"
branch_labels = None
depends_on = None

EXISTING_STATE_TABLES = [
    "location_state",
    "area_connection_state",
    "area_feature_state",
    "hazard_state",
    "interactable_state",
]

NEW_PROVENANCE_TABLES = [
    "character_state",
    "character_conditions",
    "character_resources",
]


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. Shared timeline-agreement guard
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_state_event_timeline()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_event_timeline  UUID;
        BEGIN
            IF NEW.last_event_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT timeline_id INTO v_event_timeline
            FROM narrative.events WHERE event_id = NEW.last_event_id;

            IF v_event_timeline IS DISTINCT FROM NEW.timeline_id THEN
                RAISE EXCEPTION
                    '%.% last_event_id % belongs to timeline %, but this row belongs to '
                    'timeline % — state provenance must cite an event on the same timeline',
                    TG_TABLE_SCHEMA, TG_TABLE_NAME, NEW.last_event_id, v_event_timeline,
                    NEW.timeline_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_state_event_timeline() IS
        'Shared guard for every campaign.*_state/*_conditions/*_resources table '
        'carrying a last_event_id: when set, the cited event must belong to the same '
        'timeline as this row (conventions §13.4). No-op when last_event_id is NULL.';
    """)

    for table in EXISTING_STATE_TABLES:
        op.execute(f"""
            CREATE TRIGGER tr_{table}_enforce_event_timeline
            BEFORE INSERT OR UPDATE ON campaign.{table}
            FOR EACH ROW EXECUTE FUNCTION campaign.enforce_state_event_timeline();
        """)

    # ==========================================================================
    # 2. last_event_id on the three character-state tables
    # ==========================================================================
    for table in NEW_PROVENANCE_TABLES:
        op.execute(f"""
            ALTER TABLE campaign.{table}
            ADD COLUMN last_event_id UUID
                REFERENCES narrative.events(event_id) ON DELETE SET NULL;
        """)
        op.execute(f"""
            COMMENT ON COLUMN campaign.{table}.last_event_id IS
            'The event that produced this row''s current values, when there was '
            'one (conventions §13.4). NULL for rows predating this column and for '
            'administrative/import-driven changes with no causing event.';
        """)
        op.execute(
            f"CREATE INDEX ix_{table}_last_event_id ON campaign.{table} (last_event_id) "
            "WHERE last_event_id IS NOT NULL;"
        )
        op.execute(f"""
            CREATE TRIGGER tr_{table}_enforce_event_timeline
            BEFORE INSERT OR UPDATE ON campaign.{table}
            FOR EACH ROW EXECUTE FUNCTION campaign.enforce_state_event_timeline();
        """)


def downgrade() -> None:
    """Revert the migration."""

    for table in reversed(NEW_PROVENANCE_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS tr_{table}_enforce_event_timeline ON campaign.{table};")
        op.execute(f"ALTER TABLE campaign.{table} DROP COLUMN IF EXISTS last_event_id;")

    for table in reversed(EXISTING_STATE_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS tr_{table}_enforce_event_timeline ON campaign.{table};")

    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_state_event_timeline();")
