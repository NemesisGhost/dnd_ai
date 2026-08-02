"""Ruleset-version consistency for the remaining cross-references

Revision ID: 026_ruleset_version_checks
Revises: 025_rules_provenance_canon
Create Date: 2026-08-02 19:30:00.000000

Purpose:
    Corrective revision (Phase 4 corrections review). Revisions 014 and 020
    already enforced ruleset-version agreement for a skill/its ability, a
    subclass/its class, an ability score/its build, and a class level/its
    build (and subclass/class). Revision 020's own docstring recorded the
    remaining gaps as a deliberate scope cut, not an oversight — but the
    corrections review asks for the full set to actually be closed. This
    revision adds the rest:

      - rules.classes.primary_ability_id <-> rules.classes.ruleset_version_id
      - rules.features.{class_id,subclass_id,species_id} <-> ruleset_version_id
      - rules.spells.damage_type_id <-> ruleset_version_id
      - character.character_proficiencies.{skill_id,saving_throw_ability_id}
        <-> its build's ruleset_version_id
      - character.character_features.feature_id <-> its build's ruleset_version_id
      - character.character_spellcasting_profiles.{class_id,spellcasting_ability_id}
        <-> its build's ruleset_version_id
      - character.character_known_spells / character.character_prepared_spells
        .spell_id <-> its profile's build's ruleset_version_id

    Each follows the established pattern (revisions 014, 020): a comparison
    across rows cannot be a CHECK, so a BEFORE INSERT OR UPDATE trigger reads
    both sides and raises on disagreement.

Forward migration:
    - rules.enforce_class_primary_ability_ruleset_version()
    - rules.enforce_feature_ruleset_version()
    - rules.enforce_spell_damage_type_ruleset_version()
    - character.enforce_proficiency_ruleset_version()
    - character.enforce_feature_ruleset_version()
    - character.enforce_spellcasting_profile_ruleset_version()
    - character.enforce_spell_association_ruleset_version() (shared by
      known and prepared spells)

Rollback:
    Supported. Drops each trigger and its function.

Data implications:
    Creates no rows. Existing seeded content (revision 022) already agrees
    on ruleset version in every one of these relationships, since it was
    all seeded against a single ruleset_version_id — no existing row can
    violate any of these triggers.

Locking considerations:
    Adding a trigger does not rewrite a table.

See: docs/DATABASE_CONVENTIONS.md §9.5 (same-world/same-scope consistency)
     database/migrations/versions/014_ruleset_content.py
     database/migrations/versions/020_character_builds.py (the scope-cut note)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "026_ruleset_version_checks"
down_revision = "025_rules_provenance_canon"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. rules.classes.primary_ability_id
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION rules.enforce_class_primary_ability_ruleset_version()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_ability_version UUID;
        BEGIN
            IF NEW.primary_ability_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT ruleset_version_id INTO v_ability_version
            FROM rules.abilities WHERE ability_id = NEW.primary_ability_id;

            IF v_ability_version IS DISTINCT FROM NEW.ruleset_version_id THEN
                RAISE EXCEPTION
                    'Class % belongs to ruleset version %, but its primary ability % '
                    'belongs to ruleset version %',
                    NEW.class_id, NEW.ruleset_version_id, NEW.primary_ability_id, v_ability_version
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION rules.enforce_class_primary_ability_ruleset_version() IS
        'Keeps a class''s primary ability in the same ruleset version as the class.';
    """)
    op.execute("""
        CREATE TRIGGER tr_classes_enforce_primary_ability_ruleset_version
        BEFORE INSERT OR UPDATE ON rules.classes
        FOR EACH ROW EXECUTE FUNCTION rules.enforce_class_primary_ability_ruleset_version();
    """)

    # ==========================================================================
    # 2. rules.features.{class_id,subclass_id,species_id}
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION rules.enforce_feature_ruleset_version()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_version UUID;
        BEGIN
            IF NEW.class_id IS NOT NULL THEN
                SELECT ruleset_version_id INTO v_version
                FROM rules.classes WHERE class_id = NEW.class_id;
                IF v_version IS DISTINCT FROM NEW.ruleset_version_id THEN
                    RAISE EXCEPTION
                        'Feature % belongs to ruleset version %, but its class % belongs '
                        'to ruleset version %',
                        NEW.feature_id, NEW.ruleset_version_id, NEW.class_id, v_version
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.subclass_id IS NOT NULL THEN
                SELECT ruleset_version_id INTO v_version
                FROM rules.subclasses WHERE subclass_id = NEW.subclass_id;
                IF v_version IS DISTINCT FROM NEW.ruleset_version_id THEN
                    RAISE EXCEPTION
                        'Feature % belongs to ruleset version %, but its subclass % '
                        'belongs to ruleset version %',
                        NEW.feature_id, NEW.ruleset_version_id, NEW.subclass_id, v_version
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.species_id IS NOT NULL THEN
                SELECT ruleset_version_id INTO v_version
                FROM rules.species WHERE species_id = NEW.species_id;
                IF v_version IS DISTINCT FROM NEW.ruleset_version_id THEN
                    RAISE EXCEPTION
                        'Feature % belongs to ruleset version %, but its species % '
                        'belongs to ruleset version %',
                        NEW.feature_id, NEW.ruleset_version_id, NEW.species_id, v_version
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION rules.enforce_feature_ruleset_version() IS
        'Keeps a feature''s class, subclass, and species associations (each independently '
        'nullable) in the same ruleset version as the feature.';
    """)
    op.execute("""
        CREATE TRIGGER tr_features_enforce_ruleset_version
        BEFORE INSERT OR UPDATE ON rules.features
        FOR EACH ROW EXECUTE FUNCTION rules.enforce_feature_ruleset_version();
    """)

    # ==========================================================================
    # 3. rules.spells.damage_type_id
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION rules.enforce_spell_damage_type_ruleset_version()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_version UUID;
        BEGIN
            IF NEW.damage_type_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT ruleset_version_id INTO v_version
            FROM rules.damage_types WHERE damage_type_id = NEW.damage_type_id;

            IF v_version IS DISTINCT FROM NEW.ruleset_version_id THEN
                RAISE EXCEPTION
                    'Spell % belongs to ruleset version %, but its damage type % belongs '
                    'to ruleset version %',
                    NEW.spell_id, NEW.ruleset_version_id, NEW.damage_type_id, v_version
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION rules.enforce_spell_damage_type_ruleset_version() IS
        'Keeps a spell''s optional damage type in the same ruleset version as the spell.';
    """)
    op.execute("""
        CREATE TRIGGER tr_spells_enforce_damage_type_ruleset_version
        BEFORE INSERT OR UPDATE ON rules.spells
        FOR EACH ROW EXECUTE FUNCTION rules.enforce_spell_damage_type_ruleset_version();
    """)

    # ==========================================================================
    # 4. character.character_proficiencies vs its build
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION character.enforce_proficiency_ruleset_version()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_build_version  UUID;
            v_target_version UUID;
        BEGIN
            SELECT ruleset_version_id INTO v_build_version
            FROM character.character_builds WHERE character_build_id = NEW.character_build_id;

            IF NEW.skill_id IS NOT NULL THEN
                SELECT ruleset_version_id INTO v_target_version
                FROM rules.skills WHERE skill_id = NEW.skill_id;
                IF v_target_version IS DISTINCT FROM v_build_version THEN
                    RAISE EXCEPTION
                        'Build % uses ruleset version %, but proficiency skill % belongs '
                        'to ruleset version %',
                        NEW.character_build_id, v_build_version, NEW.skill_id, v_target_version
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.saving_throw_ability_id IS NOT NULL THEN
                SELECT ruleset_version_id INTO v_target_version
                FROM rules.abilities WHERE ability_id = NEW.saving_throw_ability_id;
                IF v_target_version IS DISTINCT FROM v_build_version THEN
                    RAISE EXCEPTION
                        'Build % uses ruleset version %, but proficiency saving-throw '
                        'ability % belongs to ruleset version %',
                        NEW.character_build_id, v_build_version, NEW.saving_throw_ability_id,
                        v_target_version
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION character.enforce_proficiency_ruleset_version() IS
        'Keeps a proficiency''s skill or saving-throw-ability target in the same ruleset '
        'version as its build. Free-text targets (target_label) have no version to check.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_proficiencies_enforce_ruleset_version
        BEFORE INSERT OR UPDATE ON character.character_proficiencies
        FOR EACH ROW EXECUTE FUNCTION character.enforce_proficiency_ruleset_version();
    """)

    # ==========================================================================
    # 5. character.character_features vs its build
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION character.enforce_feature_ruleset_version()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_build_version   UUID;
            v_feature_version UUID;
        BEGIN
            SELECT ruleset_version_id INTO v_build_version
            FROM character.character_builds WHERE character_build_id = NEW.character_build_id;

            SELECT ruleset_version_id INTO v_feature_version
            FROM rules.features WHERE feature_id = NEW.feature_id;

            IF v_feature_version IS DISTINCT FROM v_build_version THEN
                RAISE EXCEPTION
                    'Build % uses ruleset version %, but feature % belongs to ruleset '
                    'version %',
                    NEW.character_build_id, v_build_version, NEW.feature_id, v_feature_version
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION character.enforce_feature_ruleset_version() IS
        'Keeps a granted feature in the same ruleset version as its build.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_features_enforce_ruleset_version
        BEFORE INSERT OR UPDATE ON character.character_features
        FOR EACH ROW EXECUTE FUNCTION character.enforce_feature_ruleset_version();
    """)

    # ==========================================================================
    # 6. character.character_spellcasting_profiles vs its build
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION character.enforce_spellcasting_profile_ruleset_version()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_build_version  UUID;
            v_target_version UUID;
        BEGIN
            SELECT ruleset_version_id INTO v_build_version
            FROM character.character_builds WHERE character_build_id = NEW.character_build_id;

            IF NEW.class_id IS NOT NULL THEN
                SELECT ruleset_version_id INTO v_target_version
                FROM rules.classes WHERE class_id = NEW.class_id;
                IF v_target_version IS DISTINCT FROM v_build_version THEN
                    RAISE EXCEPTION
                        'Build % uses ruleset version %, but spellcasting profile class % '
                        'belongs to ruleset version %',
                        NEW.character_build_id, v_build_version, NEW.class_id, v_target_version
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            SELECT ruleset_version_id INTO v_target_version
            FROM rules.abilities WHERE ability_id = NEW.spellcasting_ability_id;
            IF v_target_version IS DISTINCT FROM v_build_version THEN
                RAISE EXCEPTION
                    'Build % uses ruleset version %, but spellcasting ability % belongs '
                    'to ruleset version %',
                    NEW.character_build_id, v_build_version, NEW.spellcasting_ability_id,
                    v_target_version
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION character.enforce_spellcasting_profile_ruleset_version() IS
        'Keeps a spellcasting profile''s optional class and its spellcasting ability in '
        'the same ruleset version as its build.';
    """)
    op.execute("""
        CREATE TRIGGER tr_spellcasting_profiles_enforce_ruleset_version
        BEFORE INSERT OR UPDATE ON character.character_spellcasting_profiles
        FOR EACH ROW EXECUTE FUNCTION character.enforce_spellcasting_profile_ruleset_version();
    """)

    # ==========================================================================
    # 7. character.character_known_spells / character_prepared_spells vs
    #    their profile's build
    # ==========================================================================
    # One shared function attached to both tables — identical shape
    # (character_spellcasting_profile_id, spell_id) and identical rule.
    op.execute("""
        CREATE OR REPLACE FUNCTION character.enforce_spell_association_ruleset_version()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_build_version UUID;
            v_spell_version UUID;
        BEGIN
            SELECT cb.ruleset_version_id INTO v_build_version
            FROM character.character_spellcasting_profiles p
            JOIN character.character_builds cb ON cb.character_build_id = p.character_build_id
            WHERE p.character_spellcasting_profile_id = NEW.character_spellcasting_profile_id;

            SELECT ruleset_version_id INTO v_spell_version
            FROM rules.spells WHERE spell_id = NEW.spell_id;

            IF v_spell_version IS DISTINCT FROM v_build_version THEN
                RAISE EXCEPTION
                    'Spellcasting profile %''s build uses ruleset version %, but spell % '
                    'belongs to ruleset version %',
                    NEW.character_spellcasting_profile_id, v_build_version, NEW.spell_id,
                    v_spell_version
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION character.enforce_spell_association_ruleset_version() IS
        'Keeps a known/prepared spell in the same ruleset version as its spellcasting '
        'profile''s build. Attached to both character_known_spells and '
        'character_prepared_spells — identical shape and rule.';
    """)
    op.execute("""
        CREATE TRIGGER tr_known_spells_enforce_ruleset_version
        BEFORE INSERT OR UPDATE ON character.character_known_spells
        FOR EACH ROW EXECUTE FUNCTION character.enforce_spell_association_ruleset_version();
    """)
    op.execute("""
        CREATE TRIGGER tr_prepared_spells_enforce_ruleset_version
        BEFORE INSERT OR UPDATE ON character.character_prepared_spells
        FOR EACH ROW EXECUTE FUNCTION character.enforce_spell_association_ruleset_version();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "DROP TRIGGER IF EXISTS tr_prepared_spells_enforce_ruleset_version "
        "ON character.character_prepared_spells;"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS tr_known_spells_enforce_ruleset_version "
        "ON character.character_known_spells;"
    )
    op.execute("DROP FUNCTION IF EXISTS character.enforce_spell_association_ruleset_version();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_spellcasting_profiles_enforce_ruleset_version "
        "ON character.character_spellcasting_profiles;"
    )
    op.execute("DROP FUNCTION IF EXISTS character.enforce_spellcasting_profile_ruleset_version();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_character_features_enforce_ruleset_version "
        "ON character.character_features;"
    )
    op.execute("DROP FUNCTION IF EXISTS character.enforce_feature_ruleset_version();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_character_proficiencies_enforce_ruleset_version "
        "ON character.character_proficiencies;"
    )
    op.execute("DROP FUNCTION IF EXISTS character.enforce_proficiency_ruleset_version();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_spells_enforce_damage_type_ruleset_version ON rules.spells;"
    )
    op.execute("DROP FUNCTION IF EXISTS rules.enforce_spell_damage_type_ruleset_version();")

    op.execute("DROP TRIGGER IF EXISTS tr_features_enforce_ruleset_version ON rules.features;")
    op.execute("DROP FUNCTION IF EXISTS rules.enforce_feature_ruleset_version();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_classes_enforce_primary_ability_ruleset_version "
        "ON rules.classes;"
    )
    op.execute("DROP FUNCTION IF EXISTS rules.enforce_class_primary_ability_ruleset_version();")
