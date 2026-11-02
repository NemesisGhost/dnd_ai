"""Add campaign.session_participants and one in-progress session per campaign

Revision ID: 123_session_participants
Revises: 122_session_definition
Create Date: 2026-10-06 12:00:00.000000

Purpose:
    Phase 15 checkpoint 15.2D-2 (decision D-14, option a). A session's participants
    are *characters* (never user attendance: that would store personal data without
    need). A GM adds and removes them while running the session. The same revision
    makes the "at most one session in progress per campaign" rule (decision D-13) a
    database invariant, so no race between two start commands can leave two sessions
    playing.

Forward migration:
    - `campaign.session_participants (session_participant_id, session_id,
      character_id, participation_role, added_at, removed_at, added_by_user_id)`.
      `participation_role` is one of `player_character`, `npc`, `guest`
      (`ck_session_participants_role`). `removed_at` is NULL while the character is
      present and never earlier than `added_at`. A partial unique index allows one open
      row per `(session, character)`; a character may be added again after being
      removed (a new row). Foreign keys cascade from the session and the character.
    - `campaign.enforce_session_participant_world()` (BEFORE INSERT): the character
      belongs to the session's campaign's world.
    - `ux_sessions_one_in_progress`: a partial unique index on
      `campaign.sessions (campaign_id) WHERE started_at IS NOT NULL AND ended_at IS
      NULL`.

Rollback:
    Supported. Drops the index, trigger, function and table. Participants are lost;
    downgrade is intended for development databases.

Data implications:
    New empty table. The index fails to build if a campaign already has more than one
    started-but-not-ended session; such a campaign has no valid state to preserve and
    must be corrected before upgrading.

Locking considerations:
    A new empty table; a unique index on the (small) sessions table.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "123_session_participants"
down_revision = "122_session_definition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE campaign.session_participants (
            session_participant_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id              UUID NOT NULL
                                    REFERENCES campaign.sessions(session_id) ON DELETE CASCADE,
            character_id            UUID NOT NULL
                                    REFERENCES character.characters(character_id)
                                    ON DELETE CASCADE,
            participation_role      TEXT NOT NULL,
            added_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            removed_at              TIMESTAMPTZ,
            added_by_user_id        UUID REFERENCES security.users(user_id) ON DELETE SET NULL,
            CONSTRAINT ck_session_participants_role
                CHECK (participation_role IN ('player_character', 'npc', 'guest')),
            CONSTRAINT ck_session_participants_removed_after_added
                CHECK (removed_at IS NULL OR removed_at >= added_at)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.session_participants IS
        'The characters taking part in a session (decision D-14: characters only, never '
        'user attendance). A row is open while removed_at is NULL; a character may be added '
        'again after removal. Presence does not grant access.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.session_participants.participation_role IS
        'player_character, npc, or guest (any character present without a fixed role).';
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_session_participants_open
        ON campaign.session_participants (session_id, character_id)
        WHERE removed_at IS NULL;
    """)
    op.execute(
        "CREATE INDEX ix_session_participants_character_id "
        "ON campaign.session_participants (character_id);"
    )
    op.execute(
        "CREATE INDEX ix_session_participants_added_by_user_id "
        "ON campaign.session_participants (added_by_user_id) WHERE added_by_user_id IS NOT NULL;"
    )
    op.execute("""
        CREATE FUNCTION campaign.enforce_session_participant_world()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_session_world UUID;
            v_character_world UUID;
        BEGIN
            SELECT t.world_id INTO v_session_world
            FROM campaign.sessions s
            JOIN campaign.campaigns c ON c.campaign_id = s.campaign_id
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE s.session_id = NEW.session_id;
            SELECT world_id INTO v_character_world
            FROM core.entities WHERE entity_id = NEW.character_id;
            IF v_session_world IS DISTINCT FROM v_character_world THEN
                RAISE EXCEPTION
                    'character % belongs to world %, but session % belongs to world %',
                    NEW.character_id, v_character_world, NEW.session_id, v_session_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_session_participant_world() IS
        'A participant is a character of the session''s own world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_session_participants_enforce_world
        BEFORE INSERT ON campaign.session_participants
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_session_participant_world();
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_sessions_one_in_progress
        ON campaign.sessions (campaign_id)
        WHERE started_at IS NOT NULL AND ended_at IS NULL;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS campaign.ux_sessions_one_in_progress;")
    op.execute(
        "DROP TRIGGER IF EXISTS tr_session_participants_enforce_world "
        "ON campaign.session_participants;"
    )
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_session_participant_world();")
    op.execute("DROP TABLE IF EXISTS campaign.session_participants;")
