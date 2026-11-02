"""Add campaign.timeline_clocks (the campaign clock)

Revision ID: 118_campaign_clock
Revises: 117_entity_revisions
Create Date: 2026-10-05 17:00:00.000000

Purpose:
    Phase 15 checkpoint 15.2W-2 (decision D-10, option a). A campaign needs a
    *current world time* a GM can advance and correct. It is typed timeline state
    (DATABASE_MODEL §17), not a campaign column, so it follows the same rules as
    every other state table: one row per timeline, a `last_event_id` provenance
    link, and no change without a causal event. A branch with no row of its own
    inherits its parent's clock bounded by its branch point (resolved on the
    read side, like the active character build); the first write on a branch
    creates its own row.

Forward migration:
    - `campaign.timeline_clocks (timeline_id PK, current_world_time_id,
      last_event_id, row_version, created_at, updated_at)`.
    - Triggers: `core.set_updated_at()`, `core.bump_row_version()` (optimistic
      concurrency, revision 111), the shared `campaign.enforce_state_event_
      timeline()` (revision 066: the cited event belongs to the same timeline),
      and `campaign.enforce_timeline_clock_world()` (the world time belongs to the
      timeline's world).
    - `narrative.event_types`: `time_advanced`, `time_corrected`.

Rollback:
    Drops the table, its function, and the two event types (refused by the
    existing foreign key if events of those types already exist; restore a backup
    instead).

Data implications:
    New empty table and two lookup rows.

Locking considerations:
    None on existing tables beyond foreign-key validation of an empty table.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "118_campaign_clock"
down_revision = "117_entity_revisions"
branch_labels = None
depends_on = None

_EVENT_TYPES: tuple[tuple[str, str, int], ...] = (
    ("time_advanced", "Time Advanced", 130),
    ("time_corrected", "Time Corrected", 131),
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE campaign.timeline_clocks (
            timeline_id           UUID PRIMARY KEY
                                  REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            current_world_time_id UUID NOT NULL
                                  REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT,
            last_event_id         UUID
                                  REFERENCES narrative.events(event_id) ON DELETE SET NULL,
            row_version           BIGINT NOT NULL DEFAULT 1,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_timeline_clocks_row_version_positive CHECK (row_version >= 1)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.timeline_clocks IS
        'The current world time of a timeline (Phase 15). One row per timeline; typed '
        'timeline state changed only through the clock commands, each of which records a '
        'causal event. A branch with no row inherits its parent''s clock bounded by its '
        'branch point (resolved on read).';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.timeline_clocks.current_world_time_id IS
        'The timeline''s current point in fictional time; must belong to the timeline''s world.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.timeline_clocks.last_event_id IS
        'The time_advanced or time_corrected event that set the current value '
        '(same-timeline guard: campaign.enforce_state_event_timeline()).';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.timeline_clocks.row_version IS
        'Optimistic-concurrency token, incremented by every UPDATE (core.bump_row_version()).';
    """)
    op.execute(
        "CREATE INDEX ix_timeline_clocks_current_world_time_id "
        "ON campaign.timeline_clocks (current_world_time_id);"
    )
    op.execute(
        "CREATE INDEX ix_timeline_clocks_last_event_id "
        "ON campaign.timeline_clocks (last_event_id) WHERE last_event_id IS NOT NULL;"
    )
    op.execute("""
        CREATE TRIGGER tr_timeline_clocks_set_updated_at
        BEFORE UPDATE ON campaign.timeline_clocks
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_timeline_clocks_bump_row_version
        BEFORE UPDATE ON campaign.timeline_clocks
        FOR EACH ROW EXECUTE FUNCTION core.bump_row_version();
    """)
    op.execute("""
        CREATE TRIGGER tr_timeline_clocks_enforce_event_timeline
        BEFORE INSERT OR UPDATE ON campaign.timeline_clocks
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_state_event_timeline();
    """)
    op.execute("""
        CREATE FUNCTION campaign.enforce_timeline_clock_world()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_timeline_world UUID;
            v_time_world UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;
            SELECT world_id INTO v_time_world
            FROM core.world_times WHERE world_time_id = NEW.current_world_time_id;
            IF v_timeline_world IS DISTINCT FROM v_time_world THEN
                RAISE EXCEPTION
                    'clock world time % is in world %, but timeline % is in world %',
                    NEW.current_world_time_id, v_time_world, NEW.timeline_id, v_timeline_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_timeline_clock_world() IS
        'A timeline clock''s world time belongs to the timeline''s own world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_timeline_clocks_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.timeline_clocks
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_timeline_clock_world();
    """)
    for code, display_name, sort_order in _EVENT_TYPES:
        op.execute(f"""
            INSERT INTO narrative.event_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS campaign.timeline_clocks;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_timeline_clock_world();")
    codes = ", ".join(f"'{code}'" for code, _, _ in _EVENT_TYPES)
    op.execute(f"DELETE FROM narrative.event_types WHERE code IN ({codes});")
