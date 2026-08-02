"""Seed the initial D&D 5e (2024) ruleset

Revision ID: 022_seed_ruleset
Revises: 021_character_timeline_state
Create Date: 2026-08-02 17:30:00.000000

Purpose:
    Closes Phase 4's "first substantial seed content" first-time obligation
    (docs/PLAN.md): the first seed data with real structure and
    cross-references — skills reference an ability, subclasses and features
    reference a class, spells optionally reference a damage type — rather
    than the flat, single-column-keyed lookups every earlier seed handled.

    Not exhaustive Player's Handbook content. Enough to prove a character
    sheet can actually be assembled from structured data (Phase 4's exit
    criterion): two classes, two species, a subclass and a couple of
    features per class, a handful of spells, and the full fixed vocabularies
    (abilities, skills, damage types, conditions, creature types, languages,
    proficiency types, resource kinds).

Forward migration:
    - One ruleset ("dnd5e_2024") and one current ruleset_version ("2024")
    - Seeds every rules.* content table from database/seeds/*.yaml

Rollback:
    Supported. Deletes every row this revision inserted, scoped to the
    "dnd5e_2024" ruleset — cascades from rules.rulesets take care of
    everything hanging off it.

Data implications:
    The only migration so far whose forward direction is pure data, no DDL.
    Idempotent: every insert is ON CONFLICT DO NOTHING against a unique key,
    so re-running this revision (or seeding an already-seeded database)
    changes nothing.

Locking considerations:
    None beyond ordinary row locks during insert; every table involved is
    new and was empty before this revision ran.

See: docs/PLAN.md Phase 4 first-time obligations ("First substantial seed
     content")
     docs/DATABASE_CONVENTIONS.md §25.4 (seed idempotency)
     database/seeds/rules.*.yaml
"""

from alembic import op
from sqlalchemy import text

from dnd_ai.persistence.seeds import load_seed_data

# revision identifiers, used by Alembic.
revision = "022_seed_ruleset"
down_revision = "021_character_timeline_state"
branch_labels = None
depends_on = None

RULESET_CODE = "dnd5e_2024"
VERSION_LABEL = "2024"


