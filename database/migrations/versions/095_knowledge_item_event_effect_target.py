"""narrative.event_effects gains target_knowledge_item_id.

Revision ID: 095_knowledge_event_target
Revises: 094_reference_corpus
Create Date: 2026-08-20 14:00:00.000000

Purpose:
    Phase 12's NPC-portrayal use case needs a standalone, reusable "reveal
    this knowledge item to this party" command
    (dnd_ai.commands.knowledge.reveal_knowledge_to_party, this migration's
    only consumer) an approved ai.proposed_changes row can invoke. Unlike
    interactions.py's existing _maybe_discover_target() — which records a
    *structural* discovery (a hidden dungeon feature/connection/hazard/
    interactable becoming known to exist, via one of event_effects' already-
    present target_area_* columns) — this command's own effect is a change
    to campaign.party_knowledge, the party's current effective belief about
    a knowledge item (docs/architecture/DATABASE_MODEL.md §15). No existing
    target_* column on narrative.event_effects can represent that: the
    closest, target_entity_id, is wrong here specifically because
    knowledge.knowledge_items IS ITSELF core-entities-rooted (class-table
    inheritance, CLAUDE.md rule 4) — reusing target_entity_id would make the
    effect row structurally indistinguishable from one whose subject is an
    ordinary entity (an NPC, an item), which
    dnd_ai.commands.quests/.relationships already avoided by giving
    quest_objective/relationship their own typed target columns
    (target_quest_objective_id revision 073, target_relationship_id
    revision 076) despite quest objectives and relationships not being
    entities either.

Forward migration:
    - narrative.event_effects.target_knowledge_item_id (FK
      knowledge.knowledge_items, ON DELETE SET NULL — matching every
      sibling target_* column's own delete behavior)
    - Extends ck_event_effects_at_most_one_target to include it
    - ix_event_effects_target_knowledge_item_id (partial, matching every
      sibling target_* column's own index shape)

Rollback:
    Supported. Reverts the CHECK to its pre-existing 7-column form and
    drops the column.

Data implications:
    None. No existing narrative.event_effects row references the new
    column.

Locking considerations:
    ADD COLUMN (nullable, no default) is metadata-only on PostgreSQL 11+.
    Dropping and recreating ck_event_effects_at_most_one_target revalidates
    against every existing row, but the new column contributes nothing to
    evaluate (always NULL until this migration's companion command runs
    for the first time) — the same low-cost revalidation
    094_reference_corpus's security.resource_grants ALTER already reasoned
    through for its own extended CHECK. narrative.event_effects can be a
    large, high-volume table (every state-changing command inserts a row
    here), so this was checked deliberately rather than assumed.

See: database/migrations/versions/073_quest_and_knowledge_domain.py
     (target_quest_objective_id — the precedent this migration mirrors)
     database/migrations/versions/076_relationships_and_orgs.py
     (target_relationship_id — same pattern, most recent prior addition)
     src/dnd_ai/commands/knowledge.py (this column's only writer)
     docs/architecture/DATABASE_MODEL.md §15 (knowledge model)
"""

from alembic import op

# revision identifiers, used by Alembic. Kept to 32 characters or fewer:
# core.alembic_version.version_num is VARCHAR(32), and a longer id fails
# only at the very end of the migration, after all DDL has already run.
revision = "095_knowledge_event_target"
down_revision = "094_reference_corpus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        ALTER TABLE narrative.event_effects
        ADD COLUMN target_knowledge_item_id UUID
            REFERENCES knowledge.knowledge_items(knowledge_item_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN narrative.event_effects.target_knowledge_item_id IS
        'The knowledge.knowledge_items row whose campaign.party_knowledge '
        'state changed, when this effect is that kind of change '
        '(dnd_ai.commands.knowledge.reveal_knowledge_to_party) — distinct '
        'from target_entity_id, since a knowledge item is itself core-'
        'entities-rooted (CLAUDE.md rule 4) and reusing target_entity_id '
        'would make this effect indistinguishable from one about the entity '
        'the fact concerns rather than the fact itself.';
    """)

    op.execute("""
        ALTER TABLE narrative.event_effects
        DROP CONSTRAINT ck_event_effects_at_most_one_target;
    """)
    op.execute("""
        ALTER TABLE narrative.event_effects
        ADD CONSTRAINT ck_event_effects_at_most_one_target CHECK (
            num_nonnulls(
                target_entity_id, target_area_connection_id, target_area_feature_id,
                target_area_hazard_id, target_area_interactable_id, target_quest_objective_id,
                target_relationship_id, target_knowledge_item_id
            ) <= 1
        );
    """)

    op.execute(
        "CREATE INDEX ix_event_effects_target_knowledge_item_id "
        "ON narrative.event_effects (target_knowledge_item_id) "
        "WHERE target_knowledge_item_id IS NOT NULL;"
    )


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP INDEX IF EXISTS narrative.ix_event_effects_target_knowledge_item_id;")

    op.execute("""
        ALTER TABLE narrative.event_effects
        DROP CONSTRAINT IF EXISTS ck_event_effects_at_most_one_target;
    """)
    op.execute("""
        ALTER TABLE narrative.event_effects
        ADD CONSTRAINT ck_event_effects_at_most_one_target CHECK (
            num_nonnulls(
                target_entity_id, target_area_connection_id, target_area_feature_id,
                target_area_hazard_id, target_area_interactable_id, target_quest_objective_id,
                target_relationship_id
            ) <= 1
        );
    """)

    op.execute(
        "ALTER TABLE narrative.event_effects DROP COLUMN IF EXISTS target_knowledge_item_id;"
    )
