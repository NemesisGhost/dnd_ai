"""Recorded-event immutability

Revision ID: 065_recorded_event_immutable
Revises: 064_conditional_route_evaluation
Create Date: 2026-08-05 18:00:00.000000

Purpose:
    Corrective revision (Phase 6 exit-review correction pass). docs/
    ENTITY_LIFECYCLE.md §15 states "Recorded events are immutable.
    Corrections create new records," §20 invariant 6 restates it ("Recorded
    events are not edited in place"), and §22's acceptance tests require
    proving "a recorded event cannot be edited directly." Nothing enforced
    this: narrative.events, its inherited core.entities metadata, and its
    four append-only satellite tables (event_participants, event_locations,
    event_causes, event_observations) could all be freely UPDATEd or
    DELETEd after the event reached event_status = recorded.

    A narrative.events row and its core.entities row are both still
    genuinely editable while event_status = draft — "assembled but not
    committed as history" (ENTITY_LIFECYCLE.md §15) is exactly the state a
    draft is allowed to be revised in. Immutability begins the moment the
    status leaves draft, which is also the only state transition this
    revision allows: draft -> recorded, and (once recorded) recorded ->
    voided or recorded -> corrected. Every other transition (including
    voided/corrected -> anything, or recorded -> draft) is rejected. No
    VoidEvent/CorrectEvent command exists yet (src/dnd_ai/commands has no
    such handler) — this revision only makes the transitions the database
    will accept once one is built; it does not build the command itself.

Forward migration:
    - narrative.enforce_recorded_event_immutable(): BEFORE UPDATE trigger on
      narrative.events. While OLD.event_status is draft, all columns remain
      editable (subject to the existing narrative.enforce_event_consistency()
      trigger) except that a status change away from draft must go to
      recorded. Once OLD.event_status is recorded/voided/corrected,
      timeline_id/campaign_id/session_id/event_type_id/world_time_id/details
      are frozen, and event_status_id may only move recorded -> voided or
      recorded -> corrected.
    - narrative.enforce_recorded_event_entity_immutable(): BEFORE UPDATE
      trigger on core.entities. A no-op for any entity that isn't an event,
      or whose narrative.events row doesn't exist yet (mid-transaction CTI
      construction) or is still draft. Once the event is recorded/voided/
      corrected, freezes canonical_name/summary/canon_status_id/source_id/
      created_by_user_id — the identity/content columns core.entities
      contributes to an event. entity_type_id is already protected from
      being changed away from 'event' by core.enforce_entity_type_change()
      (revision 048) as long as the narrative.events row exists, which it
      always does once recorded. lifecycle_status_id/archived_at are left
      mutable: archival (docs/ENTITY_LIFECYCLE.md §12) is an operational
      dimension independent of content immutability, not a content edit.
    - narrative.enforce_recorded_event_child_immutable(): shared BEFORE
      UPDATE OR DELETE trigger function attached to event_participants,
      event_locations, event_causes, and event_observations. Blocks both
      operations once the parent event (via each row's own event_id) is no
      longer draft. narrative.event_effects is deliberately not included —
      it already carries its own mutable application_status lifecycle
      (pending/applied/failed/skipped), which is a different, already-
      designed-for-mutation concern (revision 057's own docstring).

Rollback:
    Supported. Drops both new trigger functions and all six new triggers.

Data implications:
    No existing narrative.events row is at any status other than 'recorded'
    (record_event() always creates at 'recorded' — no draft/voided/corrected
    row exists yet), so every existing row becomes immutable the moment this
    revision applies. This is the correct, intended effect, not a side
    effect to guard against.

Locking considerations:
    Six CREATE TRIGGER statements; no table rewrite.

See: docs/ENTITY_LIFECYCLE.md §15 (event entity lifecycle), §20 invariant 6,
     §22 (acceptance tests)
     docs/architecture/DATABASE_MODEL.md §12 (events and effects)
     database/migrations/versions/030_parent_scope_immutability.py
     (core.enforce_immutable_columns() — unconditional immutability; this
     revision needs conditional-on-status immutability instead, so it adds
     dedicated functions rather than reusing that one)
     database/migrations/versions/048_entity_type_change_protection.py
     (core.enforce_entity_type_change() — already protects entity_type_id
     while a subtype row exists)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "065_recorded_event_immutable"
down_revision = "064_conditional_route_evaluation"
branch_labels = None
depends_on = None

CHILD_TABLES = [
    "event_participants",
    "event_locations",
    "event_causes",
    "event_observations",
]


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. narrative.events content/status-transition guard
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_recorded_event_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_old_status  TEXT;
            v_new_status  TEXT;
        BEGIN
            SELECT code INTO v_old_status
            FROM narrative.event_statuses WHERE event_status_id = OLD.event_status_id;

            SELECT code INTO v_new_status
            FROM narrative.event_statuses WHERE event_status_id = NEW.event_status_id;

            IF v_old_status = 'draft' THEN
                IF v_new_status IS DISTINCT FROM 'draft' AND v_new_status IS DISTINCT FROM 'recorded'
                THEN
                    RAISE EXCEPTION
                        'Event % cannot move from status draft to %; the only valid '
                        'transition out of draft is to recorded',
                        NEW.event_id, v_new_status
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.timeline_id IS DISTINCT FROM OLD.timeline_id
               OR NEW.campaign_id IS DISTINCT FROM OLD.campaign_id
               OR NEW.session_id IS DISTINCT FROM OLD.session_id
               OR NEW.event_type_id IS DISTINCT FROM OLD.event_type_id
               OR NEW.world_time_id IS DISTINCT FROM OLD.world_time_id
               OR NEW.details IS DISTINCT FROM OLD.details
            THEN
                RAISE EXCEPTION
                    'Event % is % and its content is immutable — corrections create a '
                    'new record (docs/ENTITY_LIFECYCLE.md §15), they do not edit this one',
                    OLD.event_id, v_old_status
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF v_new_status IS DISTINCT FROM v_old_status THEN
                IF NOT (v_old_status = 'recorded' AND v_new_status IN ('voided', 'corrected')) THEN
                    RAISE EXCEPTION
                        'Event % cannot move from status % to %; recorded events may only '
                        'transition to voided or corrected',
                        OLD.event_id, v_old_status, v_new_status
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_recorded_event_immutable() IS
        'While an event is draft, its content and status remain freely editable '
        'except that leaving draft must go to recorded. Once recorded (or voided/'
        'corrected), timeline_id/campaign_id/session_id/event_type_id/world_time_id/'
        'details are frozen and event_status_id may only move recorded -> voided or '
        'recorded -> corrected (docs/ENTITY_LIFECYCLE.md §15, §22).';
    """)
    op.execute("""
        CREATE TRIGGER tr_events_enforce_recorded_immutable
        BEFORE UPDATE ON narrative.events
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_recorded_event_immutable();
    """)

    # ==========================================================================
    # 2. core.entities content guard for event-typed entities
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_recorded_event_entity_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_entity_type_code   TEXT;
            v_event_status_code  TEXT;
        BEGIN
            SELECT code INTO v_entity_type_code
            FROM core.entity_types WHERE entity_type_id = OLD.entity_type_id;

            IF v_entity_type_code IS DISTINCT FROM 'event' THEN
                RETURN NEW;
            END IF;

            SELECT es.code INTO v_event_status_code
            FROM narrative.events ev
            JOIN narrative.event_statuses es ON es.event_status_id = ev.event_status_id
            WHERE ev.event_id = OLD.entity_id;

            IF v_event_status_code IS NULL OR v_event_status_code = 'draft' THEN
                RETURN NEW;
            END IF;

            IF NEW.canonical_name IS DISTINCT FROM OLD.canonical_name
               OR NEW.summary IS DISTINCT FROM OLD.summary
               OR NEW.canon_status_id IS DISTINCT FROM OLD.canon_status_id
               OR NEW.source_id IS DISTINCT FROM OLD.source_id
               OR NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
            THEN
                RAISE EXCEPTION
                    'Entity % is a recorded event (status %) and its identity/content '
                    'columns are immutable; lifecycle_status_id/archived_at may still '
                    'change (archival is independent of content immutability)',
                    OLD.entity_id, v_event_status_code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_recorded_event_entity_immutable() IS
        'For an entity whose entity_type is event and whose narrative.events row is '
        'no longer draft, freezes canonical_name/summary/canon_status_id/source_id/'
        'created_by_user_id. No-op for every other entity, and for an event still in '
        'draft. entity_type_id is separately protected by core.enforce_entity_type_'
        'change() (revision 048) as long as the narrative.events row exists.';
    """)
    op.execute("""
        CREATE TRIGGER tr_entities_enforce_recorded_event_immutable
        BEFORE UPDATE ON core.entities
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_recorded_event_entity_immutable();
    """)

    # ==========================================================================
    # 3. Append-only satellite tables, once the event is recorded
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_recorded_event_child_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_event_id     UUID := OLD.event_id;
            v_status_code  TEXT;
        BEGIN
            SELECT code INTO v_status_code
            FROM narrative.events ev
            JOIN narrative.event_statuses es ON es.event_status_id = ev.event_status_id
            WHERE ev.event_id = v_event_id;

            IF v_status_code IS DISTINCT FROM 'draft' THEN
                RAISE EXCEPTION
                    '%.% row(s) for event % are append-only once the event leaves draft '
                    '(status %) — the attempted % is rejected; corrections create a new '
                    'record',
                    TG_TABLE_SCHEMA, TG_TABLE_NAME, v_event_id, v_status_code, TG_OP
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_recorded_event_child_immutable() IS
        'Shared BEFORE UPDATE OR DELETE guard for narrative.event_participants/'
        '_locations/_causes/_observations: blocks both once the owning event (via '
        'this row''s own event_id) is no longer draft. Not attached to event_effects, '
        'which has its own mutable application_status lifecycle by design.';
    """)
    for table in CHILD_TABLES:
        op.execute(f"""
            CREATE TRIGGER tr_{table}_enforce_recorded_immutable
            BEFORE UPDATE OR DELETE ON narrative.{table}
            FOR EACH ROW EXECUTE FUNCTION narrative.enforce_recorded_event_child_immutable();
        """)


def downgrade() -> None:
    """Revert the migration."""

    for table in reversed(CHILD_TABLES):
        op.execute(
            f"DROP TRIGGER IF EXISTS tr_{table}_enforce_recorded_immutable ON narrative.{table};"
        )
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_recorded_event_child_immutable();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_entities_enforce_recorded_event_immutable ON core.entities;"
    )
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_recorded_event_entity_immutable();")

    op.execute("DROP TRIGGER IF EXISTS tr_events_enforce_recorded_immutable ON narrative.events;")
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_recorded_event_immutable();")
