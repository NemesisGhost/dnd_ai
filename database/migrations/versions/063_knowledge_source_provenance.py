"""Real provenance for knowledge.entity_knowledge/.party_discoveries

Revision ID: 063_knowledge_source_provenance
Revises: 062_event_cause_interaction
Create Date: 2026-08-05 18:00:00.000000

Purpose:
    Closes the Phase 6 first-time obligation docs/PLAN.md states explicitly:
    "Close Phase 5's interaction/event placeholders.
    knowledge.entity_knowledge.learned_source and
    knowledge.party_discoveries.discovery_method are free-text placeholders
    (revision 041) for 'how this was learned/discovered' — replace with real
    references to interaction.interactions/narrative.events once both
    exist." Both now exist (revisions 057, 061).

    Both TEXT placeholders are dropped, not kept alongside their
    replacements — the docs call for replacement, and a stale free-text
    guess next to a real reference would be a second, disagreeing source of
    truth. Each becomes two nullable FK columns (interaction, event), with
    at most one set — zero is legitimate for knowledge with no recorded
    interaction/event source (seeded starting knowledge, an administrative
    grant), the same "explicit administrative source" carve-out rule 6
    already allows for state changes.

Forward migration:
    - knowledge.entity_knowledge: DROP learned_source; ADD
      learned_via_interaction_id, learned_via_event_id (both nullable FKs,
      at-most-one CHECK); knowledge.enforce_entity_knowledge_source_world()
    - knowledge.party_discoveries: DROP discovery_method; ADD
      discovered_via_interaction_id, discovered_via_event_id (same shape);
      knowledge.enforce_party_discovery_source_world()

Rollback:
    Supported. Drops the new columns/triggers/functions and restores
    learned_source/discovery_method as nullable TEXT columns (empty — any
    interaction/event-sourced row created after this revision has no
    free-text equivalent to backfill into them).

Data implications:
    No existing entity_knowledge/party_discoveries rows reference the
    dropped columns outside test fixtures (revision 041 shipped with no
    production data).

Locking considerations:
    ALTER TABLE ADD/DROP COLUMN on two small, currently-empty tables. Brief
    metadata-only locks; no table rewrite for the ADDs (no default), and
    DROP COLUMN in PostgreSQL never rewrites the table either.

See: docs/PLAN.md Phase 6 (first-time obligations)
     docs/architecture/DATABASE_MODEL.md §15 (knowledge model), §27
     (Phase 6 reconciliation notes)
     database/migrations/versions/041_knowledge_domain.py (the original
     placeholders)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "063_knowledge_source_provenance"
down_revision = "062_event_cause_interaction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. knowledge.entity_knowledge
    # ==========================================================================
    op.execute("ALTER TABLE knowledge.entity_knowledge DROP COLUMN learned_source;")
    op.execute("""
        ALTER TABLE knowledge.entity_knowledge
        ADD COLUMN learned_via_interaction_id UUID
            REFERENCES interaction.interactions(interaction_id) ON DELETE SET NULL,
        ADD COLUMN learned_via_event_id UUID
            REFERENCES narrative.events(event_id) ON DELETE SET NULL,
        ADD CONSTRAINT ck_entity_knowledge_at_most_one_source CHECK (
            num_nonnulls(learned_via_interaction_id, learned_via_event_id) <= 1
        );
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.entity_knowledge.learned_via_interaction_id IS
        'The interaction through which this knower learned this, when recorded. '
        'At most one of learned_via_interaction_id/learned_via_event_id is set; '
        'both NULL means an unrecorded or administrative source (e.g. seeded '
        'starting knowledge). Closes the free-text learned_source placeholder '
        '(revision 041).';
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.entity_knowledge.learned_via_event_id IS
        'The event through which this knower learned this (e.g. witnessing it '
        'directly), when recorded. See learned_via_interaction_id.';
    """)
    op.execute(
        "CREATE INDEX ix_entity_knowledge_learned_via_interaction_id "
        "ON knowledge.entity_knowledge (learned_via_interaction_id) "
        "WHERE learned_via_interaction_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_entity_knowledge_learned_via_event_id "
        "ON knowledge.entity_knowledge (learned_via_event_id) "
        "WHERE learned_via_event_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_entity_knowledge_source_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_interaction_timeline  UUID;
            v_event_timeline        UUID;
        BEGIN
            IF NEW.learned_via_interaction_id IS NOT NULL THEN
                SELECT timeline_id INTO v_interaction_timeline
                FROM interaction.interactions WHERE interaction_id = NEW.learned_via_interaction_id;

                IF v_interaction_timeline IS DISTINCT FROM NEW.timeline_id THEN
                    RAISE EXCEPTION
                        'Entity knowledge % learned_via_interaction_id % belongs to timeline %, '
                        'but the knowledge row belongs to timeline %',
                        NEW.entity_knowledge_id, NEW.learned_via_interaction_id,
                        v_interaction_timeline, NEW.timeline_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.learned_via_event_id IS NOT NULL THEN
                SELECT timeline_id INTO v_event_timeline
                FROM narrative.events WHERE event_id = NEW.learned_via_event_id;

                IF v_event_timeline IS DISTINCT FROM NEW.timeline_id THEN
                    RAISE EXCEPTION
                        'Entity knowledge % learned_via_event_id % belongs to timeline %, but '
                        'the knowledge row belongs to timeline %',
                        NEW.entity_knowledge_id, NEW.learned_via_event_id, v_event_timeline,
                        NEW.timeline_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_entity_knowledge_source_world() IS
        'Guards knowledge.entity_knowledge: learned_via_interaction_id/'
        'learned_via_event_id (when set) must belong to the same timeline as '
        'the knowledge row (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_entity_knowledge_enforce_source_world
        BEFORE INSERT OR UPDATE ON knowledge.entity_knowledge
        FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_entity_knowledge_source_world();
    """)

    # ==========================================================================
    # 2. knowledge.party_discoveries
    # ==========================================================================
    op.execute("ALTER TABLE knowledge.party_discoveries DROP COLUMN discovery_method;")
    op.execute("""
        ALTER TABLE knowledge.party_discoveries
        ADD COLUMN discovered_via_interaction_id UUID
            REFERENCES interaction.interactions(interaction_id) ON DELETE SET NULL,
        ADD COLUMN discovered_via_event_id UUID
            REFERENCES narrative.events(event_id) ON DELETE SET NULL,
        ADD CONSTRAINT ck_party_discoveries_at_most_one_source CHECK (
            num_nonnulls(discovered_via_interaction_id, discovered_via_event_id) <= 1
        );
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.party_discoveries.discovered_via_interaction_id IS
        'The interaction through which this was discovered (a search check, a '
        'conversation), when recorded. At most one of '
        'discovered_via_interaction_id/discovered_via_event_id is set; both NULL '
        'means an unrecorded or administrative source. Closes the free-text '
        'discovery_method placeholder (revision 041).';
    """)
    op.execute("""
        COMMENT ON COLUMN knowledge.party_discoveries.discovered_via_event_id IS
        'The event through which this was discovered, when recorded. See '
        'discovered_via_interaction_id.';
    """)
    op.execute(
        "CREATE INDEX ix_party_discoveries_discovered_via_interaction_id "
        "ON knowledge.party_discoveries (discovered_via_interaction_id) "
        "WHERE discovered_via_interaction_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_party_discoveries_discovered_via_event_id "
        "ON knowledge.party_discoveries (discovered_via_event_id) "
        "WHERE discovered_via_event_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_party_discovery_source_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_interaction_timeline  UUID;
            v_event_timeline        UUID;
        BEGIN
            IF NEW.discovered_via_interaction_id IS NOT NULL THEN
                SELECT timeline_id INTO v_interaction_timeline
                FROM interaction.interactions
                WHERE interaction_id = NEW.discovered_via_interaction_id;

                IF v_interaction_timeline IS DISTINCT FROM NEW.timeline_id THEN
                    RAISE EXCEPTION
                        'Party discovery % discovered_via_interaction_id % belongs to timeline '
                        '%, but the discovery belongs to timeline %',
                        NEW.party_discovery_id, NEW.discovered_via_interaction_id,
                        v_interaction_timeline, NEW.timeline_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.discovered_via_event_id IS NOT NULL THEN
                SELECT timeline_id INTO v_event_timeline
                FROM narrative.events WHERE event_id = NEW.discovered_via_event_id;

                IF v_event_timeline IS DISTINCT FROM NEW.timeline_id THEN
                    RAISE EXCEPTION
                        'Party discovery % discovered_via_event_id % belongs to timeline %, '
                        'but the discovery belongs to timeline %',
                        NEW.party_discovery_id, NEW.discovered_via_event_id, v_event_timeline,
                        NEW.timeline_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_party_discovery_source_world() IS
        'Guards knowledge.party_discoveries: discovered_via_interaction_id/'
        'discovered_via_event_id (when set) must belong to the same timeline as '
        'the discovery (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_party_discoveries_enforce_source_world
        BEFORE INSERT OR UPDATE ON knowledge.party_discoveries
        FOR EACH ROW EXECUTE FUNCTION knowledge.enforce_party_discovery_source_world();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "DROP TRIGGER IF EXISTS tr_party_discoveries_enforce_source_world "
        "ON knowledge.party_discoveries;"
    )
    op.execute("DROP FUNCTION IF EXISTS knowledge.enforce_party_discovery_source_world();")
    op.execute(
        "ALTER TABLE knowledge.party_discoveries "
        "DROP COLUMN IF EXISTS discovered_via_interaction_id, "
        "DROP COLUMN IF EXISTS discovered_via_event_id;"
    )
    op.execute("ALTER TABLE knowledge.party_discoveries ADD COLUMN discovery_method TEXT;")
    op.execute("""
        COMMENT ON COLUMN knowledge.party_discoveries.discovery_method IS
        'Free-text placeholder for how this was discovered until interaction/event '
        'records exist (Phase 6) to reference instead.';
    """)

    op.execute(
        "DROP TRIGGER IF EXISTS tr_entity_knowledge_enforce_source_world "
        "ON knowledge.entity_knowledge;"
    )
    op.execute("DROP FUNCTION IF EXISTS knowledge.enforce_entity_knowledge_source_world();")
    op.execute(
        "ALTER TABLE knowledge.entity_knowledge "
        "DROP COLUMN IF EXISTS learned_via_interaction_id, "
        "DROP COLUMN IF EXISTS learned_via_event_id;"
    )
    op.execute("ALTER TABLE knowledge.entity_knowledge ADD COLUMN learned_source TEXT;")
    op.execute("""
        COMMENT ON COLUMN knowledge.entity_knowledge.learned_source IS
        'Free-text placeholder for how this was learned until interaction/event '
        'records exist (Phase 6) to reference instead.';
    """)
