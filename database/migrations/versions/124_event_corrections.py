"""Add narrative.event_corrections (history-preserving void and correct)

Revision ID: 124_event_corrections
Revises: 123_session_participants
Create Date: 2026-10-06 18:00:00.000000

Purpose:
    Phase 15 checkpoint 15.2E-1 (decision D-15, option a). A recorded event is
    immutable (revision 065) and may only move to `voided` or `corrected`
    (`narrative.enforce_recorded_event_immutable`). Nothing yet said *why*, or what
    undid its effects. This table is that link: one row per corrected event, naming
    the correcting event that carries the compensating effects, the reason, and (for a
    correction) the replacement event.

Forward migration:
    `narrative.event_corrections (event_correction_id, corrected_event_id UNIQUE,
    correcting_event_id, replacement_event_id, correction_kind void|correct, reason,
    created_by_user_id, created_at)`.
    - `corrected_event_id` is unique: an event is corrected at most once.
    - `ck_event_corrections_replacement_only_for_correct`: only a correction names a
      replacement.
    - `narrative.enforce_event_correction_timelines()` (BEFORE INSERT): the corrected,
      correcting, and replacement events share one timeline.
    - Append-only: an UPDATE is refused for every role by trigger.
    - `narrative.enforce_event_status_has_correction()` (deferred constraint trigger on
      `narrative.events`): an event may be `voided` or `corrected` only if a correction
      row of the matching kind exists by commit, so a status can never change without
      its link.

Rollback:
    Drops the triggers, functions and table. Correction links are lost (the events keep
    their `voided` / `corrected` status, which then has no explanation); downgrade is
    intended for development databases.

Data implications:
    New empty table. Events already `voided` or `corrected` (only possible by direct
    SQL today) are not affected: the trigger fires only on a status change.

Locking considerations:
    A new empty table and a trigger on `narrative.events` (no table rewrite).
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "124_event_corrections"
down_revision = "123_session_participants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE narrative.event_corrections (
            event_correction_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            corrected_event_id   UUID NOT NULL
                                 REFERENCES narrative.events(event_id) ON DELETE RESTRICT,
            correcting_event_id  UUID NOT NULL
                                 REFERENCES narrative.events(event_id) ON DELETE RESTRICT,
            replacement_event_id UUID
                                 REFERENCES narrative.events(event_id) ON DELETE RESTRICT,
            correction_kind      TEXT NOT NULL,
            reason               TEXT NOT NULL,
            created_by_user_id   UUID REFERENCES security.users(user_id) ON DELETE SET NULL,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_event_corrections_corrected UNIQUE (corrected_event_id),
            CONSTRAINT ck_event_corrections_kind CHECK (correction_kind IN ('void', 'correct')),
            CONSTRAINT ck_event_corrections_reason_length
                CHECK (char_length(reason) BETWEEN 1 AND 1000),
            CONSTRAINT ck_event_corrections_distinct
                CHECK (corrected_event_id <> correcting_event_id),
            CONSTRAINT ck_event_corrections_replacement_only_for_correct
                CHECK (replacement_event_id IS NULL OR correction_kind = 'correct')
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.event_corrections IS
        'The link from a corrected or voided event to the correcting event that carries its '
        'compensating effects, the reason, and (for a correction) the replacement event '
        '(decision D-15). Append-only; an event is corrected at most once.';
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.event_corrections.reason IS
        'Why the event was voided or corrected. GM-only.';
    """)
    op.execute(
        "CREATE INDEX ix_event_corrections_correcting_event_id "
        "ON narrative.event_corrections (correcting_event_id);"
    )
    op.execute(
        "CREATE INDEX ix_event_corrections_replacement_event_id "
        "ON narrative.event_corrections (replacement_event_id) "
        "WHERE replacement_event_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_event_corrections_created_by_user_id "
        "ON narrative.event_corrections (created_by_user_id) "
        "WHERE created_by_user_id IS NOT NULL;"
    )

    op.execute("""
        CREATE FUNCTION narrative.enforce_event_correction_timelines()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_timeline UUID;
            v_other    UUID;
        BEGIN
            SELECT timeline_id INTO v_timeline
            FROM narrative.events WHERE event_id = NEW.corrected_event_id;
            SELECT timeline_id INTO v_other
            FROM narrative.events WHERE event_id = NEW.correcting_event_id;
            IF v_other IS DISTINCT FROM v_timeline THEN
                RAISE EXCEPTION
                    'correcting event % is on timeline %, but the corrected event is on %',
                    NEW.correcting_event_id, v_other, v_timeline
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.replacement_event_id IS NOT NULL THEN
                SELECT timeline_id INTO v_other
                FROM narrative.events WHERE event_id = NEW.replacement_event_id;
                IF v_other IS DISTINCT FROM v_timeline THEN
                    RAISE EXCEPTION
                        'replacement event % is on timeline %, but the corrected event is on %',
                        NEW.replacement_event_id, v_other, v_timeline
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_event_correction_timelines() IS
        'The corrected, correcting, and replacement events of a correction share one timeline.';
    """)
    op.execute("""
        CREATE TRIGGER tr_event_corrections_enforce_timelines
        BEFORE INSERT ON narrative.event_corrections
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_event_correction_timelines();
    """)

    op.execute("""
        CREATE FUNCTION narrative.enforce_event_correction_append_only()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            RAISE EXCEPTION 'narrative.event_corrections is append-only'
                USING ERRCODE = 'integrity_constraint_violation';
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_event_correction_append_only() IS
        'Refuses every UPDATE of narrative.event_corrections (a correction is permanent history).';
    """)
    op.execute("""
        CREATE TRIGGER tr_event_corrections_append_only
        BEFORE UPDATE ON narrative.event_corrections
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_event_correction_append_only();
    """)

    op.execute("""
        CREATE FUNCTION narrative.enforce_event_status_has_correction()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_old  TEXT;
            v_new  TEXT;
            v_kind TEXT;
        BEGIN
            SELECT code INTO v_old FROM narrative.event_statuses
            WHERE event_status_id = OLD.event_status_id;
            SELECT code INTO v_new FROM narrative.event_statuses
            WHERE event_status_id = NEW.event_status_id;
            IF v_new IN ('voided', 'corrected') AND v_old IS DISTINCT FROM v_new THEN
                SELECT correction_kind INTO v_kind
                FROM narrative.event_corrections WHERE corrected_event_id = NEW.event_id;
                IF v_kind IS NULL
                   OR (v_new = 'voided' AND v_kind <> 'void')
                   OR (v_new = 'corrected' AND v_kind <> 'correct') THEN
                    RAISE EXCEPTION
                        'event % cannot become % without a matching correction record',
                        NEW.event_id, v_new
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            RETURN NULL;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_event_status_has_correction() IS
        'An event may become voided or corrected only with a matching narrative.event_corrections '
        'row by commit (deferred), so a status never changes without its link.';
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER ctr_events_status_has_correction
        AFTER UPDATE OF event_status_id ON narrative.events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_event_status_has_correction();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ctr_events_status_has_correction ON narrative.events;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_event_status_has_correction();")
    op.execute("DROP TABLE IF EXISTS narrative.event_corrections;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_event_correction_append_only();")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_event_correction_timelines();")
