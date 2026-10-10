"""Add session versioning, scheduling, and archive bookkeeping (campaign.sessions)

Revision ID: 122_session_definition
Revises: 121_party_membership_events
Create Date: 2026-10-06 09:00:00.000000

Purpose:
    Phase 15 checkpoint 15.2D-1 (decision D-13, option a). A GM schedules, edits,
    archives, and restores sessions. A session's play status is *derived* from
    `scheduled_for`, `started_at`, and `ended_at` (unscheduled, scheduled, in
    progress, completed); `lifecycle_status_id` carries only `active` / `archived`.
    The play commands (start, participants, log) arrive with checkpoint 15.2D-2.

Forward migration:
    On `campaign.sessions`:
    - `row_version BIGINT NOT NULL DEFAULT 1` (CHECK >= 1), bumped by
      `core.bump_row_version()`.
    - `scheduled_for TIMESTAMPTZ NULL`: the planned real-world start. It is a plan,
      not history, and may be changed or cleared until the session starts.
    - `archived_at TIMESTAMPTZ NULL`: set when archived, cleared on restore.
    - `created_by_user_id UUID NULL REFERENCES security.users ON DELETE SET NULL`
      and a partial index for it.
    `(campaign_id, session_number)` is already unique (`ux_sessions_campaign_number`),
    which is the backstop for server-assigned numbering.

Rollback:
    Supported. Drops the trigger, columns, and index. Scheduling, archive time, and
    versions are lost; downgrade is intended for development databases.

Data implications:
    Existing sessions get version 1, no schedule, no archive time, no creator.

Locking considerations:
    ADD COLUMN with a constant default or NULL is metadata-only.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "122_session_definition"
down_revision = "121_party_membership_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE campaign.sessions
        ADD COLUMN row_version BIGINT NOT NULL DEFAULT 1,
        ADD CONSTRAINT ck_sessions_row_version_positive CHECK (row_version >= 1),
        ADD COLUMN scheduled_for TIMESTAMPTZ,
        ADD COLUMN archived_at TIMESTAMPTZ,
        ADD COLUMN created_by_user_id UUID
            REFERENCES security.users(user_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.sessions.row_version IS
        'Optimistic-concurrency token, incremented by every UPDATE '
        '(core.bump_row_version()). Authoring commands require the caller''s '
        'expected_row_version to equal it under a row lock and reject a stale write.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.sessions.scheduled_for IS
        'The planned real-world start of the session. A plan, not history: it may be changed '
        'or cleared until the session starts. Play status is derived from this, started_at, '
        'and ended_at.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.sessions.archived_at IS
        'When the session was archived; NULL while active.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.sessions.created_by_user_id IS
        'The authenticated human who scheduled the session through the authoring command; NULL '
        'for sessions created before revision 122 or by operator tooling.';
    """)
    op.execute(
        "CREATE INDEX ix_sessions_created_by_user_id ON campaign.sessions (created_by_user_id) "
        "WHERE created_by_user_id IS NOT NULL;"
    )
    op.execute("""
        CREATE TRIGGER tr_sessions_bump_row_version
        BEFORE UPDATE ON campaign.sessions
        FOR EACH ROW EXECUTE FUNCTION core.bump_row_version();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tr_sessions_bump_row_version ON campaign.sessions;")
    op.execute("DROP INDEX IF EXISTS campaign.ix_sessions_created_by_user_id;")
    op.execute("""
        ALTER TABLE campaign.sessions
        DROP COLUMN IF EXISTS created_by_user_id,
        DROP COLUMN IF EXISTS archived_at,
        DROP COLUMN IF EXISTS scheduled_for,
        DROP CONSTRAINT IF EXISTS ck_sessions_row_version_positive,
        DROP COLUMN IF EXISTS row_version;
    """)
