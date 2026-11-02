"""Add join/leave event provenance to campaign.party_memberships

Revision ID: 121_party_membership_events
Revises: 120_party_definition
Create Date: 2026-10-05 22:00:00.000000

Purpose:
    Phase 15 checkpoint 15.2C-2. Party membership is typed timeline state, so every
    change needs a causal event (rule 6). Adding a member records a
    `party_member_joined` event and ending a membership records a `party_member_left`
    event; the membership row cites them so history says who joined or left when and
    why. Corrections to those events arrive with checkpoint 15.2E-1.

Forward migration:
    - `narrative.event_types`: `party_member_joined`, `party_member_left`
      (`ON CONFLICT (code) DO NOTHING`).
    - `campaign.party_memberships.joined_event_id` and `left_event_id`, nullable
      foreign keys to `narrative.events` (`ON DELETE SET NULL`), each with a partial
      index. Rows created before this revision keep NULL.
    - `ck_party_memberships_left_event_needs_end`: a left event only on an ended
      membership.
    - `campaign.enforce_party_membership_events()` (BEFORE INSERT OR UPDATE): both
      events must belong to the membership's own timeline (the same rule
      `campaign.enforce_state_event_timeline()` applies to `last_event_id`).

Rollback:
    Supported. Drops the trigger, function, check, indexes, and columns, and deletes
    the two event types. It fails (foreign key) once any event of those types exists,
    which is the safe outcome; downgrade is intended for development databases.

Data implications:
    Two lookup rows and two NULL columns on existing rows.

Locking considerations:
    ADD COLUMN without a default is metadata-only; the check constrains a column that
    is NULL for every existing row, so its validation is trivial.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "121_party_membership_events"
down_revision = "120_party_definition"
branch_labels = None
depends_on = None

_EVENT_TYPES = (
    ("party_member_joined", "Party Member Joined", 125),
    ("party_member_left", "Party Member Left", 126),
)


def upgrade() -> None:
    for code, display_name, sort_order in _EVENT_TYPES:
        op.execute(f"""
            INSERT INTO narrative.event_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)
    op.execute("""
        ALTER TABLE campaign.party_memberships
        ADD COLUMN joined_event_id UUID REFERENCES narrative.events(event_id) ON DELETE SET NULL,
        ADD COLUMN left_event_id UUID REFERENCES narrative.events(event_id) ON DELETE SET NULL,
        ADD CONSTRAINT ck_party_memberships_left_event_needs_end
            CHECK (left_event_id IS NULL OR effective_to_world_time_id IS NOT NULL);
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.party_memberships.joined_event_id IS
        'The party_member_joined event that recorded this membership (same timeline); '
        'NULL for rows created before revision 121.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.party_memberships.left_event_id IS
        'The party_member_left event that ended this membership (same timeline); NULL while '
        'open and for rows ended before revision 121.';
    """)
    op.execute(
        "CREATE INDEX ix_party_memberships_joined_event_id "
        "ON campaign.party_memberships (joined_event_id) WHERE joined_event_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_party_memberships_left_event_id "
        "ON campaign.party_memberships (left_event_id) WHERE left_event_id IS NOT NULL;"
    )
    op.execute("""
        CREATE FUNCTION campaign.enforce_party_membership_events()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_timeline UUID;
        BEGIN
            IF NEW.joined_event_id IS NOT NULL THEN
                SELECT timeline_id INTO v_timeline
                FROM narrative.events WHERE event_id = NEW.joined_event_id;
                IF v_timeline IS DISTINCT FROM NEW.timeline_id THEN
                    RAISE EXCEPTION
                        'joined_event_id % belongs to timeline %, but the membership belongs to %',
                        NEW.joined_event_id, v_timeline, NEW.timeline_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            IF NEW.left_event_id IS NOT NULL THEN
                SELECT timeline_id INTO v_timeline
                FROM narrative.events WHERE event_id = NEW.left_event_id;
                IF v_timeline IS DISTINCT FROM NEW.timeline_id THEN
                    RAISE EXCEPTION
                        'left_event_id % belongs to timeline %, but the membership belongs to %',
                        NEW.left_event_id, v_timeline, NEW.timeline_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_party_membership_events() IS
        'A membership cites join and leave events of its own timeline only.';
    """)
    op.execute("""
        CREATE TRIGGER tr_party_memberships_enforce_events
        BEFORE INSERT OR UPDATE ON campaign.party_memberships
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_party_membership_events();
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS tr_party_memberships_enforce_events ON campaign.party_memberships;"
    )
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_party_membership_events();")
    op.execute("DROP INDEX IF EXISTS campaign.ix_party_memberships_left_event_id;")
    op.execute("DROP INDEX IF EXISTS campaign.ix_party_memberships_joined_event_id;")
    op.execute("""
        ALTER TABLE campaign.party_memberships
        DROP CONSTRAINT IF EXISTS ck_party_memberships_left_event_needs_end,
        DROP COLUMN IF EXISTS left_event_id,
        DROP COLUMN IF EXISTS joined_event_id;
    """)
    codes = ", ".join(f"'{code}'" for code, _, _ in _EVENT_TYPES)
    op.execute(f"DELETE FROM narrative.event_types WHERE code IN ({codes});")
