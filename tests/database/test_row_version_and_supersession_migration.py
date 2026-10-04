"""row_version tokens and the supersession link (revision 111).

`row_version` is the optimistic-concurrency token every authoring command
compares as `expected_row_version`. The supersession link is the explicit
replacement relationship ENTITY_LIFECYCLE §16.4 requires.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.factories import (
    make_campaign,
    make_entity,
    make_entity_type,
    make_timeline,
    make_world,
    status_id,
)

pytestmark = pytest.mark.database


def _version(connection: Connection, table: str, pk: str, value: uuid.UUID) -> int:
    result = connection.execute(
        text(f"SELECT row_version FROM {table} WHERE {pk} = :v"), {"v": value}
    ).scalar()
    assert isinstance(result, int)
    return result


def _rows(connection: Connection) -> dict[str, tuple[str, str, str, uuid.UUID]]:
    """(table, pk column, column to update, id) for one row of each versioned table."""
    world = make_world(connection, "rv-world")
    timeline = make_timeline(connection, world, is_primary=True)
    campaign = make_campaign(connection, timeline, lifecycle_status_code="pending")
    entity_type = make_entity_type(connection, "rv_thing")
    entity = make_entity(connection, world, entity_type)
    return {
        "world": ("core.worlds", "world_id", "name", world),
        "timeline": ("campaign.timelines", "timeline_id", "name", timeline),
        "campaign": ("campaign.campaigns", "campaign_id", "name", campaign),
        "entity": ("core.entities", "entity_id", "canonical_name", entity),
    }


@pytest.mark.parametrize("which", ["world", "timeline", "campaign", "entity"])
def test_row_version_starts_at_one_and_bumps_on_every_update(
    db_connection: Connection, which: str
) -> None:
    table, pk, column, row_id = _rows(db_connection)[which]
    # Building the fixtures may itself update a parent row (a world gains its
    # default ruleset), so measure from the current value rather than from 1.
    baseline = _version(db_connection, table, pk, row_id)

    for step in (1, 2):
        db_connection.execute(
            text(f"UPDATE {table} SET {column} = :v WHERE {pk} = :id"),
            {"v": f"renamed {step}", "id": row_id},
        )
        assert _version(db_connection, table, pk, row_id) == baseline + step


@pytest.mark.parametrize("which", ["world", "timeline", "campaign", "entity"])
def test_a_freshly_inserted_row_starts_at_version_one(
    db_connection: Connection, which: str
) -> None:
    world = make_world(db_connection, "rv-fresh")
    timeline = make_timeline(db_connection, world, is_primary=True)
    entity = make_entity(db_connection, world, make_entity_type(db_connection, "rv_fresh_thing"))
    rows = {
        "world": ("core.worlds", "world_id", world),
        "timeline": ("campaign.timelines", "timeline_id", timeline),
        "campaign": (
            "campaign.campaigns",
            "campaign_id",
            make_campaign(db_connection, timeline, lifecycle_status_code="pending"),
        ),
        "entity": ("core.entities", "entity_id", entity),
    }
    table, pk, row_id = rows[which]
    # make_campaign provisions a ruleset and sets the world's default, which
    # bumps the world row; the other three tables are untouched.
    if which != "world":
        assert _version(db_connection, table, pk, row_id) == 1


@pytest.mark.parametrize("which", ["world", "timeline", "campaign", "entity"])
def test_a_statement_cannot_choose_its_own_row_version(
    db_connection: Connection, which: str
) -> None:
    table, pk, _column, row_id = _rows(db_connection)[which]
    baseline = _version(db_connection, table, pk, row_id)
    db_connection.execute(
        text(f"UPDATE {table} SET row_version = 99 WHERE {pk} = :id"), {"id": row_id}
    )
    assert _version(db_connection, table, pk, row_id) == baseline + 1


@pytest.mark.parametrize("which", ["world", "timeline", "campaign", "entity"])
def test_row_version_must_be_positive(db_connection: Connection, which: str) -> None:
    """The bump trigger overwrites row_version on UPDATE, so the CHECK is only
    reachable through INSERT — assert its presence in the catalog instead."""
    table, _pk, _column, _id = _rows(db_connection)[which]
    schema, name = table.split(".")
    found = db_connection.execute(
        text("""
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = :s AND t.relname = :t AND c.contype = 'c'
              AND pg_get_constraintdef(c.oid) LIKE '%row_version >= 1%'
        """),
        {"s": schema, "t": name},
    ).scalar()
    assert found is not None


# ---------------------------------------------------------------------------
# Supersession link
# ---------------------------------------------------------------------------


def _set_status(connection: Connection, entity: uuid.UUID, canon: str) -> None:
    connection.execute(
        text("UPDATE core.entities SET canon_status_id = :s WHERE entity_id = :e"),
        {"s": status_id(connection, "canon_statuses", canon), "e": entity},
    )


def _supersede(connection: Connection, old: uuid.UUID, new: uuid.UUID) -> None:
    connection.execute(
        text("""
            UPDATE core.entities
            SET canon_status_id = :s, superseded_by_entity_id = :n
            WHERE entity_id = :o
        """),
        {"s": status_id(connection, "canon_statuses", "superseded"), "n": new, "o": old},
    )


@pytest.fixture
def pair(db_connection: Connection) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    world = make_world(db_connection, "supersede-world")
    entity_type = make_entity_type(db_connection, "supersede_thing")
    return (
        world,
        entity_type,
        make_entity(db_connection, world, entity_type, "Old"),
        make_entity(db_connection, world, entity_type, "New"),
    )


def test_supersession_links_a_replacement_of_the_same_world_and_type(
    db_connection: Connection, pair: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    _world, _type, old, new = pair
    _supersede(db_connection, old, new)
    stored = db_connection.execute(
        text("SELECT superseded_by_entity_id FROM core.entities WHERE entity_id = :e"),
        {"e": old},
    ).scalar()
    assert stored == new


def test_an_entity_cannot_supersede_itself(
    db_connection: Connection, pair: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    _world, _type, old, _new = pair
    with pytest.raises(IntegrityError) as exc:
        _supersede(db_connection, old, old)
    assert "ck_entities_not_self_superseded" in str(exc.value)


def test_the_link_requires_superseded_canon_status(
    db_connection: Connection, pair: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    _world, _type, old, new = pair
    with pytest.raises(DBAPIError) as exc:
        db_connection.execute(
            text("UPDATE core.entities SET superseded_by_entity_id = :n WHERE entity_id = :o"),
            {"n": new, "o": old},
        )
    assert "not superseded" in str(exc.value)


def test_the_replacement_must_share_the_world(
    db_connection: Connection, pair: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    _world, entity_type, old, _new = pair
    other_world = make_world(db_connection, "supersede-other-world")
    foreign = make_entity(db_connection, other_world, entity_type, "Foreign")
    with pytest.raises(DBAPIError) as exc:
        _supersede(db_connection, old, foreign)
    assert "same world and entity type" in str(exc.value)


def test_the_replacement_must_share_the_entity_type(
    db_connection: Connection, pair: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    world, _type, old, _new = pair
    other_type = make_entity_type(db_connection, "supersede_other_thing")
    foreign = make_entity(db_connection, world, other_type, "Other type")
    with pytest.raises(DBAPIError) as exc:
        _supersede(db_connection, old, foreign)
    assert "same world and entity type" in str(exc.value)


def test_the_link_is_write_once(
    db_connection: Connection, pair: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    world, entity_type, old, new = pair
    third = make_entity(db_connection, world, entity_type, "Third")
    _supersede(db_connection, old, new)

    with pytest.raises(DBAPIError) as repoint:
        db_connection.execute(
            text("UPDATE core.entities SET superseded_by_entity_id = :n WHERE entity_id = :o"),
            {"n": third, "o": old},
        )
    assert "write-once" in str(repoint.value)


def test_the_link_cannot_be_cleared(
    db_connection: Connection, pair: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    _world, _type, old, new = pair
    _supersede(db_connection, old, new)
    with pytest.raises(DBAPIError) as exc:
        db_connection.execute(
            text("UPDATE core.entities SET superseded_by_entity_id = NULL WHERE entity_id = :o"),
            {"o": old},
        )
    assert "write-once" in str(exc.value)


def test_a_linked_entity_cannot_leave_superseded_status(
    db_connection: Connection, pair: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    _world, _type, old, new = pair
    _supersede(db_connection, old, new)
    with pytest.raises(DBAPIError) as exc:
        _set_status(db_connection, old, "canon")
    assert "not superseded" in str(exc.value)


def test_the_replacement_cannot_be_physically_deleted(
    db_connection: Connection, pair: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    _world, _type, old, new = pair
    _supersede(db_connection, old, new)
    with pytest.raises(IntegrityError):
        db_connection.execute(text("DELETE FROM core.entities WHERE entity_id = :n"), {"n": new})
