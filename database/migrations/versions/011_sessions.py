"""Campaign sessions

Revision ID: 011_sessions
Revises: 010_campaigns
Create Date: 2026-08-02 11:00:00.000000

Purpose:
    Delivers campaign.sessions (docs/PLAN.md §5.5), the record of a single
    period of play within a campaign.

    A session deliberately carries both time bases at once: started_at/
    ended_at are real-world TIMESTAMPTZ (when the table actually played), and
    start_world_time_id/end_world_time_id are core.world_times references
    (where the story was in fictional chronology). Neither substitutes for
    the other — DATABASE_CONVENTIONS.md §12 treats them as separate concerns,
    and a session table records both because both are true facts about it.

    Unlike party_memberships (revision 009), sessions do not get a derived
    INT8RANGE or an exclusion constraint. Nothing requires sessions not to
    overlap in fictional time — a flashback session or a session covering two
    parties' concurrent scenes both produce that legitimately. Only ordering
    and world agreement are enforced, by trigger, the same shape as
    campaign.enforce_timeline_branch.

Forward migration:
    - campaign.sessions

Rollback:
    Supported. Drops the table and its trigger function.

Data implications:
    Creates no rows.

Locking considerations:
    None. The table is new and empty.

See: docs/PLAN.md §5.5 (sessions), Phase 3 exit criteria
     docs/architecture/DATABASE_MODEL.md §6.4
     docs/DATABASE_CONVENTIONS.md §12 (temporal conventions)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "011_sessions"
down_revision = "010_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. campaign.sessions
    # ==========================================================================
    # session_number is scoped per campaign (ux_sessions_campaign_number
    # below), not globally — two different campaigns each number their own
    # sessions starting from 1.
    op.execute("""
        CREATE TABLE campaign.sessions (
            session_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id            UUID NOT NULL
                                   REFERENCES campaign.campaigns(campaign_id)
                                   ON DELETE CASCADE,
            session_number         INTEGER NOT NULL,
            title                  TEXT,
            lifecycle_status_id    UUID NOT NULL
                                   REFERENCES core.lifecycle_statuses(lifecycle_status_id)
                                   ON DELETE RESTRICT,
            start_world_time_id    UUID
                                   REFERENCES core.world_times(world_time_id)
                                   ON DELETE RESTRICT,
            end_world_time_id      UUID
                                   REFERENCES core.world_times(world_time_id)
                                   ON DELETE RESTRICT,
            started_at             TIMESTAMPTZ,
            ended_at               TIMESTAMPTZ,
            summary                TEXT,
            source_id              UUID
                                   REFERENCES core.sources(source_id) ON DELETE SET NULL,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT ck_sessions_session_number_positive
                CHECK (session_number > 0),

            CONSTRAINT ck_sessions_ended_requires_started
                CHECK (ended_at IS NULL OR started_at IS NOT NULL),
            CONSTRAINT ck_sessions_ended_after_started
                CHECK (ended_at IS NULL OR ended_at > started_at),

            -- An end world time without a start is not a real interval either.
            CONSTRAINT ck_sessions_end_world_time_requires_start
                CHECK (end_world_time_id IS NULL OR start_world_time_id IS NOT NULL)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.sessions IS
        'A single period of play within a campaign. Carries both real-world time '
        '(started_at/ended_at, when the table actually played) and fictional time '
        '(start/end_world_time_id, where the story was) — see docs/PLAN.md §5.5.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.sessions.summary IS
        'A derived artifact. May be revised freely without changing the events it '
        'summarizes (docs/PLAN.md §5.5).';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.sessions.start_world_time_id IS
        'Where the story was in fictional chronology when the session began. Distinct '
        'from started_at, which is when the table actually played.';
    """)

    op.execute("""
        CREATE TRIGGER tr_sessions_set_updated_at
        BEFORE UPDATE ON campaign.sessions
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    op.execute("""
        CREATE UNIQUE INDEX ux_sessions_campaign_number
        ON campaign.sessions (campaign_id, session_number);
    """)
    op.execute("CREATE INDEX ix_sessions_campaign_id ON campaign.sessions (campaign_id);")
    op.execute(
        "CREATE INDEX ix_sessions_lifecycle_status_id ON campaign.sessions (lifecycle_status_id);"
    )
    op.execute("""
        CREATE INDEX ix_sessions_start_world_time_id
        ON campaign.sessions (start_world_time_id)
        WHERE start_world_time_id IS NOT NULL;
    """)
    op.execute("""
        CREATE INDEX ix_sessions_end_world_time_id
        ON campaign.sessions (end_world_time_id)
        WHERE end_world_time_id IS NOT NULL;
    """)
    op.execute("""
        CREATE INDEX ix_sessions_source_id
        ON campaign.sessions (source_id)
        WHERE source_id IS NOT NULL;
    """)

    # ==========================================================================
    # 2. World-time validation
    # ==========================================================================
    # Two rules that compare across rows and tables, so neither is a CHECK:
    #   1. Both world-time endpoints (when present) belong to the campaign's
    #      world, reached through its timeline.
    #   2. A bounded pair orders correctly: end.sort_key > start.sort_key.
    #
    # No derived range and no exclusion constraint here (see module docstring)
    # — this only validates, it does not prevent overlap.
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_session_world_times()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_campaign_world UUID;
            v_start_world    UUID;
            v_start_sort_key BIGINT;
            v_end_world      UUID;
            v_end_sort_key   BIGINT;
        BEGIN
            IF NEW.start_world_time_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT t.world_id INTO v_campaign_world
            FROM campaign.campaigns c
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE c.campaign_id = NEW.campaign_id;

            SELECT world_id, sort_key INTO v_start_world, v_start_sort_key
            FROM core.world_times WHERE world_time_id = NEW.start_world_time_id;

            IF v_start_world IS DISTINCT FROM v_campaign_world THEN
                RAISE EXCEPTION
                    'Start world time % belongs to world %, but session % belongs to world %',
                    NEW.start_world_time_id, v_start_world, NEW.session_id, v_campaign_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.end_world_time_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT world_id, sort_key INTO v_end_world, v_end_sort_key
            FROM core.world_times WHERE world_time_id = NEW.end_world_time_id;

            IF v_end_world IS DISTINCT FROM v_campaign_world THEN
                RAISE EXCEPTION
                    'End world time % belongs to world %, but session % belongs to world %',
                    NEW.end_world_time_id, v_end_world, NEW.session_id, v_campaign_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF v_end_sort_key <= v_start_sort_key THEN
                RAISE EXCEPTION
                    'Session end (sort_key %) must be later than its start (sort_key %)',
                    v_end_sort_key, v_start_sort_key
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_session_world_times() IS
        'Validates that a session''s world-time endpoints belong to its campaign''s '
        'world and that a bounded pair orders correctly. Unlike party_memberships, this '
        'only validates — sessions have no derived range and no overlap constraint.';
    """)
    op.execute("""
        CREATE TRIGGER tr_sessions_enforce_world_times
        BEFORE INSERT OR UPDATE ON campaign.sessions
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_session_world_times();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS campaign.sessions;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_session_world_times();")
