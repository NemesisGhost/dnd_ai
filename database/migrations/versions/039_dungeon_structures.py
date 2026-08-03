"""Dungeon structures: dungeons, areas, connections, features, hazards, interactables

Revision ID: 039_dungeon_structures
Revises: 038_locations
Create Date: 2026-08-02 18:15:00.000000

Purpose:
    Delivers the dungeon structural model from docs/PLAN.md §9.2 and
    docs/architecture/DATABASE_MODEL.md §9.2:

        world.locations
            -> world.dungeons
            -> world.dungeon_areas
                -> world.area_connections (from/to)
                -> world.area_features
                -> world.area_hazards
                -> world.area_interactables

    Dungeons and dungeon areas are locations (class-table inheritance, per
    revision 038's root) — the ER diagram in DATABASE_MODEL.md §9 shows
    WORLD_LOCATIONS ||--o| WORLD_DUNGEON_AREAS. Connections, features,
    hazards, and interactables are NOT entities: the same diagram shows them
    as plain children of WORLD_DUNGEON_AREAS with no CORE_ENTITIES edge. They
    are structural/mechanical children of an area, not independently
    identified world objects (modeling principle 5: "important world objects
    use a shared entity identity" — a lever or a bloodstain is not one of
    those in the way an NPC or a dungeon is).

    docs/architecture/DATABASE_MODEL.md §9.3 / docs/DATABASE_CONVENTIONS.md
    §15.1 apply here directly: "A hidden feature exists independently of
    whether a party knows about it. Do not store is_discovered as a global
    property." Each of area_connections/area_features/area_hazards carries an
    is_hidden column — a structural fact about the OBJECT (this door was
    built to be concealed) — never an is_discovered column, which would be a
    fact about a PARTY's knowledge and belongs in the knowledge domain
    (revision 041).

Forward migration:
    - core.entity_types rows: dungeon, dungeon_area (children of 'location',
      each with its own subtype table)
    - world.dungeons
    - world.dungeon_areas
    - world.enforce_dungeon_area_parent_dungeon(), a trigger requiring every
      dungeon area's parent_location_id to point at a 'dungeon'-typed location
    - world.connection_types (lookup: door, secret_door, passage, portal,
      stair, ladder, pit, bridge, teleportation_link), seeded
    - world.area_connections, with world.enforce_area_connection_world()
      guarding cross-world links (deliberately NOT a same-dungeon check —
      teleportation links crossing dungeons are a named use case in
      docs/DOMAIN_MODEL.md §9.6)
    - world.area_features
    - world.area_hazards
    - world.area_interactables

Rollback:
    Supported. Drops the four area-child tables, world.dungeon_areas,
    world.dungeons, both trigger functions, the connection_types lookup, and
    the two entity_types rows.

Data implications:
    Creates entity_types rows and seeds world.connection_types. No location
    or dungeon rows.

Locking considerations:
    None. All tables are new and empty.

Deliberate scoping decisions:
    - world.area_spawn_definitions (named in PLAN.md §9.2 and
      DATABASE_MODEL.md §9.2) is deliberately NOT built here. No creature
      instance or stat-block model exists anywhere in this schema yet —
      rules.creature_types is a bare classification lookup, not a stat
      block — and Phase 9 ("Items, inventory, encounters, and Foundry
      synchronization") is what actually owns encounters and would be the
      natural first consumer of spawn definitions. Building the table now
      would either reference nothing meaningful or invent encounter-generation
      scope ahead of the phase that needs it. None of Phase 5's three exit
      criteria (navigate a dungeon, keep hidden connections distinct from
      party knowledge, alter dungeon state) require it.
    - area_type, dimensions, environmental_properties (dungeon_areas),
      feature_type/hazard_type/interactable_type are free text, not lookups,
      following the same reasoning as revision 038's building_use and Phase
      4's character_senses.sense_type: docs/DOMAIN_MODEL.md §9.5-9.9 give
      examples, not a controlled vocabulary.

See: docs/PLAN.md §9.2 (dungeon structures)
     docs/architecture/DATABASE_MODEL.md §9.2
     docs/DOMAIN_MODEL.md §9.4-9.9
     docs/DATABASE_CONVENTIONS.md §9.5 (same-world consistency), §15.1
     (knowledge is not a boolean)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "039_dungeon_structures"
down_revision = "038_locations"
branch_labels = None
depends_on = None

CONNECTION_TYPES = [
    ("door", "Door"),
    ("secret_door", "Secret Door"),
    ("passage", "Passage"),
    ("portal", "Portal"),
    ("stair", "Stair"),
    ("ladder", "Ladder"),
    ("pit", "Pit"),
    ("bridge", "Bridge"),
    ("teleportation_link", "Teleportation Link"),
]


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. core.entity_types rows
    # ==========================================================================
    op.execute("""
        INSERT INTO core.entity_types
            (code, display_name, parent_entity_type_id, required_subtype_table)
        VALUES (
            'dungeon', 'Dungeon',
            (SELECT entity_type_id FROM core.entity_types WHERE code = 'location'),
            'world.dungeons'
        )
        ON CONFLICT (code) DO NOTHING;
    """)
    op.execute("""
        INSERT INTO core.entity_types
            (code, display_name, parent_entity_type_id, required_subtype_table)
        VALUES (
            'dungeon_area', 'Dungeon Area',
            (SELECT entity_type_id FROM core.entity_types WHERE code = 'location'),
            'world.dungeon_areas'
        )
        ON CONFLICT (code) DO NOTHING;
    """)

    # ==========================================================================
    # 2. world.dungeons
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.dungeons (
            dungeon_id    UUID PRIMARY KEY
                         REFERENCES world.locations(location_id) ON DELETE CASCADE,
            danger_level  core.rating_1_10,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.dungeons IS
        'Marks a location as a dungeon: a location composed of connected areas and '
        'stateful gameplay elements (docs/DOMAIN_MODEL.md §9.4). danger_level is an '
        'optional GM-facing difficulty rating.';
    """)
    op.execute("""
        CREATE TRIGGER tr_dungeons_set_updated_at
        BEFORE UPDATE ON world.dungeons
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_dungeons_enforce_subtype
        AFTER INSERT OR UPDATE ON world.dungeons
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('dungeon_id');
    """)

    # ==========================================================================
    # 3. world.dungeon_areas
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.dungeon_areas (
            dungeon_area_id            UUID PRIMARY KEY
                                       REFERENCES world.locations(location_id) ON DELETE CASCADE,
            area_type                  TEXT,
            dimensions                 TEXT,
            environmental_properties   TEXT,
            created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.dungeon_areas IS
        'A room, chamber, corridor, platform, cavern, or similar navigable unit '
        '(docs/DOMAIN_MODEL.md §9.5). Parent dungeon is expressed through '
        'world.locations.parent_location_id, required to be a dungeon-typed location '
        'by trigger.';
    """)
    op.execute("""
        COMMENT ON COLUMN world.dungeon_areas.dimensions IS
        'Free-text size description (e.g. "30 ft by 40 ft"). No structured unit system '
        'exists yet.';
    """)
    op.execute("""
        CREATE TRIGGER tr_dungeon_areas_set_updated_at
        BEFORE UPDATE ON world.dungeon_areas
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_dungeon_areas_enforce_subtype
        AFTER INSERT OR UPDATE ON world.dungeon_areas
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('dungeon_area_id');
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_dungeon_area_parent_dungeon()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_parent_location_id  UUID;
            v_parent_type_code    TEXT;
        BEGIN
            SELECT parent_location_id INTO v_parent_location_id
            FROM world.locations WHERE location_id = NEW.dungeon_area_id;

            IF v_parent_location_id IS NULL THEN
                RAISE EXCEPTION
                    'Dungeon area % has no parent_location_id — every dungeon area '
                    'must belong to a dungeon',
                    NEW.dungeon_area_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT et.code INTO v_parent_type_code
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = v_parent_location_id;

            IF v_parent_type_code IS DISTINCT FROM 'dungeon' THEN
                RAISE EXCEPTION
                    'Dungeon area % parent location % is of type %, not dungeon',
                    NEW.dungeon_area_id, v_parent_location_id, v_parent_type_code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_dungeon_area_parent_dungeon() IS
        'Requires a dungeon area''s world.locations.parent_location_id to reference a '
        'dungeon-typed location. Checked here rather than in world.locations itself '
        'since the rule is specific to the dungeon_area subtype.';
    """)
    op.execute("""
        CREATE TRIGGER tr_dungeon_areas_enforce_parent_dungeon
        AFTER INSERT OR UPDATE ON world.dungeon_areas
        FOR EACH ROW EXECUTE FUNCTION world.enforce_dungeon_area_parent_dungeon();
    """)

    # ==========================================================================
    # 4. world.connection_types (lookup)
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.connection_types (
            connection_type_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code                TEXT NOT NULL,
            display_name        TEXT NOT NULL,
            description         TEXT,
            sort_order          core.nonnegative_integer NOT NULL DEFAULT 0,
            is_active           BOOLEAN NOT NULL DEFAULT true,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_connection_types_code UNIQUE (code),
            CONSTRAINT ck_connection_types_code_length CHECK (char_length(code) <= 100),
            CONSTRAINT ck_connection_types_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.connection_types IS
        'Kinds of link between two dungeon areas (door, secret door, passage, portal, '
        'stair, ladder, pit, bridge, teleportation link) — docs/DOMAIN_MODEL.md §9.6.';
    """)
    op.execute("""
        COMMENT ON COLUMN world.connection_types.code IS
        'Stable machine-readable identifier. Application logic may reference '
        'codes, but foreign keys use IDs (conventions §11.1).';
    """)
    op.execute("""
        CREATE TRIGGER tr_connection_types_set_updated_at
        BEFORE UPDATE ON world.connection_types
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    for sort_order, (code, display_name) in enumerate(CONNECTION_TYPES):
        op.execute(f"""
            INSERT INTO world.connection_types (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    # ==========================================================================
    # 5. world.area_connections
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.area_connections (
            area_connection_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            from_dungeon_area_id  UUID NOT NULL
                                  REFERENCES world.dungeon_areas(dungeon_area_id)
                                  ON DELETE CASCADE,
            to_dungeon_area_id    UUID NOT NULL
                                  REFERENCES world.dungeon_areas(dungeon_area_id)
                                  ON DELETE CASCADE,
            connection_type_id    UUID NOT NULL
                                  REFERENCES world.connection_types(connection_type_id)
                                  ON DELETE RESTRICT,
            is_one_way            BOOLEAN NOT NULL DEFAULT false,
            is_hidden             BOOLEAN NOT NULL DEFAULT false,
            description            TEXT,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_area_connections_not_self_linked
                CHECK (from_dungeon_area_id IS DISTINCT FROM to_dungeon_area_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.area_connections IS
        'A link between two dungeon areas (docs/DOMAIN_MODEL.md §9.6). Not an entity — '
        'a structural child of the areas it joins. is_hidden is a fact about the '
        'connection itself (built to be concealed), never about whether any party has '
        'found it — party knowledge is tracked separately (docs/architecture/'
        'DATABASE_MODEL.md §9.3, revision 041).';
    """)
    op.execute("""
        COMMENT ON COLUMN world.area_connections.is_one_way IS
        'True for a connection traversable only from from_dungeon_area_id to '
        'to_dungeon_area_id (a one-way chute, a collapsing bridge behind the party, ...).';
    """)
    op.execute("""
        CREATE TRIGGER tr_area_connections_set_updated_at
        BEFORE UPDATE ON world.area_connections
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_area_connections_from_dungeon_area_id "
        "ON world.area_connections (from_dungeon_area_id);"
    )
    op.execute(
        "CREATE INDEX ix_area_connections_to_dungeon_area_id "
        "ON world.area_connections (to_dungeon_area_id);"
    )
    op.execute(
        "CREATE INDEX ix_area_connections_connection_type_id "
        "ON world.area_connections (connection_type_id);"
    )

    # Same-world consistency (conventions §9.5). Deliberately NOT a same-dungeon
    # check: a teleportation_link connecting areas in two different dungeons is
    # a named use case (docs/DOMAIN_MODEL.md §9.6), so only the world must agree.
    op.execute("""
        CREATE OR REPLACE FUNCTION world.enforce_area_connection_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_from_world  UUID;
            v_to_world    UUID;
        BEGIN
            SELECT world_id INTO v_from_world
            FROM core.entities WHERE entity_id = NEW.from_dungeon_area_id;

            SELECT world_id INTO v_to_world
            FROM core.entities WHERE entity_id = NEW.to_dungeon_area_id;

            IF v_from_world IS DISTINCT FROM v_to_world THEN
                RAISE EXCEPTION
                    'Area connection links dungeon areas from different worlds (% and %)',
                    v_from_world, v_to_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION world.enforce_area_connection_world() IS
        'Guards world.area_connections: the two linked dungeon areas must belong to '
        'the same world (conventions §9.5). Same-dungeon is deliberately NOT enforced — '
        'teleportation links may cross dungeons.';
    """)
    op.execute("""
        CREATE TRIGGER tr_area_connections_enforce_world
        BEFORE INSERT OR UPDATE ON world.area_connections
        FOR EACH ROW EXECUTE FUNCTION world.enforce_area_connection_world();
    """)

    # ==========================================================================
    # 6. world.area_features
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.area_features (
            area_feature_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            dungeon_area_id  UUID NOT NULL
                             REFERENCES world.dungeon_areas(dungeon_area_id) ON DELETE CASCADE,
            feature_type     TEXT,
            description      TEXT,
            is_hidden        BOOLEAN NOT NULL DEFAULT false,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.area_features IS
        'A notable but not necessarily interactive part of an area — mural, blood '
        'trail, altar, broken machinery, drag marks, statue (docs/DOMAIN_MODEL.md §9.7). '
        'Not an entity. is_hidden is a fact about the feature itself, never party '
        'knowledge (see world.area_connections comment).';
    """)
    op.execute("""
        CREATE TRIGGER tr_area_features_set_updated_at
        BEFORE UPDATE ON world.area_features
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_area_features_dungeon_area_id ON world.area_features (dungeon_area_id);"
    )

    # ==========================================================================
    # 7. world.area_hazards
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.area_hazards (
            area_hazard_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            dungeon_area_id  UUID NOT NULL
                             REFERENCES world.dungeon_areas(dungeon_area_id) ON DELETE CASCADE,
            hazard_type      TEXT,
            description      TEXT,
            severity         core.rating_1_10,
            is_hidden        BOOLEAN NOT NULL DEFAULT false,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.area_hazards IS
        'A dangerous environmental object or condition — trap, collapsing floor, '
        'electrical arc, poisonous gas, magical ward (docs/DOMAIN_MODEL.md §9.8). Not '
        'an entity. is_hidden is a fact about the hazard itself, never party knowledge '
        '(see world.area_connections comment).';
    """)
    op.execute("""
        CREATE TRIGGER tr_area_hazards_set_updated_at
        BEFORE UPDATE ON world.area_hazards
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_area_hazards_dungeon_area_id ON world.area_hazards (dungeon_area_id);"
    )

    # ==========================================================================
    # 8. world.area_interactables
    # ==========================================================================
    op.execute("""
        CREATE TABLE world.area_interactables (
            area_interactable_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            dungeon_area_id       UUID NOT NULL
                                  REFERENCES world.dungeon_areas(dungeon_area_id)
                                  ON DELETE CASCADE,
            interactable_type      TEXT,
            description            TEXT,
            is_hidden              BOOLEAN NOT NULL DEFAULT false,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.area_interactables IS
        'An object or mechanism intended to receive actions — lever, control panel, '
        'lock, pylon, puzzle component, sealed hatch (docs/DOMAIN_MODEL.md §9.9). Not '
        'an entity. is_hidden is a fact about the interactable itself, never party '
        'knowledge (see world.area_connections comment).';
    """)
    op.execute("""
        CREATE TRIGGER tr_area_interactables_set_updated_at
        BEFORE UPDATE ON world.area_interactables
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_area_interactables_dungeon_area_id "
        "ON world.area_interactables (dungeon_area_id);"
    )


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS world.area_interactables;")
    op.execute("DROP TABLE IF EXISTS world.area_hazards;")
    op.execute("DROP TABLE IF EXISTS world.area_features;")
    op.execute("DROP TABLE IF EXISTS world.area_connections;")
    op.execute("DROP FUNCTION IF EXISTS world.enforce_area_connection_world();")
    op.execute("DROP TABLE IF EXISTS world.connection_types;")
    op.execute(
        "DROP TRIGGER IF EXISTS tr_dungeon_areas_enforce_parent_dungeon ON world.dungeon_areas;"
    )
    op.execute("DROP FUNCTION IF EXISTS world.enforce_dungeon_area_parent_dungeon();")
    op.execute("DROP TABLE IF EXISTS world.dungeon_areas;")
    op.execute("DROP TABLE IF EXISTS world.dungeons;")
    op.execute("DELETE FROM core.entity_types WHERE code IN ('dungeon_area', 'dungeon');")
