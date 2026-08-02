"""Immutable rules-identity columns

Revision ID: 033_rules_identity_immutable
Revises: 032_proficiency_type_version
Create Date: 2026-08-02 22:30:00.000000

Purpose:
    Corrective revision (PHASE4_REMAINING_ISSUES.md §2). Revision 030 made
    world/timeline/party/campaign scope columns immutable, closing the
    "parent row's own identity changes out from under already-valid
    children" gap for *world* scope, but every ruleset-version-consistency
    trigger from revisions 014, 015, 020, 026, and 029 has the identical
    problem for *rules* identity: each validates a child row against its
    parent's current ruleset_version_id (or, for subclasses/features, its
    parent class/subclass/species) only when the *child* is inserted or
    updated. Nothing stopped the *parent* row's own identity from changing
    afterward and invalidating every already-valid child that assumed it
    would not.

    None of the columns protected here represent a legitimate "move" or
    "reassignment" — a ruleset version's own ruleset, a rule-content row's
    ruleset version, a subclass's class, a feature's class/subclass/species,
    and a build's owning character and pinned ruleset version are all
    identity, matching revision 030's own stated preference for immutability
    over a transactional revalidate-and-rebuild path. Reusing revision 030's
    generic core.enforce_immutable_columns() rather than one bespoke trigger
    per table.

    Two columns outside the ruleset_version_id pattern are included because
    they gate an existing cross-row invariant the same way a ruleset_version_id
    change would: rules.subclasses.class_id (its ruleset_version_id is only
    as trustworthy as the class it is derived from — revision 015) and
    rules.features.class_id/subclass_id/species_id (already independently
    nullable identity references a feature grant assumes are fixed).
    rules.proficiency_types.target_kind is included because
    character.enforce_proficiency_target_kind() (revision 029) only checks it
    at the child row's own insert/update — an admin edit to target_kind after
    proficiencies already exist would silently invalidate them the same way.

    core.enforce_immutable_columns() (revision 030) is also corrected here:
    it rejected *any* change to a protected column, including a NULL ->
    value transition — which is a column being *set* for the first time, not
    a change to something already set, and revision 029's own
    add-column-then-backfill pattern for rules.proficiency_types.target_kind
    (ADD COLUMN nullable, UPDATE to backfill, then SET NOT NULL) depends on
    exactly that being allowed. Every revision-030 protected column is
    already NOT NULL from insert, so this only relaxes behavior for the
    nullable columns revision 033 protects (rules.features.class_id/
    subclass_id/species_id) — matching the function's own "immutable once
    set" name and comment rather than "immutable, full stop".

    Ability/class/damage-type associations that are *not* used as the parent
    side of a cross-version invariant (rules.classes.primary_ability_id,
    rules.skills.ability_id, rules.spells.damage_type_id) are deliberately
    left mutable: no other row's validity depends on those specific
    associations beyond what each row's own insert/update trigger already
    re-checks on itself, so freezing them would add friction without closing
    a real gap. This is the policy DATABASE_MODEL.md §8 now records.

Forward migration:
    - core.enforce_immutable_columns() (revision 030) replaced to allow a
      NULL -> value transition (see above)
    - New immutability triggers using it, attached to:
      rules.ruleset_versions (ruleset_id),
      rules.abilities / species / damage_types / conditions /
        resource_definitions / skills / classes (ruleset_version_id),
      rules.subclasses (ruleset_version_id, class_id),
      rules.features (ruleset_version_id, class_id, subclass_id, species_id),
      rules.spells (ruleset_version_id),
      rules.proficiency_types (ruleset_version_id, target_kind),
      character.character_builds (character_id, ruleset_version_id),
      character.character_spellcasting_profiles (character_build_id)

Rollback:
    Supported. Drops every trigger added here and restores revision 030's
    original (stricter, NULL-inclusive) core.enforce_immutable_columns() body.

Data implications:
    Creates no rows. No test fixture in this project updates any of these
    columns after insert (grepped before writing this revision, following
    revision 030's own note), so nothing existing breaks.

Locking considerations:
    Adding a trigger does not rewrite a table.

See: PHASE4_REMAINING_ISSUES.md §2
     docs/architecture/DATABASE_MODEL.md §8 (rules model)
     database/migrations/versions/030_parent_scope_immutability.py
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "033_rules_identity_immutable"
down_revision = "032_proficiency_type_version"
branch_labels = None
depends_on = None

# (schema, table, trigger_name, [protected columns])
PROTECTED: list[tuple[str, str, str, list[str]]] = [
    ("rules", "ruleset_versions", "tr_ruleset_versions_enforce_immutable", ["ruleset_id"]),
    ("rules", "abilities", "tr_abilities_enforce_immutable", ["ruleset_version_id"]),
    ("rules", "species", "tr_species_enforce_immutable", ["ruleset_version_id"]),
    ("rules", "damage_types", "tr_damage_types_enforce_immutable", ["ruleset_version_id"]),
    ("rules", "conditions", "tr_conditions_enforce_immutable", ["ruleset_version_id"]),
    (
        "rules",
        "resource_definitions",
        "tr_resource_definitions_enforce_immutable",
        ["ruleset_version_id"],
    ),
    ("rules", "skills", "tr_skills_enforce_immutable", ["ruleset_version_id"]),
    ("rules", "classes", "tr_classes_enforce_immutable", ["ruleset_version_id"]),
    (
        "rules",
        "subclasses",
        "tr_subclasses_enforce_immutable",
        ["ruleset_version_id", "class_id"],
    ),
    (
        "rules",
        "features",
        "tr_features_enforce_immutable",
        ["ruleset_version_id", "class_id", "subclass_id", "species_id"],
    ),
    ("rules", "spells", "tr_spells_enforce_immutable", ["ruleset_version_id"]),
    (
        "rules",
        "proficiency_types",
        "tr_proficiency_types_enforce_immutable",
        ["ruleset_version_id", "target_kind"],
    ),
    (
        "character",
        "character_builds",
        "tr_character_builds_enforce_immutable",
        ["character_id", "ruleset_version_id"],
    ),
    (
        "character",
        "character_spellcasting_profiles",
        "tr_spellcasting_profiles_enforce_immutable",
        ["character_build_id"],
    ),
]


def upgrade() -> None:
    """Apply the migration."""

    # A NULL -> value transition is a column being *set*, not changed — only
    # reject when the old value was already non-null. Every revision-030
    # protected column is NOT NULL from insert, so this only changes behavior
    # for the nullable columns this revision protects.
    op.execute("""
        CREATE OR REPLACE FUNCTION core.enforce_immutable_columns()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_old  JSONB := to_jsonb(OLD);
            v_new  JSONB := to_jsonb(NEW);
            v_col  TEXT;
        BEGIN
            FOR i IN 0 .. TG_NARGS - 1 LOOP
                v_col := TG_ARGV[i];
                -- to_jsonb() turns a SQL NULL column into a JSON null, which
                -- is itself a non-NULL jsonb value under `->` — ->> (text
                -- extraction) is what actually collapses a JSON null back to
                -- a real SQL NULL, so the "was it already set" check must
                -- use ->>, not ->.
                IF v_old ->> v_col IS NOT NULL AND v_old -> v_col IS DISTINCT FROM v_new -> v_col THEN
                    RAISE EXCEPTION
                        '%.% is immutable on %.% and cannot be changed once set',
                        TG_TABLE_NAME, v_col, TG_TABLE_SCHEMA, TG_TABLE_NAME
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END LOOP;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.enforce_immutable_columns() IS
        'Generic guard rejecting UPDATEs that change any of the columns named in the '
        'trigger''s arguments away from a non-NULL value. A NULL -> value transition is '
        'allowed (the column being set for the first time, not changed). Attach with the '
        'protected column names as trigger arguments, the same shape as '
        'core.enforce_entity_subtype(''<pk_column>'').';
    """)

    for schema, table, trigger_name, columns in PROTECTED:
        args = ", ".join(f"'{c}'" for c in columns)
        op.execute(f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE ON {schema}.{table}
            FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns({args});
        """)


def downgrade() -> None:
    """Revert the migration."""

    for schema, table, trigger_name, _columns in reversed(PROTECTED):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {schema}.{table};")

    # Restore revision 030's original (stricter, NULL-inclusive) function body.
    op.execute("""
        CREATE OR REPLACE FUNCTION core.enforce_immutable_columns()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_old  JSONB := to_jsonb(OLD);
            v_new  JSONB := to_jsonb(NEW);
            v_col  TEXT;
        BEGIN
            FOR i IN 0 .. TG_NARGS - 1 LOOP
                v_col := TG_ARGV[i];
                IF v_old -> v_col IS DISTINCT FROM v_new -> v_col THEN
                    RAISE EXCEPTION
                        '%.% is immutable on %.% and cannot be changed once set',
                        TG_TABLE_NAME, v_col, TG_TABLE_SCHEMA, TG_TABLE_NAME
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END LOOP;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.enforce_immutable_columns() IS
        'Generic guard rejecting UPDATEs that change any of the columns named in the '
        'trigger''s arguments. Attach with the protected column names as trigger '
        'arguments, the same shape as core.enforce_entity_subtype(''<pk_column>'').';
    """)
