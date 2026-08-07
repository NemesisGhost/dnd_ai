"""narrative.event_causes.cause_interaction_id: close the interaction placeholder

Revision ID: 062_event_cause_interaction
Revises: 061_interaction_domain
Create Date: 2026-08-05 17:00:00.000000

Purpose:
    Revision 057's docstring recorded a deliberate scoping decision:
    narrative.event_causes.cause_description is "a free-text placeholder for
    interaction/decision/condition causes until interaction.interactions
    exists ... a real cause_interaction_id FK arrives once
    interaction.interactions exists (Phase 6 increment 2), not invented ahead
    of that table." interaction.interactions now exists (revision 061), so
    this revision closes that placeholder.

    cause_description remains — it still covers "decisions or conditions"
    that are neither a prior event nor a recorded interaction (a GM ruling,
    an ambient world condition). The three columns become mutually exclusive
    rather than cause_event_id/cause_description's previous either-or pair.

Forward migration:
    - narrative.event_causes.cause_interaction_id UUID REFERENCES
      interaction.interactions(interaction_id) ON DELETE SET NULL
    - ck_event_causes_has_cause replaced: exactly one of cause_event_id,
      cause_interaction_id, cause_description must be set (was: at least one
      of cause_event_id/cause_description)
    - narrative.enforce_event_cause_interaction_world(): the interaction, when
      set, must belong to the same timeline as the caused event

Rollback:
    Supported. Drops the new trigger/function/column and restores the
    original ck_event_causes_has_cause CHECK. Any row that came to rely on
    cause_interaction_id alone (both other columns NULL) would violate the
    restored CHECK — acceptable here since revision 057 shipped in this same
    development sequence with no event_causes rows in any deployed
    environment yet.

Data implications:
    No existing rows depend on the new column (revision 057 is unreleased
    outside this branch).

Locking considerations:
    ALTER TABLE ADD COLUMN with no default takes a brief metadata-only lock;
    no table rewrite. The table is new and empty.

See: database/migrations/versions/057_narrative_events.py (the original
     placeholder and its docstring)
     docs/architecture/DATABASE_MODEL.md §12 (events and effects), §27
     (Phase 6 reconciliation notes)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "062_event_cause_interaction"
down_revision = "061_interaction_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        ALTER TABLE narrative.event_causes
        ADD COLUMN cause_interaction_id UUID
            REFERENCES interaction.interactions(interaction_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.event_causes.cause_interaction_id IS
        'The interaction that caused this event, when it was a recorded '
        'interaction rather than a prior event or an undocumented decision/'
        'condition. Closes the placeholder revision 057''s docstring recorded.';
    """)
    op.execute(
        "CREATE INDEX ix_event_causes_cause_interaction_id "
        "ON narrative.event_causes (cause_interaction_id) "
        "WHERE cause_interaction_id IS NOT NULL;"
    )
    op.execute("""
        COMMENT ON COLUMN narrative.event_causes.cause_description IS
        'Free-text placeholder for undocumented decisions or conditions — '
        'causes that are neither a prior event (cause_event_id) nor a '
        'recorded interaction (cause_interaction_id), e.g. a GM ruling or '
        'an ambient world condition.';
    """)
    op.execute("""
        COMMENT ON TABLE narrative.event_causes IS
        'Links an event to a prior event, a recorded interaction, or a '
        'free-text decision/condition, that caused it (docs/DOMAIN_MODEL.md '
        '§13.4). Exactly one of the three is set. Append-only.';
    """)

    op.execute("ALTER TABLE narrative.event_causes DROP CONSTRAINT ck_event_causes_has_cause;")
    op.execute("""
        ALTER TABLE narrative.event_causes
        ADD CONSTRAINT ck_event_causes_has_cause CHECK (
            num_nonnulls(cause_event_id, cause_interaction_id, cause_description) = 1
        );
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION narrative.enforce_event_cause_interaction_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_event_timeline        UUID;
            v_interaction_timeline  UUID;
        BEGIN
            IF NEW.cause_interaction_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT timeline_id INTO v_event_timeline
            FROM narrative.events WHERE event_id = NEW.event_id;

            SELECT timeline_id INTO v_interaction_timeline
            FROM interaction.interactions WHERE interaction_id = NEW.cause_interaction_id;

            IF v_interaction_timeline IS DISTINCT FROM v_event_timeline THEN
                RAISE EXCEPTION
                    'Event cause %''s interaction % belongs to timeline %, but event % '
                    'belongs to timeline %',
                    NEW.event_cause_id, NEW.cause_interaction_id, v_interaction_timeline,
                    NEW.event_id, v_event_timeline
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION narrative.enforce_event_cause_interaction_world() IS
        'Guards narrative.event_causes: cause_interaction_id, when set, must '
        'belong to the same timeline as the event it caused (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_event_causes_enforce_interaction_world
        BEFORE INSERT OR UPDATE ON narrative.event_causes
        FOR EACH ROW EXECUTE FUNCTION narrative.enforce_event_cause_interaction_world();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "DROP TRIGGER IF EXISTS tr_event_causes_enforce_interaction_world "
        "ON narrative.event_causes;"
    )
    op.execute("DROP FUNCTION IF EXISTS narrative.enforce_event_cause_interaction_world();")

    op.execute("ALTER TABLE narrative.event_causes DROP CONSTRAINT ck_event_causes_has_cause;")
    op.execute("""
        ALTER TABLE narrative.event_causes
        ADD CONSTRAINT ck_event_causes_has_cause
            CHECK (cause_event_id IS NOT NULL OR cause_description IS NOT NULL);
    """)

    op.execute("ALTER TABLE narrative.event_causes DROP COLUMN IF EXISTS cause_interaction_id;")

    op.execute("""
        COMMENT ON COLUMN narrative.event_causes.cause_description IS
        'Free-text placeholder for interaction/decision/condition causes '
        'until interaction.interactions exists (Phase 6 increment 2) to '
        'reference instead — same pattern as '
        'knowledge.entity_knowledge.learned_source (revision 041).';
    """)
    op.execute("""
        COMMENT ON TABLE narrative.event_causes IS
        'Links an event to a prior event, or a free-text decision/condition, '
        'that caused it (docs/DOMAIN_MODEL.md §13.4). Append-only.';
    """)
