"""Location hierarchy: world.locations, settlements, buildings

Revision ID: 038_locations
Revises: 037_character_language_ruleset
Create Date: 2026-08-02 18:00:00.000000

Purpose:
    Delivers the base of Phase 5's location domain (docs/PLAN.md §9.1,
    docs/architecture/DATABASE_MODEL.md §9.1):

        core.entities
            -> world.locations
                -> world.settlements
                -> world.buildings
                (-> world.dungeons, world.dungeon_areas: revision 039)

    world.locations is the class-table-inheritance root for every spatial
    entity, containment expressed through a self-referencing
    parent_location_id (DATABASE_MODEL.md §9.1: "world.locations contains a
    nullable parent_location_id for containment. General semantic
    relationships ... use the universal relationship model instead of
    dedicated columns.").

    DOMAIN_MODEL.md §9.1 lists many location "subtypes" (plane, realm,
    continent, nation, region, settlement, district, building, dungeon,
    dungeon area, geographic feature), but DATABASE_MODEL.md's own ER diagram
    (§9) only gives four of them their own CTI table with extra structured
    columns: dungeons, dungeon areas, settlements, and buildings. The rest
    (plane, continent, nation, region, district, geographic_feature) carry no
    documented structured data beyond "is a location" — exactly the situation
    character.characters already solved for character subtypes with no
    dedicated apparatus (a "character"-typed entity needs no npc/player_character
    row). The same pattern is used here: each of those six is registered as
    its own core.entity_types row, a child of 'location', with
    required_subtype_table left NULL. This avoids a parallel
    world.location_types lookup that would just duplicate entity_types.

Forward migration:
    - core.entity_types rows: location (base, required_subtype_table =
      'world.locations'), plane, continent, nation, region, district,
      geographic_feature (leaf types under location, no subtype table),
      settlement, building (leaf types under location, each with its own
      subtype table)
    - world.locations
    - world.enforce_location_parent_world(), a trigger guarding
      parent_location_id against cross-world containment
    - world.settlements
    - world.buildings

Rollback:
    Supported. Drops the two subtype tables, world.locations, the trigger
    function, and the nine entity_types rows.

Data implications:
    Creates nine entity_types rows, no location rows.

Locking considerations:
    None. All tables are new and empty.

Deliberate scoping decisions:
    - world.settlements is deliberately minimal (population only).
      DOMAIN_MODEL.md §9.2 lists government, districts, economy, defenses,
      services, factions, and timeline-specific control/damage state as
      things a settlement "may have" — government and factions are Phase 8
      organization concepts, economy is an intentionally deferred domain
      (DOMAIN_MODEL.md §27), districts are just child locations via
      parent_location_id, and control/damage state is timeline state
      (campaign.location_state, revision 040). Same reasoning Phase 4 used to
      keep character.npcs minimal (docs/PHASE4_VERIFICATION.md, "Deliberate
      Scoping Decisions").
    - world.buildings.building_use is free text, not a lookup. Same reasoning
      as character.character_senses.sense_type (Phase 4): no documented
      controlled vocabulary exists for building uses (tavern, temple, shop,
      warehouse, ...), and inventing one unprompted risks the exact drift the
      Phase 4 pre-phase reconciliation fixed.

See: docs/PLAN.md §9.1 (location hierarchy), Phase 5 deliverables and exit
     criteria
     docs/architecture/DATABASE_MODEL.md §9.1
     docs/DOMAIN_MODEL.md §9.1-9.3
     docs/DATABASE_CONVENTIONS.md §7 (inheritance), §9.5 (same-world consistency)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "038_locations"
down_revision = "037_character_language_ruleset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. core.entity_types rows
    # ==========================================================================
    op.execute("""
        INSERT INTO core.entity_types (code, display_name, required_subtype_table)
        VALUES ('location', 'Location', 'world.locations')
        ON CONFLICT (code) DO NOTHING;
    """)
    for code, display_name in (
        ("plane", "Plane"),
        ("continent", "Continent"),
        ("nation", "Nation"),
        ("region", "Region"),
        ("district", "District"),
        ("geographic_feature", "Geographic Feature"),
    ):
        op.execute(f"""
            INSERT INTO core.entity_types
                (code, display_name, parent_entity_type_id)
            VALUES (
                '{code}', '{display_name}',
                (SELECT entity_type_id FROM core.entity_types WHERE code = 'location')
            )
            ON CONFLICT (code) DO NOTHING;
        """)
    op.execute("""
        INSERT INTO core.entity_types
            (code, display_name, parent_entity_type_id, required_subtype_table)
        VALUES (
            'settlement', 'Settlement',
            (SELECT entity_type_id FROM core.entity_types WHERE code = 'location'),
            'world.settlements'
        )
        ON CONFLICT (code) DO NOTHING;
    """)
    op.execute("""
        INSERT INTO core.entity_types
            (code, display_name, parent_entity_type_id, required_subtype_table)
        VALUES (
            'building', 'Building',
            (SELECT entity_type_id FROM core.entity_types WHERE code = 'location'),
            'world.buildings'
        )
        ON CONFLICT (code) DO NOTHING;
    """)

    # ==========================================================================
    # 2. world.locations
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.locations (
            location_id         UUID PRIMARY KEY
                                REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            parent_location_id  UUID REFERENCES world.locations(location_id) ON DELETE RESTRICT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_locations_not_own_parent
                CHECK (parent_location_id IS DISTINCT FROM location_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.locations IS
        'Class-table-inheritance root for every spatial entity. Containment is '
        'expressed through parent_location_id; general semantic relationships '
        '(adjacency, claims, portals, trade routes, disputed control) use the '
        'universal relationship model instead (docs/architecture/DATABASE_MODEL.md §9.1).';
    """)
    op.execute("""
        COMMENT ON COLUMN world.locations.parent_location_id IS
        'The location this one is contained within, e.g. a building''s settlement, a '
        'settlement''s region. NULL for top-level locations (planes, continents). Must '
        'belong to the same world as this location, enforced by trigger.';
    """)
    op.execute("""
        CREATE TRIGGER tr_locations_set_updated_at
        BEFORE UPDATE ON world.locations
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_locations_parent_location_id "
        "ON world.locations (parent_location_id) WHERE parent_location_id IS NOT NULL;"
    )
    op.execute("""
        CREATE TRIGGER tr_locations_enforce_subtype
        AFTER INSERT OR UPDATE ON world.locations
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('location_id');
    """)

    # Same-world consistency for containment (conventions §9.5): a location and
    # its parent must belong to the same world. Not expressible as a plain FK,
    # so a trigger — same pattern as campaign.enforce_character_state_world.
    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_location_parent_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_own_world    UUID;
            v_parent_world UUID;
        BEGIN
            IF NEW.parent_location_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT world_id INTO v_own_world
            FROM core.entities WHERE entity_id = NEW.location_id;

            SELECT world_id INTO v_parent_world
            FROM core.entities WHERE entity_id = NEW.parent_location_id;

            IF v_own_world IS DISTINCT FROM v_parent_world THEN
                RAISE EXCEPTION
                    'Location % belongs to world %, but parent location % belongs to world %',
                    NEW.location_id, v_own_world, NEW.parent_location_id, v_parent_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_location_parent_world() IS
        'Guards world.locations.parent_location_id: a location and its parent must '
        'belong to the same world (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_locations_enforce_parent_world
        BEFORE INSERT OR UPDATE ON world.locations
        FOR EACH ROW EXECUTE FUNCTION world.enforce_location_parent_world();
    """)

    # ==========================================================================
    # 3. world.settlements
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.settlements (
            settlement_id  UUID PRIMARY KEY
                           REFERENCES world.locations(location_id) ON DELETE CASCADE,
            population     core.nonnegative_integer,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.settlements IS
        'Marks a location as a populated settlement. Deliberately minimal (population '
        'only) — government, factions, and economy are later-phase concepts; districts '
        'are plain child locations; control/damage state is timeline state '
        '(campaign.location_state, revision 040). See this revision''s docstring.';
    """)
    op.execute("""
        CREATE TRIGGER tr_settlements_set_updated_at
        BEFORE UPDATE ON world.settlements
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_settlements_enforce_subtype
        AFTER INSERT OR UPDATE ON world.settlements
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('settlement_id');
    """)

    # ==========================================================================
    # 4. world.buildings
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.buildings (
            building_id   UUID PRIMARY KEY
                          REFERENCES world.locations(location_id) ON DELETE CASCADE,
            building_use  TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.buildings IS
        'Marks a location as a constructed building. building_use is free text '
        '(tavern, temple, shop, warehouse, ...) — no documented controlled vocabulary '
        'exists yet (docs/DOMAIN_MODEL.md §9.3).';
    """)
    op.execute("""
        CREATE TRIGGER tr_buildings_set_updated_at
        BEFORE UPDATE ON world.buildings
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_buildings_enforce_subtype
        AFTER INSERT OR UPDATE ON world.buildings
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('building_id');
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS world.buildings;")
    op.execute("DROP TABLE IF EXISTS world.settlements;")
    op.execute("DROP TABLE IF EXISTS world.locations;")
    op.execute("DROP FUNCTION IF EXISTS world.enforce_location_parent_world();")
    op.execute("""
        DELETE FROM core.entity_types
        WHERE code IN (
            'building', 'settlement', 'geographic_feature', 'district', 'region',
            'nation', 'continent', 'plane', 'location'
        );
    """)
