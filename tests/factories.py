"""Shared test-data builders.

Lives here rather than in a test module so test modules never import from each
other — that coupling makes it unclear who owns a helper and breaks as soon as
the importing module is collected first.

These issue raw inserts. docs/DATABASE_CONVENTIONS.md §32.3 asks for test data
built through the same commands production uses, and those commands do not
exist yet — the application layer arrives in a later phase. Everything using
these builders is also specifically testing database enforcement, which is the
exception §32.3 allows. Replace these with command calls once the command layer
lands, rather than growing them into a parallel write path.
"""

import uuid

from sqlalchemy import Connection, text


def status_id(connection: Connection, table: str, code: str) -> uuid.UUID:
    """Look up a seeded status by code. Asserts rather than returning None."""
    pk = "canon_status_id" if table == "canon_statuses" else "lifecycle_status_id"
    value = connection.execute(
        text(f"SELECT {pk} FROM core.{table} WHERE code = :c"), {"c": code}
    ).scalar()
    assert isinstance(value, uuid.UUID), f"seeded {table} row {code!r} missing"
    return value


def lookup_id(connection: Connection, schema: str, table: str, pk: str, code: str) -> uuid.UUID:
    value = connection.execute(
        text(f"SELECT {pk} FROM {schema}.{table} WHERE code = :c"), {"c": code}
    ).scalar()
    assert isinstance(value, uuid.UUID), f"seeded {schema}.{table} row {code!r} missing"
    return value


def make_world(connection: Connection, slug: str = "test-world") -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO core.worlds (name, slug, lifecycle_status_id)
            VALUES ('Test World', :slug, :status)
            RETURNING world_id
        """),
        {"slug": slug, "status": status_id(connection, "lifecycle_statuses", "active")},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_entity_type(
    connection: Connection,
    code: str,
    *,
    parent_id: uuid.UUID | None = None,
    subtype_table: str | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO core.entity_types
                (code, display_name, parent_entity_type_id, required_subtype_table)
            VALUES (:code, :code, :parent, :subtype)
            RETURNING entity_type_id
        """),
        {"code": code, "parent": parent_id, "subtype": subtype_table},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_entity(
    connection: Connection,
    world_id: uuid.UUID,
    entity_type_id: uuid.UUID,
    name: str = "Test Entity",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO core.entities
                (world_id, entity_type_id, canonical_name, canon_status_id, lifecycle_status_id)
            VALUES (:world, :etype, :name, :canon, :lifecycle)
            RETURNING entity_id
        """),
        {
            "world": world_id,
            "etype": entity_type_id,
            "name": name,
            "canon": status_id(connection, "canon_statuses", "draft"),
            "lifecycle": status_id(connection, "lifecycle_statuses", "active"),
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_user(connection: Connection, username: str = "tester") -> uuid.UUID:
    value = connection.execute(
        text(
            "INSERT INTO security.users (username, display_name) VALUES (:u, :u) RETURNING user_id"
        ),
        {"u": username},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_world_time(connection: Connection, world_id: uuid.UUID, sort_key: int) -> uuid.UUID:
    """A minimal point in a world's fictional chronology.

    sort_key is the only field that matters to interval logic, so callers pass
    it explicitly and everything else takes a default. year is supplied because
    ck_world_times_year_or_label requires a year or a label.
    """
    value = connection.execute(
        text("""
            INSERT INTO core.world_times
                (world_id, world_time_precision_id, year, sort_key)
            VALUES (
                :world,
                (SELECT world_time_precision_id FROM core.world_time_precisions
                 WHERE code = 'exact'),
                :year,
                :sort_key
            )
            RETURNING world_time_id
        """),
        {"world": world_id, "year": 1000 + sort_key, "sort_key": sort_key},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_timeline(
    connection: Connection,
    world_id: uuid.UUID,
    name: str = "Primary",
    *,
    is_primary: bool = False,
    parent_timeline_id: uuid.UUID | None = None,
    branch_world_time_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.timelines
                (world_id, name, is_primary, parent_timeline_id, branch_world_time_id,
                 lifecycle_status_id)
            VALUES (:world, :name, :primary, :parent, :branch, :status)
            RETURNING timeline_id
        """),
        {
            "world": world_id,
            "name": name,
            "primary": is_primary,
            "parent": parent_timeline_id,
            "branch": branch_world_time_id,
            "status": status_id(connection, "lifecycle_statuses", "active"),
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_party(connection: Connection, world_id: uuid.UUID, name: str = "The Company") -> uuid.UUID:
    value = connection.execute(
        text("INSERT INTO campaign.parties (world_id, name) VALUES (:w, :n) RETURNING party_id"),
        {"w": world_id, "n": name},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_campaign(
    connection: Connection, timeline_id: uuid.UUID, name: str = "The Campaign"
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.campaigns (timeline_id, name, lifecycle_status_id)
            VALUES (:tl, :n, :status)
            RETURNING campaign_id
        """),
        {
            "tl": timeline_id,
            "n": name,
            "status": status_id(connection, "lifecycle_statuses", "active"),
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_session(
    connection: Connection,
    campaign_id: uuid.UUID,
    session_number: int,
    *,
    start_world_time_id: uuid.UUID | None = None,
    end_world_time_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.sessions
                (campaign_id, session_number, lifecycle_status_id,
                 start_world_time_id, end_world_time_id)
            VALUES (:c, :n, :status, :start, :end)
            RETURNING session_id
        """),
        {
            "c": campaign_id,
            "n": session_number,
            "status": status_id(connection, "lifecycle_statuses", "active"),
            "start": start_world_time_id,
            "end": end_world_time_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_world_entity(connection: Connection, slug: str) -> uuid.UUID:
    """A world plus a throwaway entity type plus one entity, for tests that need
    an entity but do not care about its world or type."""
    world = make_world(connection, slug=slug)
    entity_type = make_entity_type(connection, f"{slug.replace('-', '_')}_type")
    return make_entity(connection, world, entity_type)