def upgrade() -> None:
    """Apply the migration."""

    bind = op.get_bind()

    # ==========================================================================
    # 1. The ruleset and its current version
    # ==========================================================================
    # ON CONFLICT DO UPDATE (a no-op self-assignment) rather than DO NOTHING,
    # so RETURNING still yields the row's id on a re-run — a bare DO NOTHING
    # returns nothing on the conflict path, which would leave ruleset_id NULL
    # the second time this migration's data is (re-)applied.
    ruleset_id = bind.execute(
        text("""
            INSERT INTO rules.rulesets (code, display_name, description)
            VALUES (:code, 'D&D 5e (2024)', 'The 2024 revision of the fifth-edition rules.')
            ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code
            RETURNING ruleset_id
        """),
        {"code": RULESET_CODE},
    ).scalar()

    ruleset_version_id = bind.execute(
        text("""
            INSERT INTO rules.ruleset_versions
                (ruleset_id, version_label, description, is_current)
            VALUES (:ruleset_id, :label, 'Initial seeded content.', true)
            ON CONFLICT (ruleset_id, version_label)
                DO UPDATE SET version_label = EXCLUDED.version_label
            RETURNING ruleset_version_id
        """),
        {"ruleset_id": ruleset_id, "label": VERSION_LABEL},
    ).scalar()

    # ==========================================================================
    # 2. Flat lookups: abilities, species, damage types, conditions,
    #    creature types, languages, proficiency types, resource definitions
    # ==========================================================================
    # These share one shape (code, display_name, description?) plus the
    # ruleset_version_id resolved above — unlike apply_seed's platform
    # lookups, that value isn't in the YAML itself, so each row is inserted
    # directly rather than through apply_seed.
    for table in (
        "abilities",
        "species",
        "damage_types",
        "conditions",
        "creature_types",
        "languages",
        "proficiency_types",
        "resource_definitions",
    ):
        for row in load_seed_data("rules", table):
            bind.execute(
                text(f"""
                    INSERT INTO rules.{table}
                        (ruleset_version_id, code, display_name, description)
                    VALUES (:v, :code, :display_name, :description)
                    ON CONFLICT (ruleset_version_id, code) DO NOTHING
                """),
                {
                    "v": ruleset_version_id,
                    "code": row["code"],
                    "display_name": row["display_name"],
                    "description": row.get("description"),
                },
            )

    # ==========================================================================
    # 3. Skills — each resolves its governing ability by code
    # ==========================================================================
    for row in load_seed_data("rules", "skills"):
        bind.execute(
            text("""
                INSERT INTO rules.skills
                    (ruleset_version_id, ability_id, code, display_name)
                VALUES (
                    :v,
                    (SELECT ability_id FROM rules.abilities
                     WHERE ruleset_version_id = :v AND code = :ability_code),
                    :code, :display_name
                )
                ON CONFLICT (ruleset_version_id, code) DO NOTHING
            """),
            {
                "v": ruleset_version_id,
                "ability_code": row["ability_code"],
                "code": row["code"],
                "display_name": row["display_name"],
            },
        )

    # ==========================================================================
    # 4. Classes
    # ==========================================================================
    for row in load_seed_data("rules", "classes"):
        bind.execute(
            text("""
                INSERT INTO rules.classes
                    (ruleset_version_id, code, display_name, hit_die, primary_ability_id)
                VALUES (
                    :v, :code, :display_name, :hit_die,
                    (SELECT ability_id FROM rules.abilities
                     WHERE ruleset_version_id = :v AND code = :primary_ability_code)
                )
                ON CONFLICT (ruleset_version_id, code) DO NOTHING
            """),
            {
                "v": ruleset_version_id,
                "code": row["code"],
                "display_name": row["display_name"],
                "hit_die": row["hit_die"],
                "primary_ability_code": row["primary_ability_code"],
            },
        )

    # ==========================================================================
    # 5. Subclasses — resolve their class by code
    # ==========================================================================
    for row in load_seed_data("rules", "subclasses"):
        bind.execute(
            text("""
                INSERT INTO rules.subclasses
                    (class_id, ruleset_version_id, code, display_name)
                VALUES (
                    (SELECT class_id FROM rules.classes
                     WHERE ruleset_version_id = :v AND code = :class_code),
                    :v, :code, :display_name
                )
                ON CONFLICT (class_id, code) DO NOTHING
            """),
            {
                "v": ruleset_version_id,
                "class_code": row["class_code"],
                "code": row["code"],
                "display_name": row["display_name"],
            },
        )

    # ==========================================================================
    # 6. Feats
    # ==========================================================================
    for row in load_seed_data("rules", "feats"):
        bind.execute(
            text("""
                INSERT INTO rules.feats (ruleset_version_id, code, display_name)
                VALUES (:v, :code, :display_name)
                ON CONFLICT (ruleset_version_id, code) DO NOTHING
            """),
            {"v": ruleset_version_id, "code": row["code"], "display_name": row["display_name"]},
        )

    # ==========================================================================
    # 7. Spells — damage_type_code is optional
    # ==========================================================================
    for row in load_seed_data("rules", "spells"):
        bind.execute(
            text("""
                INSERT INTO rules.spells
                    (ruleset_version_id, code, display_name, level, school, damage_type_id)
                VALUES (
                    :v, :code, :display_name, :level, :school,
                    (SELECT damage_type_id FROM rules.damage_types
                     WHERE ruleset_version_id = :v AND code = :damage_type_code)
                )
                ON CONFLICT (ruleset_version_id, code) DO NOTHING
            """),
            {
                "v": ruleset_version_id,
                "code": row["code"],
                "display_name": row["display_name"],
                "level": row["level"],
                "school": row.get("school"),
                "damage_type_code": row.get("damage_type_code"),
            },
        )

    # ==========================================================================
    # 8. Features — resolve class/subclass/species by code; at most one is set
    # ==========================================================================
    for row in load_seed_data("rules", "features"):
        class_code = row.get("class_code")
        subclass_code = row.get("subclass_code")
        species_code = row.get("species_code")
        bind.execute(
            text("""
                INSERT INTO rules.features
                    (ruleset_version_id, class_id, subclass_id, species_id, code,
                     display_name, granted_at_level)
                VALUES (
                    :v,
                    (SELECT class_id FROM rules.classes
                     WHERE ruleset_version_id = :v AND code = :class_code),
                    (SELECT subclass_id FROM rules.subclasses s
                     JOIN rules.classes c ON c.class_id = s.class_id
                     WHERE c.ruleset_version_id = :v AND s.code = :subclass_code),
                    (SELECT species_id FROM rules.species
                     WHERE ruleset_version_id = :v AND code = :species_code),
                    :code, :display_name, :granted_at_level
                )
                ON CONFLICT (ruleset_version_id, code) DO NOTHING
            """),
            {
                "v": ruleset_version_id,
                "class_code": class_code,
                "subclass_code": subclass_code,
                "species_code": species_code,
                "code": row["code"],
                "display_name": row["display_name"],
                "granted_at_level": row.get("granted_at_level"),
            },
        )


def downgrade() -> None:
    """Revert the migration."""

    op.execute("""
        DELETE FROM rules.rulesets WHERE code = 'dnd5e_2024';
    """)
