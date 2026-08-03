"""Close Phase 4's character-location forward references

Revision ID: 042_close_phase4_location_refs
Revises: 041_knowledge_domain
Create Date: 2026-08-02 19:00:00.000000

Purpose:
    Closes the two character-location forward references Phase 4 explicitly
    deferred because world.locations did not exist yet (docs/PLAN.md §7.3;
    docs/architecture/DATABASE_MODEL.md §7.1, §17; Phase 5's own first-time
    obligation in docs/PLAN.md §23):

        character.characters.origin_location_id
        campaign.character_location_history

    character_location_history is the sole source of truth for both a
    character's location HISTORY and its CURRENT location: the row with
    departed_at_world_time_id IS NULL is the open/current one, enforced by a
    partial unique index (one open row per (timeline, character) — the same
    "NULL end = current" shape campaign.party_memberships already uses for
    membership, docs/architecture/DATABASE_MODEL.md §17's "current location"
    example is satisfied by querying this table's open row rather than by
    adding a current_location_id column to campaign.character_state
    (revision 021), which shipped before locations existed and needs no
    schema change to stay correct — the split between current-state and
    history the project already uses elsewhere (e.g. character_builds vs.
    campaign.character_state.character_build_id) applies here without
    touching the earlier table.

Forward migration:
    - character.characters.origin_location_id, with
      character.enforce_character_origin_location_world()
    - campaign.character_location_history, with a partial unique index
      enforcing one open (current) row per (timeline, character), and
      campaign.enforce_character_location_history_world()

Rollback:
    Supported. Drops the history table and both trigger functions, then the
    origin_location_id column.

Data implications:
    None. Adds a nullable column and an empty table.

Locking considerations:
    ALTER TABLE character.characters ADD COLUMN is a fast metadata-only
    change (nullable, no default requiring a rewrite) even once character
    rows exist.

See: docs/PLAN.md §23 (Phase 5 first-time obligations), §7.3 (deferred timeline state)
     docs/architecture/DATABASE_MODEL.md §7.1, §17
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "042_close_phase4_location_refs"
down_revision = "041_knowledge_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. character.characters.origin_location_id
    # ==========================================================================
    op.execute("""
        ALTER TABLE character.characters
        ADD COLUMN origin_location_id UUID
            REFERENCES world.locations(location_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN character.characters.origin_location_id IS
        'Where this character is from. Deferred from Phase 4 until world.locations '
        'existed (docs/architecture/DATABASE_MODEL.md §7.1). Must belong to the '
        'character''s own world, enforced by trigger.';
    """)
    op.execute(
        "CREATE INDEX ix_characters_origin_location_id "
        "ON character.characters (origin_location_id) WHERE origin_location_id IS NOT NULL;"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION character.enforce_character_origin_location_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_character_world  UUID;
            v_location_world   UUID;
        BEGIN
            IF NEW.origin_location_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT world_id INTO v_character_world
            FROM core.entities WHERE entity_id = NEW.character_id;

            SELECT world_id INTO v_location_world
            FROM core.entities WHERE entity_id = NEW.origin_location_id;

            IF v_character_world IS DISTINCT FROM v_location_world THEN
                RAISE EXCEPTION
                    'Character % belongs to world %, but origin location % belongs to world %',
                    NEW.character_id, v_character_world, NEW.origin_location_id, v_location_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION character.enforce_character_origin_location_world() IS
        'Guards character.characters.origin_location_id: must belong to the same '
        'world as the character (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_characters_enforce_origin_location_world
        BEFORE INSERT OR UPDATE ON character.characters
        FOR EACH ROW EXECUTE FUNCTION character.enforce_character_origin_location_world();
    """)

    # ==========================================================================
    # 2. campaign.character_location_history
    # ==========================================================================
    op.execute("""
        CREATE TABLE campaign.character_location_history (
            character_location_history_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id                     UUID NOT NULL
                                           REFERENCES campaign.timelines(timeline_id)
                                           ON DELETE CASCADE,
            character_id                     UUID NOT NULL
                                           REFERENCES character.characters(character_id)
                                           ON DELETE CASCADE,
            location_id                      UUID NOT NULL
                                           REFERENCES world.locations(location_id)
                                           ON DELETE CASCADE,
            arrived_at_world_time_id          UUID
                                           REFERENCES core.world_times(world_time_id)
                                           ON DELETE SET NULL,
            departed_at_world_time_id         UUID
                                           REFERENCES core.world_times(world_time_id)
                                           ON DELETE SET NULL,
            created_at                        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.character_location_history IS
        'Where a character has been on a timeline. The row with '
        'departed_at_world_time_id IS NULL is the character''s current location — at '
        'most one per (timeline, character), enforced by a partial unique index. '
        'Deferred from Phase 4 until world.locations existed '
        '(docs/architecture/DATABASE_MODEL.md §17).';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_location_history.departed_at_world_time_id IS
        'NULL means the character is still at this location — the single '
        'representation of "current location", same convention as '
        'campaign.party_memberships.effective_to_world_time_id.';
    """)
    op.execute(
        "CREATE INDEX ix_character_location_history_character_id "
        "ON campaign.character_location_history (character_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_location_history_location_id "
        "ON campaign.character_location_history (location_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_location_history_arrived_at_world_time_id "
        "ON campaign.character_location_history (arrived_at_world_time_id) "
        "WHERE arrived_at_world_time_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_character_location_history_departed_at_world_time_id "
        "ON campaign.character_location_history (departed_at_world_time_id) "
        "WHERE departed_at_world_time_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_character_location_history_one_open_per_character
        ON campaign.character_location_history (timeline_id, character_id)
        WHERE departed_at_world_time_id IS NULL;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_character_location_history_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world   UUID;
            v_character_world  UUID;
            v_location_world   UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_character_world
            FROM core.entities WHERE entity_id = NEW.character_id;

            SELECT world_id INTO v_location_world
            FROM core.entities WHERE entity_id = NEW.location_id;

            IF v_character_world IS DISTINCT FROM v_timeline_world
               OR v_location_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Character location history row mixes worlds: timeline % (world %), '
                    'character % (world %), location % (world %)',
                    NEW.timeline_id, v_timeline_world, NEW.character_id, v_character_world,
                    NEW.location_id, v_location_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_character_location_history_world() IS
        'World-agreement guard for campaign.character_location_history: timeline, '
        'character, and location must all belong to the same world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_location_history_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.character_location_history
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_character_location_history_world();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS campaign.character_location_history;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_character_location_history_world();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_characters_enforce_origin_location_world "
        "ON character.characters;"
    )
    op.execute("DROP FUNCTION IF EXISTS character.enforce_character_origin_location_world();")
    op.execute("ALTER TABLE character.characters DROP COLUMN IF EXISTS origin_location_id;")
