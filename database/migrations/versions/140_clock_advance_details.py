"""Add narrative.clock_advance_details (member-safe clock advance explanation)

Revision ID: 140_clock_advance_details
Revises: 139_inventory_capability
Create Date: 2026-10-26 12:00:00.000000

Purpose:
    CP-9b / DR-4 (PHASE14_15_INTEGRATION_AND_CONSOLIDATION_PLAN.md). A GM advancing the campaign
    clock may name a gameplay cause and give an explanation meant for the members who can view the
    resulting event. The plan proposed storing that explanation in `narrative.events.details`, but
    `details` is GM-only (data classification `gm_only`; CP-9a withholds it from every non-editor),
    so exposing it would leak every legacy and private value. The explanation therefore needs its
    own, separately classified column, and "this advance was deliberately recorded as a manual
    advance" needs a persisted marker so an older advance without a cause is never guessed to have
    been manual.

Forward migration:
    `narrative.clock_advance_details (event_id PK, member_explanation NULL, created_at)`.
    - A row exists exactly for advances recorded under the CP-9b contract. With a non-clock
      `narrative.event_causes` row the advance has a gameplay cause; without one it is a manual
      advance. Advances recorded earlier have no row and are never labelled either way.
    - `member_explanation` is the only member-visible text: data classification
      `campaign_visible`, shown to any reader who may open the event. 1-500 characters, never
      empty (NULL means none given).
    - `narrative.enforce_clock_advance_detail_event()` (BEFORE INSERT): the event must be a
      `time_advanced` event.
    - Append-only: an UPDATE is refused for every role by trigger.
    No column is added to `narrative.events`, `details` and `event_causes.cause_description` keep
    their GM-only meaning, and the gameplay cause itself is an ordinary `event_causes` row (the
    clock's chain row and the cause are told apart by the cause event's type).

Rollback:
    Drops the table and functions. Member-safe explanations and manual-advance markers are lost
    (the events and their cause links stay); intended for development databases.

Data implications:
    New empty table; no backfill, nothing guessed for existing advances.

Locking considerations:
    A new empty table (no table rewrite, no lock on `narrative.events` rows).
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "140_clock_advance_details"
down_revision = "139_inventory_capability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE narrative.clock_advance_details (
            event_id           UUID PRIMARY KEY
                               REFERENCES narrative.events(event_id) ON DELETE RESTRICT,
            member_explanation TEXT,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_clock_advance_details_explanation_length
                CHECK (member_explanation IS NULL
                       OR char_length(member_explanation) BETWEEN 1 AND 500)
        );
    """)
    op.execute("""
        COMMENT ON TABLE narrative.clock_advance_details IS
        'One row per campaign clock advance recorded under the CP-9b contract: marks the advance as '
        'deliberately recorded (a manual advance when it has no gameplay cause row) and holds the '
        'optional member-safe explanation. Append-only. Advances recorded earlier have no row.';
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.clock_advance_details.member_explanation IS
        'Explanation the GM wrote for the members who may view the advance event. Campaign-visible '
        '(shown with the event); never GM-only text. NULL when none was given.';
    """)
    op.execute("""
        CREATE FUNCTION narrative.enforce_clock_advance_detail_event()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_type TEXT;
        BEGIN
            SELECT et.code INTO v_type
            FROM narrative.events ev
            JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
            WHERE ev.event_id = NEW.event_id;
            IF v_type IS DISTINCT FROM 'time_advanced' THEN
                RAISE EXCEPTION 'event % is not a time_advanced event', NEW.event_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_clock_advance_detail_event() IS
        'Clock advance details may only describe a time_advanced event.';
    """)
    op.execute("""
        CREATE TRIGGER tr_clock_advance_details_enforce_event
        BEFORE INSERT ON narrative.clock_advance_details
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_clock_advance_detail_event();
    """)
    op.execute("""
        CREATE FUNCTION narrative.enforce_clock_advance_detail_append_only()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            RAISE EXCEPTION 'narrative.clock_advance_details is append-only'
                USING ERRCODE = 'integrity_constraint_violation';
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_clock_advance_detail_append_only() IS
        'Refuses every UPDATE of narrative.clock_advance_details (recorded history).';
    """)
    op.execute("""
        CREATE TRIGGER tr_clock_advance_details_append_only
        BEFORE UPDATE ON narrative.clock_advance_details
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_clock_advance_detail_append_only();
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS narrative.clock_advance_details;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_clock_advance_detail_append_only();")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_clock_advance_detail_event();")
