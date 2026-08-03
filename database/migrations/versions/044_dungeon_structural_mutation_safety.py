"""Dungeon structural invariants: make them mutation-safe, not just insert-safe

Revision ID: 044_dungeon_mutation_safety
Revises: 043_character_location_temporal
Create Date: 2026-08-03 09:15:00.000000

Purpose:
    Phase 5 exit review finding: revision 039's dungeon-structure triggers
    validate relationships when a row is first inserted (or, for dungeon
    areas, whenever dungeon_areas itself changes), but nothing stopped a
    later UPDATE from moving a structural object's identity columns out from
    under state (revision 040) or knowledge (revision 041) rows that assume
    the original world, or from turning valid containment into a cycle.

    Two different fixes, chosen per the review's own guidance to prefer the
    simpler robust rule already used elsewhere in the schema:

    1. For world.area_connections.from_dungeon_area_id/to_dungeon_area_id and
       world.area_features/area_hazards/area_interactables.dungeon_area_id,
       there is no legitimate "move" operation — a connection joining two
       specific areas, or a feature/hazard/interactable belonging to a
       specific area, is identity, not configuration (the exact reasoning
       revision 030 already used for core.entities.world_id,
       core.world_times.world_id/sort_key, and three other columns). These
       become immutable via the existing generic
       core.enforce_immutable_columns(), reused rather than duplicated.

    2. world.locations.parent_location_id is NOT made immutable — legitimate
       reparenting (moving a building to a different district, say) is a
       real operation the schema should keep supporting. Two new triggers on
       world.locations instead revalidate on every UPDATE of that column:
       one rejects any cycle of any length (not just direct self-parenting,
       which the existing ck_locations_not_own_parent CHECK already covers
       and this trigger subsumes), and one re-runs revision 039's
       dungeon-area-must-have-a-dungeon-parent rule, which previously only
       fired from the dungeon_areas side and never revalidated when a
       dungeon area's parent changed via the locations table directly.

Forward migration:
    - core.enforce_immutable_columns() attached to:
        world.area_connections (from_dungeon_area_id, to_dungeon_area_id)
        world.area_features, .area_hazards, .area_interactables
          (dungeon_area_id)
    - world.enforce_location_no_cycle(), rejecting a containment cycle of
      any length, attached BEFORE INSERT OR UPDATE OF parent_location_id ON
      world.locations
    - world.enforce_dungeon_area_parent_dungeon_on_update(), re-running
      revision 039's dungeon-parent rule whenever a dungeon area's own
      parent_location_id changes via world.locations directly, attached
      BEFORE UPDATE OF parent_location_id ON world.locations

Rollback:
    Supported. Drops all six new triggers and the two new functions.
    core.enforce_immutable_columns() itself is not touched — revision 030
    owns its lifecycle.

Data implications:
    None. No existing rows are affected; these are constraints on future
    writes.

Locking considerations:
    Adding a trigger does not rewrite a table.

See: docs/DATABASE_CONVENTIONS.md §9.5 (same-world consistency)
     database/migrations/versions/030_parent_scope_immutability.py (the
     immutability pattern reused here)
     database/migrations/versions/039_dungeon_structures.py (the rules this
     revision makes mutation-safe)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "044_dungeon_mutation_safety"
down_revision = "043_character_location_temporal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. Immutable identity columns — reuses core.enforce_immutable_columns()
    #    from revision 030 rather than a new mechanism.
    # ==========================================================================
    op.execute("""
        CREATE TRIGGER tr_area_connections_enforce_immutable
        BEFORE UPDATE ON world.area_connections
        FOR EACH ROW EXECUTE FUNCTION
            core.enforce_immutable_columns('from_dungeon_area_id', 'to_dungeon_area_id');
    """)
    op.execute("""
        CREATE TRIGGER tr_area_features_enforce_immutable
        BEFORE UPDATE ON world.area_features
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns('dungeon_area_id');
    """)
    op.execute("""
        CREATE TRIGGER tr_area_hazards_enforce_immutable
        BEFORE UPDATE ON world.area_hazards
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns('dungeon_area_id');
    """)
    op.execute("""
        CREATE TRIGGER tr_area_interactables_enforce_immutable
        BEFORE UPDATE ON world.area_interactables
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns('dungeon_area_id');
    """)

    # ==========================================================================
    # 2. Location containment: reject cycles of any length
    # ==========================================================================
    # Subsumes ck_locations_not_own_parent (revision 038, direct self-parent
    # only) — a cycle where NEW.parent_location_id's own ancestry loops back
    # to NEW.location_id is rejected at any depth, including depth zero
    # (direct self-parenting), by the same check.
    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_location_no_cycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_found BOOLEAN;
        BEGIN
            IF NEW.parent_location_id IS NULL THEN
                RETURN NEW;
            END IF;

            WITH RECURSIVE ancestry AS (
                SELECT l.location_id, l.parent_location_id
                FROM world.locations l
                WHERE l.location_id = NEW.parent_location_id
                UNION ALL
                SELECT l.location_id, l.parent_location_id
                FROM world.locations l
                JOIN ancestry a ON l.location_id = a.parent_location_id
            )
            SELECT EXISTS (
                SELECT 1 FROM ancestry WHERE location_id = NEW.location_id
            ) INTO v_found;

            IF v_found THEN
                RAISE EXCEPTION
                    'Location % cannot be parented under %: % is already an ancestor of '
                    'itself through that chain, which would create a containment cycle',
                    NEW.location_id, NEW.parent_location_id, NEW.location_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_location_no_cycle() IS
        'Walks parent_location_id ancestry from the proposed parent and rejects the '
        'write if it ever reaches this row''s own location_id — a cycle of any length, '
        'not just direct self-parenting.';
    """)
    op.execute("""
        CREATE TRIGGER tr_locations_enforce_no_cycle
        BEFORE INSERT OR UPDATE OF parent_location_id ON world.locations
        FOR EACH ROW EXECUTE FUNCTION world.enforce_location_no_cycle();
    """)

    # ==========================================================================
    # 3. Re-run the dungeon-parent rule when a dungeon area's parent changes
    # ==========================================================================
    # world.enforce_dungeon_area_parent_dungeon() (revision 039) only fires
    # from world.dungeon_areas itself, so it never re-validates when
    # parent_location_id is updated directly on world.locations for a row
    # that happens to be a dungeon area. This closes that gap without
    # touching revision 039.
    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_dungeon_area_parent_dungeon_on_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_is_dungeon_area    BOOLEAN;
            v_parent_type_code   TEXT;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM world.dungeon_areas WHERE dungeon_area_id = NEW.location_id
            ) INTO v_is_dungeon_area;

            IF NOT v_is_dungeon_area THEN
                RETURN NEW;
            END IF;

            IF NEW.parent_location_id IS NULL THEN
                RAISE EXCEPTION
                    'Dungeon area %''s parent_location_id cannot be cleared — every '
                    'dungeon area must belong to a dungeon',
                    NEW.location_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT et.code INTO v_parent_type_code
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = NEW.parent_location_id;

            IF v_parent_type_code IS DISTINCT FROM 'dungeon' THEN
                RAISE EXCEPTION
                    'Dungeon area % parent location % is of type %, not dungeon',
                    NEW.location_id, NEW.parent_location_id, v_parent_type_code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_dungeon_area_parent_dungeon_on_update() IS
        'Re-runs revision 039''s dungeon-area-must-have-a-dungeon-parent rule whenever '
        'parent_location_id changes on a row that already has a world.dungeon_areas '
        'row, closing the gap left by that revision''s trigger only firing from the '
        'dungeon_areas side.';
    """)
    op.execute("""
        CREATE TRIGGER tr_locations_enforce_dungeon_area_parent_on_update
        BEFORE UPDATE OF parent_location_id ON world.locations
        FOR EACH ROW EXECUTE FUNCTION world.enforce_dungeon_area_parent_dungeon_on_update();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute(
        "DROP TRIGGER IF EXISTS tr_locations_enforce_dungeon_area_parent_on_update "
        "ON world.locations;"
    )
    op.execute("DROP FUNCTION IF EXISTS world.enforce_dungeon_area_parent_dungeon_on_update();")

    op.execute("DROP TRIGGER IF EXISTS tr_locations_enforce_no_cycle ON world.locations;")
    op.execute("DROP FUNCTION IF EXISTS world.enforce_location_no_cycle();")

    op.execute(
        "DROP TRIGGER IF EXISTS tr_area_interactables_enforce_immutable "
        "ON world.area_interactables;"
    )
    op.execute("DROP TRIGGER IF EXISTS tr_area_hazards_enforce_immutable ON world.area_hazards;")
    op.execute("DROP TRIGGER IF EXISTS tr_area_features_enforce_immutable ON world.area_features;")
    op.execute(
        "DROP TRIGGER IF EXISTS tr_area_connections_enforce_immutable ON world.area_connections;"
    )
