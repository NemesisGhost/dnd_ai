"""Interaction status is irreversible once terminal; check results require an open interaction

Revision ID: 070_interaction_lifecycle_guard
Revises: 069_event_deletion_protection
Create Date: 2026-08-06 13:00:00.000000

Purpose:
    Corrective revision (Phase 6 exit-review follow-up, after PR #16).
    Revision 067 made interaction.actions/.targets/.check_requests/
    .check_results/.external_messages append-only once the parent
    interaction's status leaves 'initiated' — but nothing stopped moving
    the status itself back to 'initiated' afterward, which would silently
    reopen every one of those tables to UPDATE/DELETE again (since
    interaction.enforce_interaction_locked() only inspects the interaction's
    *current* status, not its history). A second, related gap: nothing
    stopped inserting a new interaction.check_results row against an
    interaction that had already finished — revision 067 only guarded
    UPDATE/DELETE on check_results, never INSERT.

Forward migration:
    - interaction.enforce_interaction_status_irreversible(): BEFORE UPDATE
      trigger on interaction.interactions. Once OLD.status is 'resolved',
      'failed', or 'cancelled', rejects any change to NEW.status — those
      three statuses are terminal and, once reached, permanent. No other
      transition is restricted: interactions legitimately move between
      'initiated'/'resolving' and on to any of the three terminal statuses
      as dnd_ai.commands.interactions.resolve_check (this phase's
      correction) requires, and every other column stays exactly as
      mutable as revision 061 designed it (summary, world_time_id via the
      existing consistency trigger, resulting_event_id).
    - interaction.enforce_check_result_interaction_open(): BEFORE INSERT
      trigger on interaction.check_results. Resolves the owning interaction
      via NEW.check_request_id -> check_requests.action_id ->
      actions.interaction_id (the same two-hop path revision 067's
      enforce_check_results_immutable() already uses for UPDATE/DELETE) and
      calls the existing interaction.enforce_interaction_locked() shared
      helper. A check result can only ever be recorded while its
      interaction is still 'initiated' — the same rule revision 067 already
      applies to editing one, now applied to creating one in the first
      place.

Rollback:
    Supported. Drops both triggers and both functions.

Data implications:
    None — no existing row is touched.

Locking considerations:
    Two CREATE TRIGGER statements; no table rewrite.

See: docs/architecture/SYSTEM_ARCHITECTURE.md §6 (command/query separation)
     docs/architecture/DATABASE_MODEL.md §16 (interaction and resolution
     model)
     database/migrations/versions/067_interaction_structural_immutability.py
     (interaction.enforce_interaction_locked(), reused unchanged here)
     src/dnd_ai/commands/interactions.py (resolve_check()'s companion
     application-level interaction lock, added in this same correction pass)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "070_interaction_lifecycle_guard"
down_revision = "069_event_deletion_protection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. interaction.interactions.status becomes irreversible once terminal
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_interaction_status_irreversible()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status IN ('resolved', 'failed', 'cancelled')
               AND NEW.status IS DISTINCT FROM OLD.status
            THEN
                RAISE EXCEPTION
                    'Interaction % has terminal status % and cannot move to % — resolved, '
                    'failed, and cancelled interactions are permanent, since reopening one '
                    'would let its append-only structural records (revision 067) be edited '
                    'again by first reverting the status',
                    OLD.interaction_id, OLD.status, NEW.status
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.enforce_interaction_status_irreversible() IS
        'Once status is resolved/failed/cancelled, rejects any further change to it. Every '
        'other transition (initiated/resolving -> any status) remains unrestricted.';
    """)
    op.execute("""
        CREATE TRIGGER tr_interactions_enforce_status_irreversible
        BEFORE UPDATE ON interaction.interactions
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_interaction_status_irreversible();
    """)

    # ==========================================================================
    # 2. interaction.check_results requires its interaction still be open
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_check_result_interaction_open()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_interaction_id  UUID;
        BEGIN
            SELECT a.interaction_id INTO v_interaction_id
            FROM interaction.check_requests cr
            JOIN interaction.actions a ON a.action_id = cr.action_id
            WHERE cr.check_request_id = NEW.check_request_id;

            PERFORM interaction.enforce_interaction_locked(v_interaction_id);
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.enforce_check_result_interaction_open() IS
        'A check result can only be recorded while its interaction is still initiated — '
        'reuses interaction.enforce_interaction_locked() (revision 067), the same rule '
        'already applied to editing an existing check_results row.';
    """)
    op.execute("""
        CREATE TRIGGER tr_check_results_enforce_interaction_open
        BEFORE INSERT ON interaction.check_results
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_check_result_interaction_open();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "DROP TRIGGER IF EXISTS tr_check_results_enforce_interaction_open "
        "ON interaction.check_results;"
    )
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_check_result_interaction_open();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_interactions_enforce_status_irreversible "
        "ON interaction.interactions;"
    )
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_interaction_status_irreversible();")
