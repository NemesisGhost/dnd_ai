"""Character-state, proficiency, and rule-content-scope corrections

Revision ID: 029_character_corrections
Revises: 028_build_timeline_state
Create Date: 2026-08-02 21:00:00.000000

Purpose:
    Corrective revision (Phase 4 corrections review) closing five smaller
    gaps found in the Phase 4 character and rules schema:

    1. campaign.character_state.current_hit_points could exceed
       maximum_hit_points — nothing capped healing at maximum. Temporary hit
       points are already a separate column, so this cannot be confused with
       an intentional over-max buffer.
    2. campaign.character_state.transformed_into_id (revision 021) checked
       only that it was not the character's own id — not that the
       transformation target belonged to the same world as the character
       being transformed. A same-world guard closes that.
    3. rules.spells.code had no format CHECK, unlike every sibling
       ruleset-content table (ck_<table>_code_format).
    4. character.character_proficiencies required exactly one target column
       set (revision 020) but never checked that it was the *right* one for
       the row's proficiency_type_id, and allowed the same skill/ability/
       free-text target to be granted twice on one build.
    5. Rule content a character actually uses — its species, its builds'
       ruleset versions, and the conditions/resources applied to it on a
       timeline — was never checked against rules.world_rulesets, so a
       character could reference content from a ruleset its own world never
       allowed.

Forward migration:
    - ck_character_state_current_within_max
    - campaign.enforce_character_state_transformation_world()
    - ck_spells_code_format
    - rules.proficiency_types.target_kind, backfilled from existing codes
    - character.enforce_proficiency_target_kind()
    - partial unique indexes preventing duplicate proficiency targets per
      build
    - rules.ruleset_allowed_for_world(), a shared helper, plus:
      character.enforce_character_species_ruleset_allowed(),
      character.enforce_build_ruleset_allowed(),
      campaign.enforce_condition_ruleset_allowed(),
      campaign.enforce_resource_ruleset_allowed()

Rollback:
    Supported. Drops every object added here, in dependency order.

Data implications:
    Backfills rules.proficiency_types.target_kind for the five seeded rows
    (revision 022): weapon/armor/tool -> free_text, skill -> skill,
    saving_throw -> saving_throw. No character_state, character_proficiencies,
    character_builds, character_conditions, or character_resources rows
    exist outside test fixtures to re-validate.

Locking considerations:
    Every touched table is empty or near-empty in practice; none of these
    changes require a table rewrite beyond the small target_kind backfill.

See: docs/architecture/DATABASE_MODEL.md §7, §8
     database/migrations/versions/020_character_builds.py
     database/migrations/versions/021_character_timeline_state.py
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "029_character_corrections"
down_revision = "028_build_timeline_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. current_hit_points cannot exceed maximum_hit_points
    # ==========================================================================
    op.execute("""
        ALTER TABLE campaign.character_state
        ADD CONSTRAINT ck_character_state_current_within_max
            CHECK (current_hit_points <= maximum_hit_points);
    """)

    # ==========================================================================
    # 2. transformed_into_id must be a character in the same world
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_character_state_transformation_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_character_world   UUID;
            v_transformed_world UUID;
        BEGIN
            IF NEW.transformed_into_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT world_id INTO v_character_world
            FROM core.entities WHERE entity_id = NEW.character_id;

            SELECT world_id INTO v_transformed_world
            FROM core.entities WHERE entity_id = NEW.transformed_into_id;

            IF v_transformed_world IS DISTINCT FROM v_character_world THEN
                RAISE EXCEPTION
                    'Character % belongs to world %, but its transformed form % belongs '
                    'to world %',
                    NEW.character_id, v_character_world, NEW.transformed_into_id,
                    v_transformed_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_character_state_transformation_world() IS
        'Keeps transformed_into_id pointed at a character in the same world as the '
        'character being transformed.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_state_enforce_transformation_world
        BEFORE INSERT OR UPDATE ON campaign.character_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_character_state_transformation_world();
    """)

    # ==========================================================================
    # 3. rules.spells.code format, matching every sibling content table
    # ==========================================================================
    op.execute("""
        ALTER TABLE rules.spells
        ADD CONSTRAINT ck_spells_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$');
    """)

    # ==========================================================================
    # 4. Proficiency target kind must agree with proficiency_type, and a
    #    build cannot be granted the same semantic proficiency twice
    # ==========================================================================
    op.execute("""
        ALTER TABLE rules.proficiency_types
        ADD COLUMN target_kind TEXT
        CONSTRAINT ck_proficiency_types_target_kind
            CHECK (target_kind IN ('skill', 'saving_throw', 'free_text'));
    """)
    op.execute("""
        COMMENT ON COLUMN rules.proficiency_types.target_kind IS
        'Which column of character.character_proficiencies a proficiency of this type '
        'must set: skill_id, saving_throw_ability_id, or the free-text target_label '
        '(weapon/armor/tool categories with no dedicated lookup yet). Enforced by '
        'trigger on character.character_proficiencies.';
    """)
    op.execute("""
        UPDATE rules.proficiency_types SET target_kind = CASE code
            WHEN 'skill' THEN 'skill'
            WHEN 'saving_throw' THEN 'saving_throw'
            ELSE 'free_text'
        END
        WHERE target_kind IS NULL;
    """)
    op.execute("ALTER TABLE rules.proficiency_types ALTER COLUMN target_kind SET NOT NULL;")

    op.execute("""
        CREATE OR REPLACE FUNCTION character.enforce_proficiency_target_kind()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_target_kind TEXT;
        BEGIN
            SELECT target_kind INTO v_target_kind
            FROM rules.proficiency_types WHERE proficiency_type_id = NEW.proficiency_type_id;

            IF v_target_kind = 'skill' AND NEW.skill_id IS NULL THEN
                RAISE EXCEPTION
                    'Proficiency type % requires a skill target, but skill_id is not set',
                    NEW.proficiency_type_id
                    USING ERRCODE = 'integrity_constraint_violation';
            ELSIF v_target_kind = 'saving_throw' AND NEW.saving_throw_ability_id IS NULL THEN
                RAISE EXCEPTION
                    'Proficiency type % requires a saving-throw-ability target, but '
                    'saving_throw_ability_id is not set',
                    NEW.proficiency_type_id
                    USING ERRCODE = 'integrity_constraint_violation';
            ELSIF v_target_kind = 'free_text' AND NEW.target_label IS NULL THEN
                RAISE EXCEPTION
                    'Proficiency type % requires a free-text target, but target_label is '
                    'not set',
                    NEW.proficiency_type_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION character.enforce_proficiency_target_kind() IS
        'Keeps the target column a proficiency sets (skill_id, saving_throw_ability_id, '
        'or target_label) in agreement with its proficiency_type''s target_kind. Works '
        'alongside ck_character_proficiencies_one_target, which only requires exactly '
        'one to be set — this checks it is the right one.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_proficiencies_enforce_target_kind
        BEFORE INSERT OR UPDATE ON character.character_proficiencies
        FOR EACH ROW EXECUTE FUNCTION character.enforce_proficiency_target_kind();
    """)

    op.execute("""
        CREATE UNIQUE INDEX ux_character_proficiencies_build_skill
        ON character.character_proficiencies (character_build_id, skill_id)
        WHERE skill_id IS NOT NULL;
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_character_proficiencies_build_saving_throw
        ON character.character_proficiencies (character_build_id, saving_throw_ability_id)
        WHERE saving_throw_ability_id IS NOT NULL;
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_character_proficiencies_build_target_label
        ON character.character_proficiencies (character_build_id, target_label)
        WHERE target_label IS NOT NULL;
    """)

    # ==========================================================================
    # 5. Rule content a character uses must be allowed for its world
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION rules.ruleset_allowed_for_world(
            p_world_id UUID, p_ruleset_version_id UUID
        )
        RETURNS BOOLEAN
        LANGUAGE sql
        STABLE
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM rules.ruleset_versions rv
                JOIN rules.world_rulesets wr ON wr.ruleset_id = rv.ruleset_id
                WHERE rv.ruleset_version_id = p_ruleset_version_id
                  AND wr.world_id = p_world_id
            );
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION rules.ruleset_allowed_for_world(UUID, UUID) IS
        'True when the given ruleset version''s ruleset family is one the given world '
        'allows (rules.world_rulesets). Shared by the character/state world-allowance '
        'triggers below.';
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION character.enforce_character_species_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_world           UUID;
            v_species_version UUID;
        BEGIN
            SELECT world_id INTO v_world FROM core.entities WHERE entity_id = NEW.character_id;

            SELECT ruleset_version_id INTO v_species_version
            FROM rules.species WHERE species_id = NEW.species_id;

            IF NOT rules.ruleset_allowed_for_world(v_world, v_species_version) THEN
                RAISE EXCEPTION
                    'Species %''s ruleset is not allowed for world % (character %''s world)',
                    NEW.species_id, v_world, NEW.character_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION character.enforce_character_species_ruleset_allowed() IS
        'Keeps a character''s species drawn from a ruleset its own world allows.';
    """)
    op.execute("""
        CREATE TRIGGER tr_characters_enforce_species_ruleset_allowed
        BEFORE INSERT OR UPDATE ON character.characters
        FOR EACH ROW EXECUTE FUNCTION character.enforce_character_species_ruleset_allowed();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION character.enforce_build_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_world UUID;
        BEGIN
            SELECT world_id INTO v_world FROM core.entities WHERE entity_id = NEW.character_id;

            IF NOT rules.ruleset_allowed_for_world(v_world, NEW.ruleset_version_id) THEN
                RAISE EXCEPTION
                    'Build %''s ruleset version is not allowed for world % (character '
                    '%''s world)',
                    NEW.character_build_id, v_world, NEW.character_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION character.enforce_build_ruleset_allowed() IS
        'Keeps a character build pinned to a ruleset version its own world allows.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_builds_enforce_ruleset_allowed
        BEFORE INSERT OR UPDATE ON character.character_builds
        FOR EACH ROW EXECUTE FUNCTION character.enforce_build_ruleset_allowed();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_condition_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_world             UUID;
            v_condition_version UUID;
        BEGIN
            SELECT world_id INTO v_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT ruleset_version_id INTO v_condition_version
            FROM rules.conditions WHERE condition_id = NEW.condition_id;

            IF NOT rules.ruleset_allowed_for_world(v_world, v_condition_version) THEN
                RAISE EXCEPTION
                    'Condition %''s ruleset is not allowed for world % (timeline %''s world)',
                    NEW.condition_id, v_world, NEW.timeline_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_condition_ruleset_allowed() IS
        'Keeps an applied condition drawn from a ruleset the timeline''s world allows.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_conditions_enforce_ruleset_allowed
        BEFORE INSERT OR UPDATE ON campaign.character_conditions
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_condition_ruleset_allowed();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_resource_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_world            UUID;
            v_resource_version UUID;
        BEGIN
            SELECT world_id INTO v_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT ruleset_version_id INTO v_resource_version
            FROM rules.resource_definitions
            WHERE resource_definition_id = NEW.resource_definition_id;

            IF NOT rules.ruleset_allowed_for_world(v_world, v_resource_version) THEN
                RAISE EXCEPTION
                    'Resource definition %''s ruleset is not allowed for world % '
                    '(timeline %''s world)',
                    NEW.resource_definition_id, v_world, NEW.timeline_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_resource_ruleset_allowed() IS
        'Keeps a tracked resource drawn from a ruleset the timeline''s world allows.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_resources_enforce_ruleset_allowed
        BEFORE INSERT OR UPDATE ON campaign.character_resources
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_resource_ruleset_allowed();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "DROP TRIGGER IF EXISTS tr_character_resources_enforce_ruleset_allowed "
        "ON campaign.character_resources;"
    )
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_resource_ruleset_allowed();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_character_conditions_enforce_ruleset_allowed "
        "ON campaign.character_conditions;"
    )
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_condition_ruleset_allowed();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_character_builds_enforce_ruleset_allowed "
        "ON character.character_builds;"
    )
    op.execute("DROP FUNCTION IF EXISTS character.enforce_build_ruleset_allowed();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_characters_enforce_species_ruleset_allowed "
        "ON character.characters;"
    )
    op.execute("DROP FUNCTION IF EXISTS character.enforce_character_species_ruleset_allowed();")

    op.execute("DROP FUNCTION IF EXISTS rules.ruleset_allowed_for_world(UUID, UUID);")

    op.execute("DROP INDEX IF EXISTS character.ux_character_proficiencies_build_target_label;")
    op.execute("DROP INDEX IF EXISTS character.ux_character_proficiencies_build_saving_throw;")
    op.execute("DROP INDEX IF EXISTS character.ux_character_proficiencies_build_skill;")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_character_proficiencies_enforce_target_kind "
        "ON character.character_proficiencies;"
    )
    op.execute("DROP FUNCTION IF EXISTS character.enforce_proficiency_target_kind();")
    op.execute("ALTER TABLE rules.proficiency_types DROP COLUMN IF EXISTS target_kind;")

    op.execute("ALTER TABLE rules.spells DROP CONSTRAINT IF EXISTS ck_spells_code_format;")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_character_state_enforce_transformation_world "
        "ON campaign.character_state;"
    )
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_character_state_transformation_world();")

    op.execute(
        "ALTER TABLE campaign.character_state "
        "DROP CONSTRAINT IF EXISTS ck_character_state_current_within_max;"
    )
