"""Interactions pass through 'resolving' once their first check result lands

Revision ID: 071_resolving_status_transition
Revises: 070_interaction_lifecycle_guard
Create Date: 2026-08-06 15:00:00.000000

Purpose:
    Corrective revision (Phase 6 exit-review follow-up, after PR #16's
    second correction pass). resolve_check() correctly kept a multi-check
    interaction's status at 'initiated' until every check_request had a
    result — but 'initiated' is also the one status revision 067's
    enforce_interaction_locked() treats as unlocked, so a still-'initiated'
    interaction's actions/targets/check_requests/check_results/
    external_messages remained freely UPDATE-/DELETE-able for as long as any
    check was still outstanding. A check resolved first may already have
    produced an immutable narrative.events row, an event_effects row, a
    consequence, and a committed state change — the check_request/
    check_result that caused all of that must become append-only the moment
    it is recorded, not only once the whole interaction finishes.

    interaction.interactions.status already has a 'resolving' value
    (revision 061's own CHECK constraint) that nothing ever set. The fix
    is for the application layer to actually use it — the parent
    interaction now moves to 'resolving' as soon as its first check result
    is recorded (this revision's docstring's companion change, in
    src/dnd_ai/commands/interactions.py's _resolve_interaction()) — and
    for the database to accept that as correct: enforce_interaction_locked()
    (revision 067) already rejects UPDATE/DELETE on structural records for
    any status other than 'initiated', so 'resolving' is already covered by
    that guard without changes. The one place that needed to change is the
    opposite direction: interaction.check_results must still accept new
    INSERTs while 'resolving' (a later check_request's result), which
    revision 070's enforce_check_result_interaction_open() could not do —
    it reused enforce_interaction_locked() unchanged, which only accepts
    'initiated'.

Forward migration:
    - interaction.enforce_interaction_accepting_check_results(p_interaction_id
      UUID) RETURNS void: a narrower sibling of enforce_interaction_locked()
      (revision 067), raising unless the interaction's status is 'initiated'
      or 'resolving'. Terminal statuses (resolved/failed/cancelled) are
      still rejected exactly as before.
    - interaction.enforce_check_result_interaction_open() (revision 070):
      CREATE OR REPLACE to call the new helper instead of
      enforce_interaction_locked(). The existing BEFORE INSERT trigger on
      interaction.check_results needs no change — only the function body
      it calls does.

Rollback:
    Supported. Restores enforce_check_result_interaction_open() to its
    revision-070 body (calling enforce_interaction_locked() again), then
    drops the new helper function.

Data implications:
    None — no existing row is touched.

Locking considerations:
    Two CREATE OR REPLACE FUNCTION statements; no table rewrite, no new
    trigger.

See: docs/architecture/DATABASE_MODEL.md §16 (interaction and resolution
     model)
     database/migrations/versions/067_interaction_structural_immutability.py
     (interaction.enforce_interaction_locked(), unchanged, still the only
     guard for UPDATE/DELETE)
     database/migrations/versions/070_interaction_lifecycle_guard.py
     (interaction.enforce_check_result_interaction_open(), whose body this
     revision replaces)
     src/dnd_ai/commands/interactions.py (_resolve_interaction(), the
     application-side change that actually starts using 'resolving')
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "071_resolving_status_transition"
down_revision = "070_interaction_lifecycle_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        CREATE OR REPLACE FUNCTION interaction.enforce_interaction_accepting_check_results(
            p_interaction_id UUID
        )
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_status  TEXT;
        BEGIN
            SELECT status INTO v_status
            FROM interaction.interactions WHERE interaction_id = p_interaction_id;

            IF v_status NOT IN ('initiated', 'resolving') THEN
                RAISE EXCEPTION
                    'interaction % has status % and cannot accept another check result — '
                    'resolved, failed, and cancelled interactions are terminal',
                    p_interaction_id, v_status
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.enforce_interaction_accepting_check_results(UUID) IS
        'Shared helper: raises unless the given interaction is still initiated or resolving. '
        'Narrower sibling of interaction.enforce_interaction_locked() (revision 067, which '
        'only accepts initiated) — used solely by interaction.check_results'' INSERT guard, '
        'since a still-outstanding check_request must remain answerable while an earlier '
        'one has already moved the interaction to resolving.';
    """)
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

            PERFORM interaction.enforce_interaction_accepting_check_results(v_interaction_id);
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION interaction.enforce_check_result_interaction_open() IS
        'A check result can be recorded while its interaction is initiated or resolving — '
        'rejected once the interaction is terminal. Uses interaction.enforce_interaction_'
        'accepting_check_results() (revision 071), not enforce_interaction_locked() (revision '
        '067, which is reserved for the UPDATE/DELETE structural guards that must reject '
        'resolving too).';
    """)


def downgrade() -> None:
    """Revert the migration."""

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
    op.execute(
        "DROP FUNCTION IF EXISTS interaction.enforce_interaction_accepting_check_results(UUID);"
    )
