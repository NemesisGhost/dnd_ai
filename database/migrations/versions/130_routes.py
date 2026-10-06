"""Add routes between locations as a relationship subtype

Revision ID: 130_routes
Revises: 129_relationship_definition
Create Date: 2026-10-06 21:00:00.000000

Purpose:
    Phase 15 checkpoint 15.3A-2c (decision D-20, option a). DATABASE_MODEL section 9.1 says
    routes between locations use the relationship model, not a table of their own. This adds
    the pieces: the relationship type `route`, the participant roles `origin` and
    `destination`, the typed subtype `world.route_relationships` (distance, travel time and
    mode as free text, and whether the route is built to be concealed), and the event type that
    recording travel writes.

Forward migration:
    - `world.relationship_types`: `route`; `world.relationship_participant_roles`: `origin`,
      `destination` (`ON CONFLICT (code) DO NOTHING`).
    - `world.route_relationships (relationship_id, distance_text, travel_time_text, travel_mode,
      is_hidden)`: one row per route, removed with its relationship, with bounded text.
    - `narrative.event_types`: `characters_traveled`.

Rollback:
    Supported: drops the table and deletes the lookup rows by code. The deletes fail (foreign
    key) once any relationship, participant or event uses them, which is the safe outcome;
    downgrade is intended for development databases.

Data implications:
    Three lookup rows and one empty table.

Locking considerations:
    Lookup inserts and a new table; nothing existing is rewritten.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "130_routes"
down_revision = "129_relationship_definition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO world.relationship_types (code, display_name, sort_order)
        VALUES ('route', 'Route', 20) ON CONFLICT (code) DO NOTHING;
    """)
    op.execute("""
        INSERT INTO world.relationship_participant_roles (code, display_name, sort_order)
        VALUES ('origin', 'Origin', 20), ('destination', 'Destination', 21)
        ON CONFLICT (code) DO NOTHING;
    """)
    op.execute("""
        INSERT INTO narrative.event_types (code, display_name, sort_order)
        VALUES ('characters_traveled', 'Characters Traveled', 160)
        ON CONFLICT (code) DO NOTHING;
    """)
    op.execute("""
        CREATE TABLE world.route_relationships (
            relationship_id  UUID PRIMARY KEY
                             REFERENCES world.relationships(relationship_id) ON DELETE CASCADE,
            distance_text     TEXT,
            travel_time_text  TEXT,
            travel_mode       TEXT,
            is_hidden         BOOLEAN NOT NULL DEFAULT false,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_route_relationships_distance_length
                CHECK (distance_text IS NULL OR char_length(distance_text) <= 200),
            CONSTRAINT ck_route_relationships_travel_time_length
                CHECK (travel_time_text IS NULL OR char_length(travel_time_text) <= 200),
            CONSTRAINT ck_route_relationships_travel_mode_length
                CHECK (travel_mode IS NULL OR char_length(travel_mode) <= 200)
        );
    """)
    op.execute("""
        COMMENT ON TABLE world.route_relationships IS
        'A specialized relationship: a route between two locations (origin and destination '
        'participants). Distance, travel time and mode are free text; is_hidden says the route '
        'is built to be concealed and is shown only to editors. Travel along it is recorded '
        'by the travel command, which updates character location history.';
    """)
    op.execute("""
        COMMENT ON COLUMN world.route_relationships.is_hidden IS
        'The route is concealed: only people who can edit canon see it. A fact about the route '
        'itself, never about who has found it.';
    """)
    op.execute("""
        CREATE TRIGGER tr_route_relationships_set_updated_at
        BEFORE UPDATE ON world.route_relationships
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS world.route_relationships;")
    op.execute("DELETE FROM narrative.event_types WHERE code = 'characters_traveled';")
    op.execute(
        "DELETE FROM world.relationship_participant_roles "
        "WHERE code IN ('origin', 'destination');"
    )
    op.execute("DELETE FROM world.relationship_types WHERE code = 'route';")
