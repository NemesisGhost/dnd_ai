"""Recorded events cannot be deleted, directly or via core.entities cascade

Revision ID: 069_event_deletion_protection
Revises: 068_ruleset_check_route_guard
Create Date: 2026-08-06 12:00:00.000000

Purpose:
    Corrective revision (Phase 6 exit-review follow-up, after PR #16).
    Revision 065 made a recorded event's content and status transitions
    immutable via BEFORE UPDATE triggers, but nothing stopped removing the
    row entirely: `DELETE FROM narrative.events` was never guarded, and
    `narrative.events.event_id` is `REFERENCES core.entities(entity_id) ON
    DELETE CASCADE`, so deleting the entity row silently deleted the event
    too. Both paths violate docs/ENTITY_LIFECYCLE.md §15 ("Recorded events
    are immutable. Corrections create new records") and §20 invariant 10
    ("Physical deletion cannot silently destroy history"); §14's allowed
    physical-deletion cases are explicit that only an "unreferenced draft
    created by mistake" may be removed this way — a recorded/voided/
    corrected event is exactly the kind of immutable history §14's
    deletion constraints ("No immutable events may reference the entity")
    are protecting.

Forward migration:
    - narrative.enforce_recorded_event_not_deletable(): BEFORE DELETE
      trigger on narrative.events. Raises unless OLD.event_status is draft.
      Requires no child rows (participants/locations/causes/observations)
      to exist or not — it only inspects OLD.event_status_id, so a
      childless recorded event is rejected exactly the same as one with
      children.

    Blocking the DELETE on narrative.events also blocks the cascade path
    through core.entities: PostgreSQL implements ON DELETE CASCADE by
    issuing an ordinary DELETE against the referencing table, which fires
    that table's own BEFORE DELETE triggers same as a direct DELETE would.
    An attempt to `DELETE FROM core.entities` for a recorded event's
    entity_id therefore aborts the whole statement (and transaction) at
    the cascaded narrative.events delete, before any row is actually
    removed — no second trigger on core.entities is needed.

Rollback:
    Supported. Drops the trigger and function.

Data implications:
    None — no existing row is touched. Every existing narrative.events row
    is already 'recorded' (revision 065's own data-implications note), so
    all of them become undeletable the moment this revision applies, which
    is the correct, intended effect.

Locking considerations:
    One CREATE TRIGGER statement; no table rewrite.

See: docs/ENTITY_LIFECYCLE.md §14 (physical deletion), §15 (event entity
     lifecycle), §20 invariant 10 (physical deletion cannot silently
     destroy history)
     database/migrations/versions/065_recorded_event_immutability.py
     (the companion UPDATE-side immutability this revision completes)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "069_event_deletion_protection"
down_revision = "068_ruleset_check_route_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_recorded_event_not_deletable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_status  TEXT;
        BEGIN
            SELECT code INTO v_status
            FROM narrative.event_statuses WHERE event_status_id = OLD.event_status_id;

            IF v_status IS DISTINCT FROM 'draft' THEN
                RAISE EXCEPTION
                    'Event % is % and cannot be deleted — physical deletion is reserved for '
                    'unreferenced drafts (docs/ENTITY_LIFECYCLE.md §14); a recorded event is '
                    'history and may only be voided or corrected, not removed',
                    OLD.event_id, v_status
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN OLD;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_recorded_event_not_deletable() IS
        'Rejects DELETE on narrative.events unless the row is still draft. Also blocks '
        'deletion reached via core.entities'' ON DELETE CASCADE, since PostgreSQL fires '
        'this same BEFORE DELETE trigger for cascaded deletes (docs/ENTITY_LIFECYCLE.md '
        '§14, §15, §20 invariant 10).';
    """)
    op.execute("""
        CREATE TRIGGER tr_events_enforce_not_deletable
        BEFORE DELETE ON narrative.events
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_recorded_event_not_deletable();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TRIGGER IF EXISTS tr_events_enforce_not_deletable ON narrative.events;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_recorded_event_not_deletable();")
