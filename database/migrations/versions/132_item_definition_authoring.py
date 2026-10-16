"""Add world-owned item definitions, a row version, and generic seed items

Revision ID: 132_item_definition_authoring
Revises: 131_npc_portrayal
Create Date: 2026-10-06 12:00:00.000000

Purpose:
    Phase 15 checkpoint 15.3B-1a (decision D-22 option c). A clean install had zero
    `rules.item_definitions`, so no item instance could be created, and the table had no world
    scope, so a GM's homebrew item would have leaked into every world on the same ruleset.

    This revision (1) adds `owning_world_id` (NULL = ruleset-wide, set = homebrew owned by one
    world), `row_version` and `created_by_user_id` to `rules.item_definitions`; (2) replaces the
    single `(ruleset_version_id, code)` uniqueness with one for ruleset-wide definitions and one
    per owning world; (3) makes `owning_world_id` immutable with `ruleset_version_id`; (4) makes
    an item instance accept only a ruleset-wide definition or one its own world owns; and (5)
    seeds a closed set of generic, unlicensed mundane definitions for the current dnd5e ruleset
    version. This is a documented exception to "rules data is ruleset-wide" (DATABASE_MODEL §8).

Rollback:
    Drops the guard changes and columns. World-owned definitions are deleted (and the downgrade
    fails if an item instance still uses one), and the seeded generic definitions are deleted
    unless an instance references them.
"""

from alembic import op
from sqlalchemy import text

revision = "132_item_definition_authoring"
down_revision = "131_npc_portrayal"
branch_labels = None
depends_on = None

# (code, display name, category, rarity, weight, base cost gp, description)
GENERIC_ITEMS = [
    ("dagger", "Dagger", "weapon", "common", 1, 2, "A short blade for stabbing or throwing."),
    ("club", "Club", "weapon", "common", 2, 0.1, "A simple wooden bludgeon."),
    ("quarterstaff", "Quarterstaff", "weapon", "common", 4, 0.2, "A long wooden staff."),
    ("shortsword", "Shortsword", "weapon", "common", 2, 10, "A light, quick blade."),
    ("longsword", "Longsword", "weapon", "common", 3, 15, "A versatile one-handed blade."),
    ("greataxe", "Greataxe", "weapon", "common", 7, 30, "A heavy two-handed axe."),
    ("shortbow", "Shortbow", "weapon", "common", 2, 25, "A compact bow."),
    ("longbow", "Longbow", "weapon", "common", 2, 50, "A tall bow with long range."),
    ("arrows", "Arrows", "ammunition", "common", 1, 1, "A bundle of arrows."),
    ("leather_armor", "Leather Armor", "armor", "common", 10, 10, "Light, flexible armor."),
    ("chain_shirt", "Chain Shirt", "armor", "common", 20, 50, "A shirt of interlocking rings."),
    ("plate_armor", "Plate Armor", "armor", "common", 65, 1500, "Full articulated plate."),
    ("shield", "Shield", "shield", "common", 6, 10, "A wooden or metal shield."),
    (
        "healing_potion",
        "Healing Potion",
        "potion",
        "common",
        0.5,
        50,
        "A vial that restores health.",
    ),
    ("spell_scroll", "Spell Scroll", "scroll", "uncommon", 0, None, "A scroll holding one spell."),
    ("thieves_tools", "Thieves' Tools", "tool", "common", 1, 25, "Picks and probes for locks."),
    ("backpack", "Backpack", "gear", "common", 5, 2, "A pack for carrying gear."),
    ("rope", "Rope", "gear", "common", 10, 1, "Fifty feet of hempen rope."),
    ("torch", "Torch", "gear", "common", 1, 0.01, "A wooden torch that burns for an hour."),
    ("rations", "Rations", "gear", "common", 2, 0.5, "A day of dried food."),
    ("waterskin", "Waterskin", "gear", "common", 5, 0.2, "A skin for carrying water."),
    ("gem", "Gemstone", "treasure", "common", 0, 50, "A small cut gemstone."),
    ("art_object", "Art Object", "treasure", "common", 1, 250, "A valuable piece of art."),
    ("trinket", "Trinket", "other", "common", 0, 0, "A small curiosity of no clear worth."),
]


