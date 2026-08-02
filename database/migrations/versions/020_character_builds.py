"""Character builds

Revision ID: 020_character_builds
Revises: 019_character_shared_data
Create Date: 2026-08-02 16:30:00.000000

Purpose:
    Delivers docs/PLAN.md §7.4's build tables — the actual mechanical
    snapshot a character sheet is assembled from. "Builds are versioned
    definitions" (§7.2): a build is pinned to one rules.ruleset_versions row,
    and everything hanging off it (ability scores, class levels,
    proficiencies, features, spellcasting) belongs to that build, not
    directly to the character, so a character can be rebuilt or leveled up
    as a new build without losing the old one's history.

    Current hit points, conditions, and spell-slot use are NOT here — those
    are timeline state (campaign.character_state and friends), delivered in
    the next revision, and change during play independently of the build.

Forward migration:
    - character.character_builds
    - character.character_ability_scores
    - character.character_class_levels (supports multiclassing: one row per
      class within a build)
    - character.character_proficiencies
    - character.character_features
    - character.character_spellcasting_profiles
    - character.character_known_spells
    - character.character_prepared_spells

Rollback:
    Supported. Drops all eight tables in dependency order.

Data implications:
    Creates no rows.

Locking considerations:
    None. All tables are new and empty.

Simplifications:
    Ruleset-version agreement is enforced by trigger for ability scores and
    class levels (the two cases where a wrong-version reference would be
    most confusing to debug), following the pattern used throughout this
    project for cross-row invariants. Proficiencies, features, and
    spellcasting profiles rely on their target rows' own FKs for referential
    validity but do not cross-check ruleset version against the build — a
    deliberate scope cut given Phase 4's exit criteria, not an oversight;
    revisit if mixed-version references turn out to be a real problem.

See: docs/PLAN.md §7.4 (character builds)
     docs/architecture/DATABASE_MODEL.md §7.4
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "020_character_builds"
down_revision = "019_character_shared_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. character.character_builds
    # ==========================================================================
    op.execute("""
        CREATE TABLE character.character_builds (
            character_build_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            character_id        UUID NOT NULL
                                REFERENCES character.characters(character_id)
                                ON DELETE CASCADE,
            ruleset_version_id  UUID NOT NULL
                                REFERENCES rules.ruleset_versions(ruleset_version_id)
                                ON DELETE RESTRICT,
            label               TEXT,
            is_current          BOOLEAN NOT NULL DEFAULT FALSE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.character_builds IS
        'A versioned mechanical snapshot of a character, pinned to one ruleset version. '
        'Ability scores, class levels, proficiencies, features, and spellcasting all '
        'belong to a build, not directly to the character, so re-leveling or rebuilding '
        'does not erase the prior build''s history.';
    """)
    op.execute("""
        COMMENT ON COLUMN character.character_builds.is_current IS
        'The build a character sheet is assembled from by default. At most one per '
        'character, enforced by a partial unique index rather than a CHECK, since the '
        'rule spans rows.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_builds_set_updated_at
        BEFORE UPDATE ON character.character_builds
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_character_builds_character_id ON character.character_builds (character_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_builds_ruleset_version_id "
        "ON character.character_builds (ruleset_version_id);"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_character_builds_one_current_per_character
        ON character.character_builds (character_id)
        WHERE is_current;
    """)

    # ==========================================================================
    # 2. character.character_ability_scores
    # ==========================================================================
    op.execute("""
        CREATE TABLE character.character_ability_scores (
            character_build_id  UUID NOT NULL
                                REFERENCES character.character_builds(character_build_id)
                                ON DELETE CASCADE,
            ability_id          UUID NOT NULL
                                REFERENCES rules.abilities(ability_id) ON DELETE RESTRICT,
            score               core.nonnegative_integer NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (character_build_id, ability_id),
            CONSTRAINT ck_character_ability_scores_positive CHECK (score > 0)
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.character_ability_scores IS
        'The raw score (e.g. 16) a build has in one ability. Modifiers are derived, not '
        'stored.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_ability_scores_set_updated_at
        BEFORE UPDATE ON character.character_ability_scores
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_character_ability_scores_ability_id "
        "ON character.character_ability_scores (ability_id);"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION character.enforce_ability_score_ruleset_version()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_build_version   UUID;
            v_ability_version UUID;
        BEGIN
            SELECT ruleset_version_id INTO v_build_version
            FROM character.character_builds WHERE character_build_id = NEW.character_build_id;

            SELECT ruleset_version_id INTO v_ability_version
            FROM rules.abilities WHERE ability_id = NEW.ability_id;

            IF v_ability_version IS DISTINCT FROM v_build_version THEN
                RAISE EXCEPTION
                    'Build % uses ruleset version %, but ability % belongs to ruleset '
                    'version %',
                    NEW.character_build_id, v_build_version, NEW.ability_id, v_ability_version
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION character.enforce_ability_score_ruleset_version() IS
        'Keeps an ability score''s ability in the same ruleset version as its build.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_ability_scores_enforce_ruleset_version
        BEFORE INSERT OR UPDATE ON character.character_ability_scores
        FOR EACH ROW EXECUTE FUNCTION character.enforce_ability_score_ruleset_version();
    """)

    # ==========================================================================
    # 3. character.character_class_levels
    # ==========================================================================
    # One row per class within a build (the primary key), which is what makes
    # multiclassing representable: a build may hold levels in more than one
    # class at once.
    op.execute("""
        CREATE TABLE character.character_class_levels (
            character_build_id  UUID NOT NULL
                                REFERENCES character.character_builds(character_build_id)
                                ON DELETE CASCADE,
            class_id            UUID NOT NULL
                                REFERENCES rules.classes(class_id) ON DELETE RESTRICT,
            subclass_id         UUID
                                REFERENCES rules.subclasses(subclass_id) ON DELETE RESTRICT,
            level               core.nonnegative_integer NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (character_build_id, class_id),
            CONSTRAINT ck_character_class_levels_positive CHECK (level > 0)
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.character_class_levels IS
        'A build''s level in one class. Multiple rows per build support multiclassing.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_class_levels_set_updated_at
        BEFORE UPDATE ON character.character_class_levels
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_character_class_levels_class_id "
        "ON character.character_class_levels (class_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_class_levels_subclass_id "
        "ON character.character_class_levels (subclass_id) WHERE subclass_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION character.enforce_class_level_consistency()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_build_version UUID;
            v_class_version UUID;
            v_subclass_class UUID;
        BEGIN
            SELECT ruleset_version_id INTO v_build_version
            FROM character.character_builds WHERE character_build_id = NEW.character_build_id;

            SELECT ruleset_version_id INTO v_class_version
            FROM rules.classes WHERE class_id = NEW.class_id;

            IF v_class_version IS DISTINCT FROM v_build_version THEN
                RAISE EXCEPTION
                    'Build % uses ruleset version %, but class % belongs to ruleset '
                    'version %',
                    NEW.character_build_id, v_build_version, NEW.class_id, v_class_version
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.subclass_id IS NOT NULL THEN
                SELECT class_id INTO v_subclass_class
                FROM rules.subclasses WHERE subclass_id = NEW.subclass_id;

                IF v_subclass_class IS DISTINCT FROM NEW.class_id THEN
                    RAISE EXCEPTION
                        'Subclass % belongs to class %, not class %',
                        NEW.subclass_id, v_subclass_class, NEW.class_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION character.enforce_class_level_consistency() IS
        'Keeps a class level''s class in the same ruleset version as its build, and its '
        'optional subclass belonging to that same class.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_class_levels_enforce_consistency
        BEFORE INSERT OR UPDATE ON character.character_class_levels
        FOR EACH ROW EXECUTE FUNCTION character.enforce_class_level_consistency();
    """)

    # ==========================================================================
    # 4. character.character_proficiencies
    # ==========================================================================
    # A proficiency names exactly one target: a skill, a saving-throw ability,
    # or a free-text target (a specific weapon, armor category, or tool — this
    # project has no dedicated lookup for those yet, and inventing one
    # unprompted is exactly the drift this project just spent effort
    # reconciling). The CHECK requires exactly one, so a row's meaning is
    # never ambiguous.
    op.execute("""
        CREATE TABLE character.character_proficiencies (
            character_proficiency_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            character_build_id        UUID NOT NULL
                                      REFERENCES character.character_builds(character_build_id)
                                      ON DELETE CASCADE,
            proficiency_type_id       UUID NOT NULL
                                      REFERENCES rules.proficiency_types(proficiency_type_id)
                                      ON DELETE RESTRICT,
            skill_id                  UUID REFERENCES rules.skills(skill_id) ON DELETE CASCADE,
            saving_throw_ability_id   UUID REFERENCES rules.abilities(ability_id) ON DELETE CASCADE,
            target_label              TEXT,
            is_expertise               BOOLEAN NOT NULL DEFAULT FALSE,
            created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_character_proficiencies_one_target CHECK (
                num_nonnulls(skill_id, saving_throw_ability_id, target_label) = 1
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.character_proficiencies IS
        'A build''s proficiency in a skill, a saving-throw ability, or a free-text '
        'target (a weapon, armor category, or tool). Exactly one of skill_id, '
        'saving_throw_ability_id, and target_label is set.';
    """)
    op.execute(
        "CREATE INDEX ix_character_proficiencies_build_id "
        "ON character.character_proficiencies (character_build_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_proficiencies_type_id "
        "ON character.character_proficiencies (proficiency_type_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_proficiencies_skill_id "
        "ON character.character_proficiencies (skill_id) WHERE skill_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_character_proficiencies_saving_throw_ability_id "
        "ON character.character_proficiencies (saving_throw_ability_id) "
        "WHERE saving_throw_ability_id IS NOT NULL;"
    )

    # ==========================================================================
    # 5. character.character_features
    # ==========================================================================
    op.execute("""
        CREATE TABLE character.character_features (
            character_build_id  UUID NOT NULL
                                REFERENCES character.character_builds(character_build_id)
                                ON DELETE CASCADE,
            feature_id          UUID NOT NULL
                                REFERENCES rules.features(feature_id) ON DELETE RESTRICT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (character_build_id, feature_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.character_features IS
        'A feature a build has been granted, from its class, subclass, or species.';
    """)
    op.execute(
        "CREATE INDEX ix_character_features_feature_id ON character.character_features (feature_id);"
    )

    # ==========================================================================
    # 6. character.character_spellcasting_profiles
    # ==========================================================================
    # class_id is nullable to allow a species- or feat-granted spellcasting
    # profile with no owning class. Unique per (build, class) when class_id is
    # set — a build has at most one profile per class; multiple class-less
    # profiles are permitted since NULL is never equal to itself in a UNIQUE
    # constraint.
    op.execute("""
        CREATE TABLE character.character_spellcasting_profiles (
            character_spellcasting_profile_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            character_build_id                 UUID NOT NULL
                                               REFERENCES character.character_builds(character_build_id)
                                               ON DELETE CASCADE,
            class_id                            UUID
                                               REFERENCES rules.classes(class_id) ON DELETE CASCADE,
            spellcasting_ability_id             UUID NOT NULL
                                               REFERENCES rules.abilities(ability_id) ON DELETE RESTRICT,
            created_at                          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_spellcasting_profiles_build_class UNIQUE (character_build_id, class_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.character_spellcasting_profiles IS
        'A source of spellcasting for a build (Wizard casting, Warlock Pact Magic, ...) '
        'and the ability it keys off. class_id is NULL for species- or feat-granted '
        'casting with no owning class.';
    """)
    op.execute(
        "CREATE INDEX ix_spellcasting_profiles_build_id "
        "ON character.character_spellcasting_profiles (character_build_id);"
    )
    op.execute(
        "CREATE INDEX ix_spellcasting_profiles_class_id "
        "ON character.character_spellcasting_profiles (class_id) WHERE class_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_spellcasting_profiles_ability_id "
        "ON character.character_spellcasting_profiles (spellcasting_ability_id);"
    )

    # ==========================================================================
    # 7. character.character_known_spells / character_prepared_spells
    # ==========================================================================
    # Kept as two independent association tables rather than one with a
    # "prepared" flag: whether "prepared" is even a meaningful subset of
    # "known" varies by class and edition (a Wizard prepares from a
    # spellbook; a Sorcerer just knows spells and never separately prepares),
    # so this migration does not hardcode prepared subset-of-known as an
    # invariant.
    op.execute("""
        CREATE TABLE character.character_known_spells (
            character_spellcasting_profile_id  UUID NOT NULL
                                               REFERENCES character.character_spellcasting_profiles(
                                                   character_spellcasting_profile_id
                                               ) ON DELETE CASCADE,
            spell_id                            UUID NOT NULL
                                               REFERENCES rules.spells(spell_id) ON DELETE RESTRICT,
            created_at                          TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (character_spellcasting_profile_id, spell_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.character_known_spells IS
        'Spells a spellcasting profile knows, independent of whether they are prepared.';
    """)
    op.execute(
        "CREATE INDEX ix_character_known_spells_spell_id "
        "ON character.character_known_spells (spell_id);"
    )

    op.execute("""
        CREATE TABLE character.character_prepared_spells (
            character_spellcasting_profile_id  UUID NOT NULL
                                               REFERENCES character.character_spellcasting_profiles(
                                                   character_spellcasting_profile_id
                                               ) ON DELETE CASCADE,
            spell_id                            UUID NOT NULL
                                               REFERENCES rules.spells(spell_id) ON DELETE RESTRICT,
            created_at                          TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (character_spellcasting_profile_id, spell_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.character_prepared_spells IS
        'Spells currently prepared for a spellcasting profile. Not constrained to be a '
        'subset of known spells: whether that subset relationship applies at all varies '
        'by class.';
    """)
    op.execute(
        "CREATE INDEX ix_character_prepared_spells_spell_id "
        "ON character.character_prepared_spells (spell_id);"
    )


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS character.character_prepared_spells;")
    op.execute("DROP TABLE IF EXISTS character.character_known_spells;")
    op.execute("DROP TABLE IF EXISTS character.character_spellcasting_profiles;")
    op.execute("DROP TABLE IF EXISTS character.character_features;")
    op.execute("DROP TABLE IF EXISTS character.character_proficiencies;")
    op.execute("DROP TABLE IF EXISTS character.character_class_levels;")
    op.execute("DROP FUNCTION IF EXISTS character.enforce_class_level_consistency();")
    op.execute("DROP TABLE IF EXISTS character.character_ability_scores;")
    op.execute("DROP FUNCTION IF EXISTS character.enforce_ability_score_ruleset_version();")
    op.execute("DROP TABLE IF EXISTS character.character_builds;")
