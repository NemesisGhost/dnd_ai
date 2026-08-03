"""Validate knowledge-domain event timestamps belong to the right world

Revision ID: 045_knowledge_timestamp_world
Revises: 044_dungeon_mutation_safety
Create Date: 2026-08-03 09:30:00.000000

Purpose:
    Phase 5 exit review finding: revision 041's world-agreement triggers for
    knowledge.entity_knowledge and knowledge.party_discoveries validated
    timeline/knowledge-item/recipient agreement but never checked
    learned_at_world_time_id or discovered_at_world_time_id — both nullable
    core.world_times references that could silently point at a world time
    from a different world entirely.

    Fixed by extending (CREATE OR REPLACE) the two existing trigger
    functions rather than adding new ones, since the world-time check
    belongs in the same one-function-owns-the-whole-contract shape revision
    041 already established (and revision 009's
    sync_party_membership_period() also uses) — a second trigger doing an
    overlapping check would just be two places to keep in sync. Revision 041
    itself is not modified; this is a forward-only CREATE OR REPLACE
    layered on top, the same technique revision 035 used to replace
    rules.ruleset_allowed_for_world().

    Both functions already run BEFORE INSERT OR UPDATE (revision 041), so
    extending their bodies automatically covers updates without touching
    the trigger attachments.

    core.world_times.world_id and .sort_key are immutable as of revision
    030, so a world time referenced by an existing, already-valid knowledge
    row cannot later be moved to a different world out from under it —
    tests prove this holds for both new checks.

Forward migration:
    - knowledge.enforce_entity_knowledge_world(): now also rejects a
      learned_at_world_time_id from a different world than the row's own
      timeline/knowledge-item world
    - knowledge.enforce_party_discovery_world(): now also rejects a
      discovered_at_world_time_id from a different world than the row's own
      timeline/knowledge-item world

Rollback:
    Supported. Restores each function to its revision-041 body exactly.

Data implications:
    None. No rows exist yet in either table.

Locking considerations:
    CREATE OR REPLACE FUNCTION does not lock the tables the trigger is
    attached to.

See: docs/DATABASE_CONVENTIONS.md §9.5 (same-world consistency)
     database/migrations/versions/041_knowledge_domain.py (the functions
     extended here)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "045_knowledge_timestamp_world"
down_revision = "044_dungeon_mutation_safety"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. knowledge.entity_knowledge.learned_at_world_time_id
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_entity_knowledge_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world     UUID;
            v_item_world         UUID;
            v_knower_world       UUID;
            v_learned_at_world   UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_item_world
            FROM core.entities WHERE entity_id = NEW.knowledge_item_id;

            SELECT world_id INTO v_knower_world
            FROM core.entities WHERE entity_id = NEW.knower_entity_id;

            IF v_item_world IS DISTINCT FROM v_timeline_world
               OR v_knower_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Entity knowledge row mixes worlds: timeline % (world %), '
                    'knowledge item % (world %), knower % (world %)',
                    NEW.timeline_id, v_timeline_world, NEW.knowledge_item_id, v_item_world,
                    NEW.knower_entity_id, v_knower_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.learned_at_world_time_id IS NOT NULL THEN
                SELECT world_id INTO v_learned_at_world
                FROM core.world_times WHERE world_time_id = NEW.learned_at_world_time_id;

                IF v_learned_at_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Entity knowledge row mixes worlds: timeline % (world %), '
                        'learned_at_world_time_id % (world %)',
                        NEW.timeline_id, v_timeline_world, NEW.learned_at_world_time_id,
                        v_learned_at_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_entity_knowledge_world() IS
        'World-agreement guard for knowledge.entity_knowledge: timeline, knowledge '
        'item, knower, and (when set) learned_at_world_time_id must all belong to the '
        'same world.';
    """)

    # ==========================================================================
    # 2. knowledge.party_discoveries.discovered_at_world_time_id
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_party_discovery_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world      UUID;
            v_item_world          UUID;
            v_recipient_world     UUID;
            v_discovered_at_world UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_item_world
            FROM core.entities WHERE entity_id = NEW.knowledge_item_id;

            IF NEW.party_id IS NULL AND NEW.knower_entity_id IS NULL THEN
                -- Malformed (no recipient at all) — let
                -- ck_party_discoveries_exactly_one_recipient reject it with a
                -- clearer error instead of this trigger reporting a spurious
                -- "recipient world NULL" mismatch.
                RETURN NEW;
            END IF;

            IF NEW.party_id IS NOT NULL THEN
                SELECT world_id INTO v_recipient_world
                FROM campaign.parties WHERE party_id = NEW.party_id;
            ELSE
                SELECT world_id INTO v_recipient_world
                FROM core.entities WHERE entity_id = NEW.knower_entity_id;
            END IF;

            IF v_item_world IS DISTINCT FROM v_timeline_world
               OR v_recipient_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Party discovery mixes worlds: timeline % (world %), knowledge item % '
                    '(world %), recipient world %',
                    NEW.timeline_id, v_timeline_world, NEW.knowledge_item_id, v_item_world,
                    v_recipient_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.discovered_at_world_time_id IS NOT NULL THEN
                SELECT world_id INTO v_discovered_at_world
                FROM core.world_times WHERE world_time_id = NEW.discovered_at_world_time_id;

                IF v_discovered_at_world IS DISTINCT FROM v_timeline_world THEN
                    RAISE EXCEPTION
                        'Party discovery mixes worlds: timeline % (world %), '
                        'discovered_at_world_time_id % (world %)',
                        NEW.timeline_id, v_timeline_world, NEW.discovered_at_world_time_id,
                        v_discovered_at_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_party_discovery_world() IS
        'World-agreement guard for knowledge.party_discoveries: timeline, knowledge '
        'item, recipient (party or knower entity), and (when set) '
        'discovered_at_world_time_id must all belong to the same world.';
    """)


def downgrade() -> None:
    """Revert the migration — restores each function to its revision-041 body."""

    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_entity_knowledge_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world  UUID;
            v_item_world      UUID;
            v_knower_world    UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_item_world
            FROM core.entities WHERE entity_id = NEW.knowledge_item_id;

            SELECT world_id INTO v_knower_world
            FROM core.entities WHERE entity_id = NEW.knower_entity_id;

            IF v_item_world IS DISTINCT FROM v_timeline_world
               OR v_knower_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Entity knowledge row mixes worlds: timeline % (world %), '
                    'knowledge item % (world %), knower % (world %)',
                    NEW.timeline_id, v_timeline_world, NEW.knowledge_item_id, v_item_world,
                    NEW.knower_entity_id, v_knower_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_entity_knowledge_world() IS
        'World-agreement guard for knowledge.entity_knowledge: timeline, knowledge '
        'item, and knower must all belong to the same world.';
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION knowledge.enforce_party_discovery_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world    UUID;
            v_item_world        UUID;
            v_recipient_world   UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_item_world
            FROM core.entities WHERE entity_id = NEW.knowledge_item_id;

            IF NEW.party_id IS NULL AND NEW.knower_entity_id IS NULL THEN
                RETURN NEW;
            END IF;

            IF NEW.party_id IS NOT NULL THEN
                SELECT world_id INTO v_recipient_world
                FROM campaign.parties WHERE party_id = NEW.party_id;
            ELSE
                SELECT world_id INTO v_recipient_world
                FROM core.entities WHERE entity_id = NEW.knower_entity_id;
            END IF;

            IF v_item_world IS DISTINCT FROM v_timeline_world
               OR v_recipient_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Party discovery mixes worlds: timeline % (world %), knowledge item % '
                    '(world %), recipient world %',
                    NEW.timeline_id, v_timeline_world, NEW.knowledge_item_id, v_item_world,
                    v_recipient_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION knowledge.enforce_party_discovery_world() IS
        'World-agreement guard for knowledge.party_discoveries: timeline, knowledge '
        'item, and recipient (party or knower entity) must all belong to the same world.';
    """)
