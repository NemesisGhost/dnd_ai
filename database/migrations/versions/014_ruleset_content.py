"""Ruleset-scoped rule-content lookups

Revision ID: 014_ruleset_content
Revises: 013_rulesets
Create Date: 2026-08-02 13:30:00.000000

Purpose:
    Delivers the rule-content tables from docs/PLAN.md §6.1 that share one
    shape: a ruleset-version-scoped lookup with a stable code, a display
    name, and a description. Every one of these is a case DOMAIN_MODEL.md
    §7.2 names as a rule definition ("rule definitions are not timeline
    entities unless a particular instance becomes relevant in the world").

    rules.skills is the one exception in this revision: it additionally
    names the ability score that governs it, so it is built explicitly
    rather than through the shared loop.

    rules.classes, subclasses, features, feats, and spells are NOT here —
    they cross-reference each other and rules.skills/abilities in ways the
    shared shape does not fit, and are built in the next revision.
    rules.item_definitions is deferred to Phase 9, which owns both item
    definitions and item instances together.

Forward migration:
    - rules.abilities, rules.species, rules.damage_types, rules.conditions,
      rules.creature_types, rules.languages, rules.proficiency_types,
      rules.resource_definitions — identical shape, generated from one loop
    - rules.skills — the above shape plus a governing ability reference

Rollback:
    Supported. Drops all nine tables.

Data implications:
    Creates no rows. Seeded once content for the initial ruleset exists.

Locking considerations:
    None. All tables are new and empty.

See: docs/PLAN.md §6.1 (ruleset separation)
     docs/architecture/DATABASE_MODEL.md §8 (rules model)
     docs/DOMAIN_MODEL.md §7.2 (rule definition catalog)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "014_ruleset_content"
down_revision = "013_rulesets"
branch_labels = None
depends_on = None


# All nine share DATABASE_CONVENTIONS.md §11's lookup shape, scoped to a
# ruleset version rather than global: <table>_id, ruleset_version_id, code,
# display_name, description. Uniqueness is (ruleset_version_id, code) rather
# than a bare UNIQUE(code) — two different rulesets, or two versions of one
# ruleset, may each define a "fire" damage type independently.
RULESET_LOOKUPS = [
    (
        "abilities",
        "ability_id",
        "A scored capability a character has (Strength, Dexterity, ...). Governs skills "
        "and saving throws.",
    ),
    (
        "species",
        "species_id",
        "A playable ancestry (Human, Elf, ...). One of the identity-level references on "
        "character.characters (docs/architecture/DATABASE_MODEL.md §7.1).",
    ),
    (
        "damage_types",
        "damage_type_id",
        "A category of damage (fire, slashing, ...) that resistances, vulnerabilities, "
        "and immunities key off.",
    ),
    (
        "conditions",
        "condition_id",
        "A status a character can be under (poisoned, prone, ...). Definitions only — "
        "campaign.character_conditions (Phase 4 timeline state) tracks who currently has "
        "one.",
    ),
    (
        "creature_types",
        "creature_type_id",
        "A monster-manual classification (beast, fiend, undead, ...), distinct from "
        "species: a character has a species, any character or monster has a creature "
        "type.",
    ),
    (
        "languages",
        "language_id",
        "A language a character can know or speak, referenced by character.character_languages.",
    ),
    (
        "proficiency_types",
        "proficiency_type_id",
        "A category of proficiency (weapon, armor, tool, skill, saving throw) that "
        "character.character_proficiencies rows are typed by.",
    ),
    (
        "resource_definitions",
        "resource_definition_id",
        "A depletable/rechargeable resource kind (spell slot, ki point, rage use, ...). "
        "Definitions only — campaign.character_resources (Phase 4 timeline state) tracks "
        "current and maximum amounts.",
    ),
]


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. The eight identically shaped ruleset-scoped lookups
    # ==========================================================================
    for table, pk, comment in RULESET_LOOKUPS:
        op.execute(f"""
            CREATE TABLE rules.{table} (
                {pk}                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                ruleset_version_id  UUID NOT NULL
                                    REFERENCES rules.ruleset_versions(ruleset_version_id)
                                    ON DELETE CASCADE,
                code                TEXT NOT NULL,
                display_name        TEXT NOT NULL,
                description         TEXT,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ux_{table}_ruleset_version_code UNIQUE (ruleset_version_id, code),
                CONSTRAINT ck_{table}_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
            );
        """)
        op.execute(f"COMMENT ON TABLE rules.{table} IS '{comment}';")
        op.execute(f"""
            CREATE TRIGGER tr_{table}_set_updated_at
            BEFORE UPDATE ON rules.{table}
            FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
        """)
        op.execute(
            f"CREATE INDEX ix_{table}_ruleset_version_id ON rules.{table} (ruleset_version_id);"
        )

    # ==========================================================================
    # 2. rules.skills
    # ==========================================================================
    # Same shape as the loop above, plus the governing ability. A skill and
    # its ability must belong to the same ruleset version — enforced by
    # trigger below, the same class of cross-row guard used throughout this
    # project rather than a CHECK, which cannot compare across tables.
    op.execute("""
        CREATE TABLE rules.skills (
            skill_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ruleset_version_id  UUID NOT NULL
                                REFERENCES rules.ruleset_versions(ruleset_version_id)
                                ON DELETE CASCADE,
            ability_id          UUID NOT NULL
                                REFERENCES rules.abilities(ability_id) ON DELETE RESTRICT,
            code                TEXT NOT NULL,
            display_name        TEXT NOT NULL,
            description         TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_skills_ruleset_version_code UNIQUE (ruleset_version_id, code),
            CONSTRAINT ck_skills_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE rules.skills IS
        'A trained capability governed by one ability (Stealth -> Dexterity, ...).';
    """)
    op.execute("""
        CREATE TRIGGER tr_skills_set_updated_at
        BEFORE UPDATE ON rules.skills
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_skills_ruleset_version_id ON rules.skills (ruleset_version_id);")
    op.execute("CREATE INDEX ix_skills_ability_id ON rules.skills (ability_id);")

    op.execute("""
        CREATE OR REPLACE FUNCTION rules.enforce_skill_ability_ruleset_version()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_ability_version UUID;
        BEGIN
            SELECT ruleset_version_id INTO v_ability_version
            FROM rules.abilities WHERE ability_id = NEW.ability_id;

            IF v_ability_version IS DISTINCT FROM NEW.ruleset_version_id THEN
                RAISE EXCEPTION
                    'Skill % belongs to ruleset version %, but its ability % belongs to '
                    'ruleset version %',
                    NEW.skill_id, NEW.ruleset_version_id, NEW.ability_id, v_ability_version
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION rules.enforce_skill_ability_ruleset_version() IS
        'Keeps a skill''s governing ability in the same ruleset version as the skill.';
    """)
    op.execute("""
        CREATE TRIGGER tr_skills_enforce_ability_ruleset_version
        BEFORE INSERT OR UPDATE ON rules.skills
        FOR EACH ROW EXECUTE FUNCTION rules.enforce_skill_ability_ruleset_version();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS rules.skills;")
    op.execute("DROP FUNCTION IF EXISTS rules.enforce_skill_ability_ruleset_version();")
    for table, _pk, _comment in reversed(RULESET_LOOKUPS):
        op.execute(f"DROP TABLE IF EXISTS rules.{table};")