def upgrade() -> None:
    op.execute("""
        ALTER TABLE rules.item_definitions
        ADD COLUMN owning_world_id UUID REFERENCES core.worlds(world_id) ON DELETE CASCADE,
        ADD COLUMN row_version BIGINT NOT NULL DEFAULT 1,
        ADD CONSTRAINT ck_item_definitions_row_version_positive CHECK (row_version >= 1),
        ADD COLUMN created_by_user_id UUID
            REFERENCES security.users(user_id) ON DELETE SET NULL;
    """)
    op.execute("""
        COMMENT ON COLUMN rules.item_definitions.owning_world_id IS
        'NULL for a ruleset-wide definition visible to every world on the ruleset; set for a '
        'homebrew definition that only this world can see and use. Immutable. A documented '
        'exception to ruleset-wide rules data (DATABASE_MODEL §8).';
    """)
    op.execute("""
        COMMENT ON COLUMN rules.item_definitions.row_version IS
        'Optimistic-concurrency token, incremented by every UPDATE '
        '(core.bump_row_version()). Authoring commands require the caller''s '
        'expected_row_version to equal it under a row lock and reject a stale write.';
    """)
    op.execute("""
        COMMENT ON COLUMN rules.item_definitions.created_by_user_id IS
        'The authenticated human who authored this homebrew definition; NULL for seeded or '
        'operator-created definitions.';
    """)
    op.execute(
        "ALTER TABLE rules.item_definitions "
        "DROP CONSTRAINT ux_item_definitions_ruleset_version_code;"
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_item_definitions_ruleset_version_code "
        "ON rules.item_definitions (ruleset_version_id, code) WHERE owning_world_id IS NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_item_definitions_world_code "
        "ON rules.item_definitions (owning_world_id, ruleset_version_id, code) "
        "WHERE owning_world_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_item_definitions_created_by_user_id "
        "ON rules.item_definitions (created_by_user_id) WHERE created_by_user_id IS NOT NULL;"
    )
    op.execute("""
        CREATE TRIGGER tr_item_definitions_bump_row_version
        BEFORE UPDATE ON rules.item_definitions
        FOR EACH ROW EXECUTE FUNCTION core.bump_row_version();
    """)
    op.execute("DROP TRIGGER tr_item_definitions_enforce_immutable ON rules.item_definitions;")
    op.execute("""
        CREATE TRIGGER tr_item_definitions_enforce_immutable
        BEFORE UPDATE ON rules.item_definitions
        FOR EACH ROW EXECUTE FUNCTION
            core.enforce_immutable_columns('ruleset_version_id', 'owning_world_id');
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_item_instance_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_world              UUID;
            v_definition_version UUID;
            v_owner              UUID;
        BEGIN
            SELECT world_id INTO v_world
            FROM core.entities WHERE entity_id = NEW.item_instance_id;

            SELECT ruleset_version_id, owning_world_id INTO v_definition_version, v_owner
            FROM rules.item_definitions WHERE item_definition_id = NEW.item_definition_id;

            IF NOT rules.ruleset_allowed_for_world(v_world, v_definition_version) THEN
                RAISE EXCEPTION
                    'Item definition %''s ruleset is not allowed for world % (item instance %''s world)',
                    NEW.item_definition_id, v_world, NEW.item_instance_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF v_owner IS NOT NULL AND v_owner IS DISTINCT FROM v_world THEN
                RAISE EXCEPTION
                    'Item definition % is homebrew owned by another world (item instance %''s world is %)',
                    NEW.item_definition_id, NEW.item_instance_id, v_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)

    bind = op.get_bind()
    insert = text("""
        INSERT INTO rules.item_definitions
            (ruleset_version_id, item_category_id, code, display_name, description, rarity,
             weight, base_cost_gp)
        SELECT rv.ruleset_version_id, ic.item_category_id, :code, :name, :description, :rarity,
               :weight, :cost
        FROM rules.ruleset_versions rv
        JOIN rules.rulesets r ON r.ruleset_id = rv.ruleset_id
        JOIN rules.item_categories ic ON ic.code = :category
        WHERE r.code = 'dnd5e' AND rv.is_current
        ON CONFLICT (ruleset_version_id, code) WHERE owning_world_id IS NULL DO NOTHING
    """)
    for code, name, category, rarity, weight, cost, description in GENERIC_ITEMS:
        bind.execute(
            insert,
            {
                "code": code,
                "name": name,
                "category": category,
                "rarity": rarity,
                "weight": weight,
                "cost": cost,
                "description": description,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DELETE FROM rules.item_definitions WHERE owning_world_id IS NOT NULL"))
    bind.execute(
        text("""
            DELETE FROM rules.item_definitions d
            WHERE d.code = ANY(:codes)
              AND d.created_by_user_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM world.item_instances i
                  WHERE i.item_definition_id = d.item_definition_id
              )
        """),
        {"codes": [item[0] for item in GENERIC_ITEMS]},
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_item_instance_ruleset_allowed()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_world             UUID;
            v_definition_version UUID;
        BEGIN
            SELECT world_id INTO v_world
            FROM core.entities WHERE entity_id = NEW.item_instance_id;

            SELECT ruleset_version_id INTO v_definition_version
            FROM rules.item_definitions WHERE item_definition_id = NEW.item_definition_id;

            IF NOT rules.ruleset_allowed_for_world(v_world, v_definition_version) THEN
                RAISE EXCEPTION
                    'Item definition %''s ruleset is not allowed for world % (item instance %''s world)',
                    NEW.item_definition_id, v_world, NEW.item_instance_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("DROP TRIGGER tr_item_definitions_enforce_immutable ON rules.item_definitions;")
    op.execute("""
        CREATE TRIGGER tr_item_definitions_enforce_immutable
        BEFORE UPDATE ON rules.item_definitions
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns('ruleset_version_id');
    """)
    op.execute("DROP TRIGGER tr_item_definitions_bump_row_version ON rules.item_definitions;")
    op.execute("DROP INDEX rules.ix_item_definitions_created_by_user_id;")
    op.execute("DROP INDEX rules.ux_item_definitions_world_code;")
    op.execute("DROP INDEX rules.ux_item_definitions_ruleset_version_code;")
    op.execute(
        "ALTER TABLE rules.item_definitions ADD CONSTRAINT "
        "ux_item_definitions_ruleset_version_code UNIQUE (ruleset_version_id, code);"
    )
    op.execute("""
        ALTER TABLE rules.item_definitions
        DROP CONSTRAINT ck_item_definitions_row_version_positive,
        DROP COLUMN created_by_user_id,
        DROP COLUMN row_version,
        DROP COLUMN owning_world_id;
    """)
