"""Interaction structural records become append-only once resolution begins

Revision ID: 067_interaction_structural_lock
Revises: 066_state_event_timeline_safe
Create Date: 2026-08-05 19:00:00.000000

Purpose:
    Corrective revision (Phase 6 exit-review correction pass). interaction.
    actions/.targets/.check_requests/.check_results/.external_messages are
    all documented as "Append-only" in their own table comments (revision
    061), but nothing enforced it — any of them could be UPDATEd or DELETEd
    after interaction.resolve_check() had already used their contents to
    produce a committed event, effect, and state change, retroactively
    invalidating an applied result with no trace.

    interaction.interactions.status starts at 'initiated' and legitimately
    needs its child rows to stay insertable while building up the
    interaction (perform_interaction() inserts an action, its targets, and
    its check requests together, all while status is still 'initiated').
    Immutability begins once status leaves 'initiated' — the same point
    resolve_check() moves it to 'resolved' (docs/architecture/
    SYSTEM_ARCHITECTURE.md §6, this phase's resolve_check() correction).
    INSERT is never blocked by this revision, only UPDATE and DELETE.

    A single shared helper, interaction.enforce_interaction_locked(), holds
    the "has this interaction left initiated" check; each of the five
    tables gets its own small trigger function only because each reaches
    its owning interaction_id through a different join path (0 hops for
    actions/external_messages, 1 hop through actions for targets/
    check_requests, 2 hops through check_requests -> actions for
    check_results) — PostgreSQL trigger functions cannot be parameterized
    with a computed join path the way core.enforce_immutable_columns() is
    parameterized with column names.

Forward migration:
    - interaction.enforce_interaction_locked(p_interaction_id UUID): shared
      helper, raises when the interaction's status is not 'initiated'.
    - interaction.enforce_actions_immutable() / enforce_external_messages_
      immutable(): BEFORE UPDATE OR DELETE, interaction_id read directly
      from OLD.
    - interaction.enforce_targets_immutable() / enforce_check_requests_
      immutable(): BEFORE UPDATE OR DELETE, interaction_id resolved via
      OLD.action_id -> interaction.actions.interaction_id.
    - interaction.enforce_check_results_immutable(): BEFORE UPDATE OR
      DELETE, interaction_id resolved via OLD.check_request_id ->
      interaction.check_requests.action_id -> interaction.actions.
      interaction_id.

Rollback:
    Supported. Drops all five per-table triggers and functions, then the
    shared helper.

Data implications:
    None — no existing row is touched.

Locking considerations:
    Six CREATE FUNCTION and five CREATE TRIGGER statements; no table
    rewrite.

See: docs/architecture/SYSTEM_ARCHITECTURE.md §6 (command/query separation)
     docs/architecture/DATABASE_MODEL.md §16 (interaction and resolution
     model)
     database/migrations/versions/061_interaction_domain.py (the tables'
     original "Append-only" documentation, unenforced until now)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "067_interaction_structural_lock"
down_revision = "066_state_event_timeline_safe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_interaction_locked(p_interaction_id UUID)
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_status  TEXT;
        BEGIN
            SELECT status INTO v_status
            FROM interaction.interactions WHERE interaction_id = p_interaction_id;

            IF v_status IS DISTINCT FROM 'initiated' THEN
                RAISE EXCEPTION
                    'interaction % has status % and its structural records (actions, '
                    'targets, check requests, check results, external messages) are '
                    'append-only once resolution begins',
                    p_interaction_id, v_status
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.enforce_interaction_locked(UUID) IS
        'Shared helper: raises unless the given interaction is still status = '
        'initiated. Called by each structural table''s own BEFORE UPDATE OR DELETE '
        'trigger function once it has resolved its own interaction_id.';
    """)

    # ---- interaction.actions (interaction_id direct) --------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_actions_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            PERFORM interaction.enforce_interaction_locked(OLD.interaction_id);
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER tr_actions_enforce_immutable
        BEFORE UPDATE OR DELETE ON interaction.actions
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_actions_immutable();
    """)

    # ---- interaction.external_messages (interaction_id direct) ----------------
    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_external_messages_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            PERFORM interaction.enforce_interaction_locked(OLD.interaction_id);
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER tr_external_messages_enforce_immutable
        BEFORE UPDATE OR DELETE ON interaction.external_messages
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_external_messages_immutable();
    """)

    # ---- interaction.targets (via action_id) -----------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_targets_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_interaction_id  UUID;
        BEGIN
            SELECT interaction_id INTO v_interaction_id
            FROM interaction.actions WHERE action_id = OLD.action_id;

            PERFORM interaction.enforce_interaction_locked(v_interaction_id);
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER tr_targets_enforce_immutable
        BEFORE UPDATE OR DELETE ON interaction.targets
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_targets_immutable();
    """)

    # ---- interaction.check_requests (via action_id) ----------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_check_requests_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_interaction_id  UUID;
        BEGIN
            SELECT interaction_id INTO v_interaction_id
            FROM interaction.actions WHERE action_id = OLD.action_id;

            PERFORM interaction.enforce_interaction_locked(v_interaction_id);
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER tr_check_requests_enforce_immutable
        BEFORE UPDATE OR DELETE ON interaction.check_requests
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_check_requests_immutable();
    """)

    # ---- interaction.check_results (via check_request_id -> action_id) --------
    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_check_results_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_interaction_id  UUID;
        BEGIN
            SELECT a.interaction_id INTO v_interaction_id
            FROM interaction.check_requests cr
            JOIN interaction.actions a ON a.action_id = cr.action_id
            WHERE cr.check_request_id = OLD.check_request_id;

            PERFORM interaction.enforce_interaction_locked(v_interaction_id);
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER tr_check_results_enforce_immutable
        BEFORE UPDATE OR DELETE ON interaction.check_results
        FOR EACH ROW EXECUTE FUNCTION interaction.enforce_check_results_immutable();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "DROP TRIGGER IF EXISTS tr_check_results_enforce_immutable ON interaction.check_results;"
    )
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_check_results_immutable();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_check_requests_enforce_immutable ON interaction.check_requests;"
    )
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_check_requests_immutable();")

    op.execute("DROP TRIGGER IF EXISTS tr_targets_enforce_immutable ON interaction.targets;")
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_targets_immutable();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_external_messages_enforce_immutable "
        "ON interaction.external_messages;"
    )
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_external_messages_immutable();")

    op.execute("DROP TRIGGER IF EXISTS tr_actions_enforce_immutable ON interaction.actions;")
    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_actions_immutable();")

    op.execute("DROP FUNCTION IF EXISTS interaction.enforce_interaction_locked(UUID);")
