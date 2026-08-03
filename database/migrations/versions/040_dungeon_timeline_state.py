"""Dungeon timeline state: location, connection, feature, hazard, interactable state

Revision ID: 040_dungeon_timeline_state
Revises: 039_dungeon_structures
Create Date: 2026-08-02 18:30:00.000000

Purpose:
    Delivers the five typed timeline-state tables docs/PLAN.md §9.3 and
    docs/architecture/DATABASE_MODEL.md §17 name for the location/dungeon
    domain:

        campaign.location_state
        campaign.area_connection_state
        campaign.area_feature_state
        campaign.hazard_state
        campaign.interactable_state

    Same situation Phase 4 faced with character timeline state (revision
    021): DATABASE_MODEL.md §17's general shape calls for
    effective_from_event_id/effective_to_event_id, but narrative.events does
    not exist until Phase 6. Each table here is a single mutable current row
    per (timeline, target), enforced by its primary key — not a gap, the
    correct shape for this phase (see revision 021's docstring for the full
    reasoning, which applies unchanged here).

    Each state table's "status" column is a small lookup rather than a bare
    TEXT/CHECK, matching the connection/hazard/interactable examples
    DATABASE_MODEL.md §17 gives verbatim ("door open/closed/locked/broken/
    destroyed"; "trap armed/triggered/reset/bypassed/disarmed") — these are
    genuinely extensible vocabularies (a GM might add a status), unlike
    character.characters.size_category, which is fixed across editions.

Forward migration:
    - campaign.location_state (is_searched, is_destroyed, alarm_level,
      condition_notes) plus campaign.enforce_location_state_world()
    - campaign.connection_statuses (lookup: open, closed, locked, broken,
      destroyed), seeded
    - campaign.area_connection_state plus
      campaign.enforce_area_connection_state_world()
    - campaign.area_feature_state (is_destroyed, condition_notes) plus
      campaign.enforce_area_feature_state_world()
    - campaign.hazard_statuses (lookup: armed, triggered, reset, bypassed,
      disarmed), seeded
    - campaign.hazard_state plus campaign.enforce_hazard_state_world()
    - campaign.interactable_statuses (lookup: active, inactive, activated,
      deactivated, broken, locked), seeded
    - campaign.interactable_state plus
      campaign.enforce_interactable_state_world()

Rollback:
    Supported. Drops all five state tables, their five trigger functions, and
    the three status lookups (with their seed rows).

Data implications:
    Seeds three small lookups. No state rows.

Locking considerations:
    None. All tables are new and empty.

Deliberate scoping decisions:
    - One trigger function per table rather than one shared function (unlike
      revision 021's single campaign.enforce_character_state_world() for all
      three character-state tables). Each target here reaches world_id
      through a different join path (a location is itself entity-rooted; a
      connection/feature/hazard/interactable reaches world_id through its
      dungeon area), so a single shared function would need per-table
      branching that is harder to read than five short functions.
    - "Alarm level" (a DATABASE_MODEL.md §17 example) is modeled on
      campaign.location_state rather than per-interactable, since an alarm is
      naturally a property of an area/dungeon as a whole, not any single
      mechanism that might trigger it.

See: docs/PLAN.md §9.3 (dungeon timeline state)
     docs/architecture/DATABASE_MODEL.md §17 (typed timeline state)
     docs/DATABASE_CONVENTIONS.md §13 (timeline-state conventions)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "040_dungeon_timeline_state"
down_revision = "039_dungeon_structures"
branch_labels = None
depends_on = None

CONNECTION_STATUSES = [
    ("open", "Open"),
    ("closed", "Closed"),
    ("locked", "Locked"),
    ("broken", "Broken"),
    ("destroyed", "Destroyed"),
]

HAZARD_STATUSES = [
    ("armed", "Armed"),
    ("triggered", "Triggered"),
    ("reset", "Reset"),
    ("bypassed", "Bypassed"),
    ("disarmed", "Disarmed"),
]

INTERACTABLE_STATUSES = [
    ("active", "Active"),
    ("inactive", "Inactive"),
    ("activated", "Activated"),
    ("deactivated", "Deactivated"),
    ("broken", "Broken"),
    ("locked", "Locked"),
]


def _lookup_table(schema: str, table: str, pk: str, comment: str) -> None:
    op.execute(f"""
        CREATE TABLE {schema}.{table} (
            {pk}          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code          TEXT NOT NULL,
            display_name  TEXT NOT NULL,
            description   TEXT,
            sort_order    core.nonnegative_integer NOT NULL DEFAULT 0,
            is_active     BOOLEAN NOT NULL DEFAULT true,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_{table}_code UNIQUE (code),
            CONSTRAINT ck_{table}_code_length CHECK (char_length(code) <= 100),
            CONSTRAINT ck_{table}_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute(f"COMMENT ON TABLE {schema}.{table} IS '{comment}';")
    op.execute(f"""
        COMMENT ON COLUMN {schema}.{table}.code IS
        'Stable machine-readable identifier. Application logic may reference '
        'codes, but foreign keys use IDs (conventions §11.1).';
    """)
    op.execute(f"""
        CREATE TRIGGER tr_{table}_set_updated_at
        BEFORE UPDATE ON {schema}.{table}
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. campaign.location_state
    # ==========================================================================
    op.execute("""
        CREATE TABLE campaign.location_state (
            timeline_id       UUID NOT NULL
                              REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            location_id       UUID NOT NULL
                              REFERENCES world.locations(location_id) ON DELETE CASCADE,
            is_searched       BOOLEAN NOT NULL DEFAULT false,
            is_destroyed      BOOLEAN NOT NULL DEFAULT false,
            alarm_level       core.nonnegative_integer NOT NULL DEFAULT 0,
            condition_notes   TEXT,
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (timeline_id, location_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.location_state IS
        'Current per-timeline condition of a location: searched, destroyed, alarm '
        'level, free-text notes (e.g. "flooded", "smoldering ruins"). One row per '
        '(timeline, location) — see this revision''s docstring on event linkage.';
    """)
    op.execute(
        "CREATE INDEX ix_location_state_location_id ON campaign.location_state (location_id);"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_location_state_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world  UUID;
            v_location_world  UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT world_id INTO v_location_world
            FROM core.entities WHERE entity_id = NEW.location_id;

            IF v_location_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Location % belongs to world %, but timeline % belongs to world %',
                    NEW.location_id, v_location_world, NEW.timeline_id, v_timeline_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_location_state_world() IS
        'World-agreement guard for campaign.location_state: the location must belong '
        'to the timeline''s world.';
    """)
    op.execute("""
        CREATE TRIGGER tr_location_state_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.location_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_location_state_world();
    """)

    # ==========================================================================
    # 2. campaign.connection_statuses + campaign.area_connection_state
    # ==========================================================================
    _lookup_table(
        "campaign",
        "connection_statuses",
        "connection_status_id",
        "Current condition of an area connection (open, closed, locked, broken, "
        "destroyed) — docs/architecture/DATABASE_MODEL.md §17.",
    )
    for sort_order, (code, display_name) in enumerate(CONNECTION_STATUSES):
        op.execute(f"""
            INSERT INTO campaign.connection_statuses (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    op.execute("""
        CREATE TABLE campaign.area_connection_state (
            timeline_id            UUID NOT NULL
                                   REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            area_connection_id     UUID NOT NULL
                                   REFERENCES world.area_connections(area_connection_id)
                                   ON DELETE CASCADE,
            connection_status_id   UUID NOT NULL
                                   REFERENCES campaign.connection_statuses(connection_status_id)
                                   ON DELETE RESTRICT,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (timeline_id, area_connection_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.area_connection_state IS
        'Current per-timeline condition of an area connection. Deliberately separate '
        'from whether any party has discovered the connection exists — that is '
        'knowledge state (docs/architecture/DATABASE_MODEL.md §9.3, revision 041), '
        'never stored here.';
    """)
    op.execute(
        "CREATE INDEX ix_area_connection_state_area_connection_id "
        "ON campaign.area_connection_state (area_connection_id);"
    )
    op.execute(
        "CREATE INDEX ix_area_connection_state_connection_status_id "
        "ON campaign.area_connection_state (connection_status_id);"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_area_connection_state_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world    UUID;
            v_connection_world  UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT e.world_id INTO v_connection_world
            FROM world.area_connections ac
            JOIN core.entities e ON e.entity_id = ac.from_dungeon_area_id
            WHERE ac.area_connection_id = NEW.area_connection_id;

            IF v_connection_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Area connection % belongs to world %, but timeline % belongs to world %',
                    NEW.area_connection_id, v_connection_world, NEW.timeline_id, v_timeline_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_area_connection_state_world() IS
        'World-agreement guard for campaign.area_connection_state. Uses the '
        'connection''s from_dungeon_area_id to resolve its world — '
        'world.enforce_area_connection_world() already guarantees from/to agree.';
    """)
    op.execute("""
        CREATE TRIGGER tr_area_connection_state_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.area_connection_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_area_connection_state_world();
    """)

    # ==========================================================================
    # 3. campaign.area_feature_state
    # ==========================================================================
    op.execute("""
        CREATE TABLE campaign.area_feature_state (
            timeline_id       UUID NOT NULL
                              REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            area_feature_id   UUID NOT NULL
                              REFERENCES world.area_features(area_feature_id) ON DELETE CASCADE,
            is_destroyed      BOOLEAN NOT NULL DEFAULT false,
            condition_notes   TEXT,
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (timeline_id, area_feature_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.area_feature_state IS
        'Current per-timeline condition of an area feature (defaced, destroyed, '
        'altered) — never whether a party has noticed it (revision 041).';
    """)
    op.execute(
        "CREATE INDEX ix_area_feature_state_area_feature_id "
        "ON campaign.area_feature_state (area_feature_id);"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_area_feature_state_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world  UUID;
            v_feature_world   UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT e.world_id INTO v_feature_world
            FROM world.area_features af
            JOIN core.entities e ON e.entity_id = af.dungeon_area_id
            WHERE af.area_feature_id = NEW.area_feature_id;

            IF v_feature_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Area feature % belongs to world %, but timeline % belongs to world %',
                    NEW.area_feature_id, v_feature_world, NEW.timeline_id, v_timeline_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_area_feature_state_world() IS
        'World-agreement guard for campaign.area_feature_state.';
    """)
    op.execute("""
        CREATE TRIGGER tr_area_feature_state_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.area_feature_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_area_feature_state_world();
    """)

    # ==========================================================================
    # 4. campaign.hazard_statuses + campaign.hazard_state
    # ==========================================================================
    _lookup_table(
        "campaign",
        "hazard_statuses",
        "hazard_status_id",
        "Current status of a hazard (armed, triggered, reset, bypassed, disarmed) — "
        "docs/architecture/DATABASE_MODEL.md §17.",
    )
    for sort_order, (code, display_name) in enumerate(HAZARD_STATUSES):
        op.execute(f"""
            INSERT INTO campaign.hazard_statuses (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    op.execute("""
        CREATE TABLE campaign.hazard_state (
            timeline_id        UUID NOT NULL
                               REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            area_hazard_id     UUID NOT NULL
                               REFERENCES world.area_hazards(area_hazard_id) ON DELETE CASCADE,
            hazard_status_id   UUID NOT NULL
                               REFERENCES campaign.hazard_statuses(hazard_status_id)
                               ON DELETE RESTRICT,
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (timeline_id, area_hazard_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.hazard_state IS
        'Current per-timeline status of a hazard. Separate from whether any party '
        'knows the hazard exists (revision 041).';
    """)
    op.execute(
        "CREATE INDEX ix_hazard_state_area_hazard_id ON campaign.hazard_state (area_hazard_id);"
    )
    op.execute(
        "CREATE INDEX ix_hazard_state_hazard_status_id ON campaign.hazard_state (hazard_status_id);"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_hazard_state_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world  UUID;
            v_hazard_world    UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT e.world_id INTO v_hazard_world
            FROM world.area_hazards ah
            JOIN core.entities e ON e.entity_id = ah.dungeon_area_id
            WHERE ah.area_hazard_id = NEW.area_hazard_id;

            IF v_hazard_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Area hazard % belongs to world %, but timeline % belongs to world %',
                    NEW.area_hazard_id, v_hazard_world, NEW.timeline_id, v_timeline_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_hazard_state_world() IS
        'World-agreement guard for campaign.hazard_state.';
    """)
    op.execute("""
        CREATE TRIGGER tr_hazard_state_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.hazard_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_hazard_state_world();
    """)

    # ==========================================================================
    # 5. campaign.interactable_statuses + campaign.interactable_state
    # ==========================================================================
    _lookup_table(
        "campaign",
        "interactable_statuses",
        "interactable_status_id",
        "Current status of an interactable (active, inactive, activated, "
        "deactivated, broken, locked) — docs/architecture/DATABASE_MODEL.md §17.",
    )
    for sort_order, (code, display_name) in enumerate(INTERACTABLE_STATUSES):
        op.execute(f"""
            INSERT INTO campaign.interactable_statuses (code, display_name, sort_order)
            VALUES ('{code}', '{display_name}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    op.execute("""
        CREATE TABLE campaign.interactable_state (
            timeline_id               UUID NOT NULL
                                      REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            area_interactable_id      UUID NOT NULL
                                      REFERENCES world.area_interactables(area_interactable_id)
                                      ON DELETE CASCADE,
            interactable_status_id    UUID NOT NULL
                                      REFERENCES
                                          campaign.interactable_statuses(interactable_status_id)
                                      ON DELETE RESTRICT,
            updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (timeline_id, area_interactable_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.interactable_state IS
        'Current per-timeline status of an interactable (a shrine activated, a lever '
        'thrown, a pylon powered). Separate from whether any party knows it exists '
        '(revision 041).';
    """)
    op.execute(
        "CREATE INDEX ix_interactable_state_area_interactable_id "
        "ON campaign.interactable_state (area_interactable_id);"
    )
    op.execute(
        "CREATE INDEX ix_interactable_state_interactable_status_id "
        "ON campaign.interactable_state (interactable_status_id);"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION campaign.enforce_interactable_state_world()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_timeline_world      UUID;
            v_interactable_world  UUID;
        BEGIN
            SELECT world_id INTO v_timeline_world
            FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

            SELECT e.world_id INTO v_interactable_world
            FROM world.area_interactables ai
            JOIN core.entities e ON e.entity_id = ai.dungeon_area_id
            WHERE ai.area_interactable_id = NEW.area_interactable_id;

            IF v_interactable_world IS DISTINCT FROM v_timeline_world THEN
                RAISE EXCEPTION
                    'Area interactable % belongs to world %, but timeline % belongs to world %',
                    NEW.area_interactable_id, v_interactable_world, NEW.timeline_id,
                    v_timeline_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_interactable_state_world() IS
        'World-agreement guard for campaign.interactable_state.';
    """)
    op.execute("""
        CREATE TRIGGER tr_interactable_state_enforce_world
        BEFORE INSERT OR UPDATE ON campaign.interactable_state
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_interactable_state_world();
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS campaign.interactable_state;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_interactable_state_world();")
    op.execute("DROP TABLE IF EXISTS campaign.interactable_statuses;")

    op.execute("DROP TABLE IF EXISTS campaign.hazard_state;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_hazard_state_world();")
    op.execute("DROP TABLE IF EXISTS campaign.hazard_statuses;")

    op.execute("DROP TABLE IF EXISTS campaign.area_feature_state;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_area_feature_state_world();")

    op.execute("DROP TABLE IF EXISTS campaign.area_connection_state;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_area_connection_state_world();")
    op.execute("DROP TABLE IF EXISTS campaign.connection_statuses;")

    op.execute("DROP TABLE IF EXISTS campaign.location_state;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_location_state_world();")
