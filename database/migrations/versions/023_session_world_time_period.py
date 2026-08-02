"""Derived fictional-time range for sessions

Revision ID: 023_session_world_time_period
Revises: 022_seed_ruleset
Create Date: 2026-08-02 18:00:00.000000

Purpose:
    Corrective revision (Phase 4 corrections review). campaign.sessions
    stored the world-time endpoint foreign keys and validated their world
    agreement and ordering (revision 011), but unlike campaign.party_memberships
    (revision 009, ADR 0010) it never derived an actual INT8RANGE from them.
    docs/DATABASE_CONVENTIONS.md §12.3 asks for the range to be persisted
    whenever an interval's overlap or containment might ever need to be
    queried, and DATABASE_MODEL.md §6.4 documented "no derived range" as a
    deliberate choice that, on reflection, only holds for the exclusion
    constraint (§12.5) — sessions still benefit from having their interval
    queryable the same way party memberships do, they just must not reject
    overlaps.

    world_time_period follows the same half-open [start, end) contract as
    party_memberships.effective_period:
      - (NULL, NULL) is permitted and means "unscheduled" — world_time_period
        is NULL too.
      - A start with no end produces an unbounded-upper range: the session's
        fictional placement is open (still being played through).
      - A partially specified interval (end without start) was already
        rejected by ck_sessions_end_world_time_requires_start (revision 011);
        this revision does not relax that.
      - A bounded interval requires end.sort_key > start.sort_key, already
        enforced by campaign.enforce_session_world_times().

    No exclusion constraint is added — DATABASE_MODEL.md §6.4's decision that
    overlapping sessions are legitimate (flashbacks, concurrent-party
    sessions) stands. This revision only makes the interval a first-class,
    queryable range; it does not change what is allowed.

Forward migration:
    - campaign.sessions.world_time_period INT8RANGE
    - campaign.enforce_session_world_times() extended to derive it, mirroring
      campaign.sync_party_membership_period()
    - CHECK constraints tying the derived range's nullness/openness to the
      endpoint columns, matching party_memberships' ck_party_memberships_*
      family

Rollback:
    Supported. Drops the column, its constraints, and reverts the trigger
    function to its revision-011 body.

Data implications:
    campaign.sessions is empty outside test fixtures, which roll back.

Locking considerations:
    ADD COLUMN ... NULL is metadata-only.

See: docs/adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md
     docs/architecture/DATABASE_MODEL.md §6.4
     docs/DATABASE_CONVENTIONS.md §12.3, §12.5
     database/migrations/versions/011_sessions.py
     database/migrations/versions/009_parties_and_memberships.py
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "023_session_world_time_period"
down_revision = "022_seed_ruleset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("ALTER TABLE campaign.sessions ADD COLUMN world_time_period INT8RANGE;")
    op.execute("""
        COMMENT ON COLUMN campaign.sessions.world_time_period IS
        'Derived, never client-authoritative: an INT8RANGE over start_world_time_id/'
        'end_world_time_id''s sort_key values, rebuilt by trigger on every INSERT and '
        'UPDATE. NULL when the session is unscheduled (both endpoints NULL). Unlike '
        'party_memberships, there is no exclusion constraint over this column — '
        'overlapping sessions are legitimate (docs/architecture/DATABASE_MODEL.md §6.4).';
    """)

    op.execute("""
        ALTER TABLE campaign.sessions
        ADD CONSTRAINT ck_sessions_period_matches_start
            CHECK ((start_world_time_id IS NULL) = (world_time_period IS NULL));
    """)
    op.execute("""
        ALTER TABLE campaign.sessions
        ADD CONSTRAINT ck_sessions_open_ended_agrees
            CHECK (
                world_time_period IS NULL
                OR (end_world_time_id IS NULL) = upper_inf(world_time_period)
            );
    """)
    op.execute("""
        ALTER TABLE campaign.sessions
        ADD CONSTRAINT ck_sessions_period_not_empty
            CHECK (world_time_period IS NULL OR NOT isempty(world_time_period));
    """)

    # Replace campaign.enforce_session_world_times() with a version that also
    # derives world_time_period, following campaign.sync_party_membership_period()'s
    # shape exactly (revision 009): validate, then unconditionally overwrite the
    # range from the endpoints so callers can never make the two disagree.
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
                NEW.world_time_period := NULL;
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
                NEW.world_time_period := int8range(v_start_sort_key, NULL, '[)');
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

            NEW.world_time_period := int8range(v_start_sort_key, v_end_sort_key, '[)');
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_session_world_times() IS
        'Validates that a session''s world-time endpoints belong to its campaign''s '
        'world and that a bounded pair orders correctly, then derives world_time_period '
        'from them (docs/adr/0010). No exclusion constraint — sessions may overlap.';
    """)


def downgrade() -> None:
    """Revert the migration."""

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
    op.execute(
        "ALTER TABLE campaign.sessions DROP CONSTRAINT IF EXISTS ck_sessions_period_not_empty;"
    )
    op.execute(
        "ALTER TABLE campaign.sessions DROP CONSTRAINT IF EXISTS ck_sessions_open_ended_agrees;"
    )
    op.execute(
        "ALTER TABLE campaign.sessions DROP CONSTRAINT IF EXISTS ck_sessions_period_matches_start;"
    )
    op.execute("ALTER TABLE campaign.sessions DROP COLUMN IF EXISTS world_time_period;")
