"""Validate proficiency-type ruleset version

Revision ID: 032_proficiency_type_version
Revises: 031_world_ruleset_full_protect
Create Date: 2026-08-02 22:15:00.000000

Purpose:
    Corrective revision (PHASE4_REMAINING_ISSUES.md §3).
    character.enforce_proficiency_ruleset_version() (revision 026) checked
    the referenced skill or saving-throw ability against the build's ruleset
    version, but never checked proficiency_type_id itself — a build could be
    granted a proficiency whose rules.proficiency_types row belongs to a
    different ruleset version entirely.

Forward migration:
    - character.enforce_proficiency_ruleset_version() replaced: adds a
      proficiency_type_id-vs-build check alongside the existing skill/
      saving-throw checks. The trigger itself (revision 026) is unchanged.

Rollback:
    Supported. Restores revision 026's original function body verbatim.

Data implications:
    Creates no rows. No existing character_proficiencies row can violate
    this: every proficiency_type_id seeded so far (revision 022) shares its
    ruleset version with every build that could reference it.

Locking considerations:
    CREATE OR REPLACE FUNCTION does not lock or rewrite
    character.character_proficiencies.

See: PHASE4_REMAINING_ISSUES.md §3
     database/migrations/versions/026_ruleset_version_consistency.py
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "032_proficiency_type_version"
down_revision = "031_world_ruleset_full_protect"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

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

            SELECT ruleset_version_id INTO v_target_version
            FROM rules.proficiency_types WHERE proficiency_type_id = NEW.proficiency_type_id;
            IF v_target_version IS DISTINCT FROM v_build_version THEN
                RAISE EXCEPTION
                    'Build % uses ruleset version %, but proficiency type % belongs to '
                    'ruleset version %',
                    NEW.character_build_id, v_build_version, NEW.proficiency_type_id,
                    v_target_version
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

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
        'Keeps a proficiency''s type, and its skill or saving-throw-ability target, in '
        'the same ruleset version as its build. Free-text targets (target_label) have no '
        'version to check beyond the type itself.';
    """)


def downgrade() -> None:
    """Revert the migration."""

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
