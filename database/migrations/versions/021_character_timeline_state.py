"""Character timeline state: combat state, conditions, resources

Revision ID: 021_character_timeline_state
Revises: 020_character_builds
Create Date: 2026-08-02 17:00:00.000000

Purpose:
    Delivers the three timeline-state tables docs/PLAN.md §7.3 names as
    Phase 4 deliverables: campaign.character_state, .character_conditions,
    .character_resources. This is mutable per-timeline current state, kept
    separate from the character's build (revision 020) exactly as
    DATABASE_MODEL.md §7.4 requires: "Current hit points, conditions,
    spell-slot use and other temporary resources belong to campaign timeline
    state," not the build.

    docs/architecture/DATABASE_MODEL.md §17's general typed-state shape calls
    for effective_from_event_id/effective_to_event_id on every such table,
    but narrative.events does not exist until Phase 6 — the same situation
    Phase 3 faced with campaign.timelines.branch_event_id. Rather than defer
    these three tables entirely (Phase 4's own exit criteria require them),
    each is built as a single mutable current row per (timeline, character)
    pair, enforced by its primary key. Phase 6 is expected to add event
    linkage for historical reconstruction; it does not need to change these
    tables' shape to do it, since rule 6 (state changes need a causal event,
    committing atomically) is a transaction-boundary guarantee the command
    layer provides, not a column these tables are missing.

    campaign.character_location_history and campaign.character_inventory are
    NOT here — both were already explicitly deferred in PLAN.md §7.3 (to
    Phase 5 and Phase 9 respectively), since neither has anything to
    reference yet.

Forward migration:
    - campaign.character_state
    - campaign.character_conditions
    - campaign.character_resources
    - campaign.enforce_character_state_world(), a single shared trigger
      function attached to all three (they share the same
      timeline_id/character_id world-agreement rule)

Rollback:
    Supported. Drops all three tables and the shared trigger function.

Data implications:
    Creates no rows.

Locking considerations:
    None. All tables are new and empty.

See: docs/PLAN.md §7.3 (timeline state)
     docs/architecture/DATABASE_MODEL.md §17 (typed timeline state)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "021_character_timeline_state"
down_revision = "020_character_builds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. Shared world-agreement trigger
    # ==========================================================================
    # All three tables below share the same (timeline_id, character_id)
    # column pair and the same rule: the character must belong to the
    # timeline's world. One shared function, attached three times, rather
    # than three near-identical copies — the same reasoning as
    # core.set_updated_at().
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_character_state_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world UUID;
            v_character_world UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_character_world
            FROM core.entities WHERE entity_id = NEW.character_id;

            IF v_character_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Character % belongs to world %, but timeline % belongs to world %',
                    NEW.character_id, v_character_world, NEW.timeline_id, v_timeline_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_character_state_world() IS
        'Shared world-agreement guard for the character timeline-state tables: the '
        'character must belong to the timeline''s world. Attach to any table with '
        '(timeline_id, character_id) columns following this shape.';
    """)

    # ==========================================================================
    # 2. campaign.character_state
    # ==========================================================================
    # One current row per (timeline, character) — the primary key is the
    # enforcement mechanism, in place of the partial-unique-index pattern
    # used where multiple historical rows coexist (there are none here yet;
    # see the module docstring on event linkage).
    op.execute("""
        CREATE TABLE campaign.character_state (
            timeline_id             UUID NOT NULL
                                    REFERENCES campaign.timelines(timeline_id)
                                    ON DELETE CASCADE,
            character_id            UUID NOT NULL
                                    REFERENCES character.characters(character_id)
                                    ON DELETE CASCADE,
            current_hit_points      INTEGER NOT NULL,
            maximum_hit_points      core.nonnegative_integer NOT NULL,
            temporary_hit_points    core.nonnegative_integer NOT NULL DEFAULT 0,
            exhaustion_level        core.nonnegative_integer NOT NULL DEFAULT 0,
            death_save_successes    core.nonnegative_integer NOT NULL DEFAULT 0,
            death_save_failures     core.nonnegative_integer NOT NULL DEFAULT 0,
            initiative              INTEGER,
            transformed_into_id     UUID
                                    REFERENCES character.characters(character_id)
                                    ON DELETE SET NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (timeline_id, character_id),
            CONSTRAINT ck_character_state_hp_nonnegative CHECK (current_hit_points >= 0),
            CONSTRAINT ck_character_state_death_saves CHECK (
                death_save_successes <= 3 AND death_save_failures <= 3
            ),
            CONSTRAINT ck_character_state_not_own_transformation
                CHECK (transformed_into_id IS DISTINCT FROM character_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.character_state IS
        'Current combat/vitals state for a character on a timeline: HP, exhaustion, '
        'death saves, initiative when in an encounter, and current transformed form. '
        'One row per (timeline, character) — see the module docstring on why there is '
        'no event-linked history yet.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_state.initiative IS
        'Set only while the character is in an encounter. NULL otherwise.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_state.transformed_into_id IS
        'The character sheet currently being used instead of this one''s own (a '
        'polymorph or similar transformation). NULL means no transformation is active.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_state_set_updated_at
        BEFORE UPDATE ON campaign.character_state
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_character_state_character_id ON campaign.character_state (character_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_state_transformed_into_id "
        "ON campaign.character_state (transformed_into_id) WHERE transformed_into_id IS NOT NULL;"
    )
    op.execute("""
        CREATE TRIGGER tr_character_state_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.character_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_character_state_world();
    """)

    # ==========================================================================
    # 3. campaign.character_conditions
    # ==========================================================================
    # A character has at most one active instance of a given condition per
    # timeline at a time — the primary key includes condition_id for that
    # reason. Stacking severity (e.g. multiple exhaustion sources) is
    # represented by exhaustion_level on character_state, not by multiple
    # condition rows.
    op.execute("""
        CREATE TABLE campaign.character_conditions (
            timeline_id          UUID NOT NULL
                                 REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            character_id         UUID NOT NULL
                                 REFERENCES character.characters(character_id) ON DELETE CASCADE,
            condition_id         UUID NOT NULL
                                 REFERENCES rules.conditions(condition_id) ON DELETE RESTRICT,
            source_description   TEXT,
            applied_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (timeline_id, character_id, condition_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.character_conditions IS
        'A condition currently active on a character in a timeline. '
        'source_description is free text for now — a causal event reference arrives '
        'in Phase 6.';
    """)
    op.execute(
        "CREATE INDEX ix_character_conditions_character_id "
        "ON campaign.character_conditions (character_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_conditions_condition_id "
        "ON campaign.character_conditions (condition_id);"
    )
    op.execute("""
        CREATE TRIGGER tr_character_conditions_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.character_conditions
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_character_state_world();
    """)

    # ==========================================================================
    # 4. campaign.character_resources
    # ==========================================================================
    op.execute("""
        CREATE TABLE campaign.character_resources (
            timeline_id             UUID NOT NULL
                                    REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            character_id            UUID NOT NULL
                                    REFERENCES character.characters(character_id)
                                    ON DELETE CASCADE,
            resource_definition_id  UUID NOT NULL
                                    REFERENCES rules.resource_definitions(resource_definition_id)
                                    ON DELETE RESTRICT,
            current_amount          core.nonnegative_integer NOT NULL,
            maximum_amount          core.nonnegative_integer NOT NULL,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (timeline_id, character_id, resource_definition_id),
            CONSTRAINT ck_character_resources_current_within_max
                CHECK (current_amount <= maximum_amount)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.character_resources IS
        'Current and maximum amount of a depletable/rechargeable resource (spell '
        'slots, ki points, rage uses, ...) a character has in a timeline.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_resources_set_updated_at
        BEFORE UPDATE ON campaign.character_resources
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_character_resources_character_id "
        "ON campaign.character_resources (character_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_resources_resource_definition_id "
        "ON campaign.character_resources (resource_definition_id);"
    )
    op.execute("""
        CREATE TRIGGER tr_character_resources_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.character_resources
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_character_state_world();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS campaign.character_resources;")
    op.execute("DROP TABLE IF EXISTS campaign.character_conditions;")
    op.execute("DROP TABLE IF EXISTS campaign.character_state;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_character_state_world();")
