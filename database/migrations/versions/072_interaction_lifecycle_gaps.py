"""Database-owned interaction status advance; structural rows lock at creation time

Revision ID: 072_interaction_lifecycle_gaps
Revises: 071_resolving_status_transition
Create Date: 2026-08-07 09:00:00.000000

Purpose:
    Corrective revision (Phase 6 exit-review follow-up, after PR #16's
    third correction pass). Two related gaps survived that pass because
    they lived in the database, not in resolve_check() itself:

    1. Revision 071 lets interaction.check_results accept an INSERT while
       the parent interaction is 'initiated' or 'resolving' — but nothing
       in the database ever advances that status. Only
       src/dnd_ai/commands/interactions.py's resolve_check() did, in a
       separate statement after the INSERT. A caller inserting a check
       result directly (or any future command that isn't resolve_check())
       could leave the interaction at 'initiated' indefinitely, which
       interaction.enforce_interaction_locked() (revision 067) treats as
       fully unlocked — exactly the bypass the 'resolving' status was
       introduced to close, just reached by skipping the one command that
       knew to set it.
    2. interaction.actions/.targets/.check_requests reject UPDATE/DELETE
       once the interaction leaves 'initiated' (revision 067), but nothing
       ever stopped inserting a *new* one after that point. A resolved
       interaction could acquire a brand new, unanswered check_request,
       which is incoherent — 'resolved' is supposed to mean every required
       check has already been answered — and would also permanently strand
       that request unanswerable (revision 071's guard only allows
       check_results while initiated/resolving, and this revision closes
       the 'resolving' half of that same window for the requests
       themselves).

Forward migration:
    - interaction.advance_interaction_status_on_check_result(): AFTER
      INSERT trigger on interaction.check_results. Locks the parent
      interaction (SELECT ... FOR UPDATE, the same row-locking pattern
      resolve_check() already uses), counts total check_requests versus
      those with a result across every action the interaction has, and
      sets status to 'resolved' once none remain outstanding or (only
      while still 'initiated') to 'resolving' otherwise. A single-check
      interaction's only result satisfies both conditions at once and
      goes straight to 'resolved'. If the interaction is already terminal
      by the time the lock is acquired (a concurrent administrative
      cancellation racing a check result whose INSERT the BEFORE trigger
      had already permitted), the status is left alone rather than
      raising — the row was already validly inserted.
    - interaction.enforce_actions_creatable() / enforce_targets_creatable()
      / enforce_check_requests_creatable(): BEFORE INSERT triggers on
      actions/targets/check_requests respectively, each resolving the
      target interaction_id (direct on actions; via action_id ->
      actions.interaction_id for targets/check_requests — the same join
      depths revision 067's UPDATE/DELETE guards already use) and calling
      the existing interaction.enforce_interaction_locked() (revision 067)
      unchanged — the same "must still be initiated" rule that already
      governs editing one of these rows now also governs creating one.
      interaction.check_results and .external_messages are deliberately
      not touched here: check_results already has its own, more permissive
      initiated-or-resolving INSERT guard (revisions 070-071), and
      external_messages carries no "required check" invariant to protect.

    src/dnd_ai/commands/interactions.py's resolve_check() no longer sets
    interaction.interactions.status itself — the trigger above now owns
    that transition atomically with the check_results INSERT it already
    performs, so the separate application-level UPDATE was fully
    redundant. Event linkage (resulting_event_id, the consequence row)
    remains application logic, since the database has no way to know
    which event a check produced.

Rollback:
    Supported. Drops all four new triggers and functions.

Data implications:
    None — no existing row is touched.

Locking considerations:
    Four CREATE TRIGGER / CREATE FUNCTION statements; no table rewrite.

See: docs/architecture/DATABASE_MODEL.md §16 (interaction and resolution
     model)
     database/migrations/versions/067_interaction_structural_immutability.py
     (interaction.enforce_interaction_locked(), reused unchanged for the
     three new creation guards)
     database/migrations/versions/070_interaction_lifecycle_guard.py
     database/migrations/versions/071_resolving_status_transition.py
     (the status values and check_results INSERT guard this revision
     builds on)
     src/dnd_ai/commands/interactions.py (resolve_check(), whose status
     UPDATE this revision makes redundant and removes)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "072_interaction_lifecycle_gaps"
down_revision = "071_resolving_status_transition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. interaction.interactions.status advances atomically with a
    #    check_results INSERT, regardless of caller.
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.advance_interaction_status_on_check_result()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_interaction_id  UUID;
            v_status          TEXT;
            v_total           INT;
            v_resolved        INT;
        BEGIN
            SELECT a.interaction_id INTO v_interaction_id
            FROM interaction.check_requests cr
            JOIN interaction.actions a ON a.action_id = cr.action_id
            WHERE cr.check_request_id = NEW.check_request_id;

            SELECT status INTO v_status
            FROM interaction.interactions WHERE interaction_id = v_interaction_id
            FOR UPDATE;

            IF v_status IN ('resolved', 'failed', 'cancelled') THEN
                -- Already terminal by the time the lock was acquired (the
                -- BEFORE INSERT guard already permitted this row when it
                -- was still initiated/resolving); leave status alone.
                RETURN NEW;
            END IF;

            SELECT count(cr.check_request_id), count(res.check_result_id)
            INTO v_total, v_resolved
            FROM interaction.check_requests cr
            JOIN interaction.actions a ON a.action_id = cr.action_id
            LEFT JOIN interaction.check_results res ON res.check_request_id = cr.check_request_id
            WHERE a.interaction_id = v_interaction_id;

            IF v_resolved >= v_total THEN
                UPDATE interaction.interactions SET status = 'resolved'
                WHERE interaction_id = v_interaction_id;
            ELSIF v_status = 'initiated' THEN
                UPDATE interaction.interactions SET status = 'resolving'
                WHERE interaction_id = v_interaction_id;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.advance_interaction_status_on_check_result() IS
        'Atomically with a check_results INSERT: moves the parent interaction to resolving '
        'on the first still-incomplete result, or to resolved once every check_request it '
        'has (across all its actions) has one. Owns the status transition regardless of '
        'caller, so resolve_check() no longer needs to set it separately.';
    """)
    op.execute("""
        CREATE TRIGGER tr_check_results_advance_interaction_status
        AFTER INSERT ON interaction.check_results
        FOR EACH ROW EXECUTE FUNCTION interaction.advance_interaction_status_on_check_result();
    """)

    # ==========================================================================
    # 2. interaction.actions/.targets/.check_requests can only be created
    #    while the interaction is still initiated.
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_actions_creatable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            PERFORM interaction.enforce_interaction_locked(NEW.interaction_id);
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER tr_actions_enforce_creatable
        BEFORE INSERT ON interaction.actions
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_actions_creatable();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_targets_creatable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_interaction_id  UUID;
        BEGIN
            SELECT interaction_id INTO v_interaction_id
            FROM interaction.actions WHERE action_id = NEW.action_id;

            PERFORM interaction.enforce_interaction_locked(v_interaction_id);
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER tr_targets_enforce_creatable
        BEFORE INSERT ON interaction.targets
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_targets_creatable();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_check_requests_creatable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_interaction_id  UUID;
        BEGIN
            SELECT interaction_id INTO v_interaction_id
            FROM interaction.actions WHERE action_id = NEW.action_id;

            PERFORM interaction.enforce_interaction_locked(v_interaction_id);
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER tr_check_requests_enforce_creatable
        BEFORE INSERT ON interaction.check_requests
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_check_requests_creatable();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "DROP TRIGGER IF EXISTS tr_check_requests_enforce_creatable ON interaction.check_requests;"
    )
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_check_requests_creatable();")

    op.execute("DROP TRIGGER IF EXISTS tr_targets_enforce_creatable ON interaction.targets;")
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_targets_creatable();")

    op.execute("DROP TRIGGER IF EXISTS tr_actions_enforce_creatable ON interaction.actions;")
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_actions_creatable();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_check_results_advance_interaction_status "
        "ON interaction.check_results;"
    )
    op.execute("DROP FUNCTION IF EXISTS interaction.advance_interaction_status_on_check_result();")
