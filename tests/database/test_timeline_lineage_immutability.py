"""campaign.timelines lineage is immutable (revision 111).

`parent_timeline_id` and `branch_world_time_id` define which parent history a
branch inherits, so reparenting by UPDATE would silently rewrite history.
`branch_event_id` may still go NULL -> value once (revision 058).
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from tests.factories import (
    make_event,
    make_timeline,
    make_world,
    make_world_time,
    set_timeline_branch_event,
)

pytestmark = pytest.mark.database


class Lineage:
    def __init__(self, connection: Connection) -> None:
        self.world = make_world(connection, "lineage-world")
        self.root = make_timeline(connection, self.world, "Root", is_primary=True)
        self.other_root = make_timeline(connection, self.world, "Other root")
        self.time_a = make_world_time(connection, self.world, 100)
        self.time_b = make_world_time(connection, self.world, 200)
        self.branch = make_timeline(
            connection,
            self.world,
            "Branch",
            parent_timeline_id=self.root,
            branch_world_time_id=self.time_a,
        )


@pytest.fixture
def lineage(db_connection: Connection) -> Lineage:
    return Lineage(db_connection)


def test_a_branch_cannot_be_reparented(db_connection: Connection, lineage: Lineage) -> None:
    with pytest.raises(DBAPIError) as exc:
        db_connection.execute(
            text("UPDATE campaign.timelines SET parent_timeline_id = :p WHERE timeline_id = :t"),
            {"p": lineage.other_root, "t": lineage.branch},
        )
    assert "parent_timeline_id is immutable" in str(exc.value)


def test_a_branch_point_cannot_be_moved(db_connection: Connection, lineage: Lineage) -> None:
    with pytest.raises(DBAPIError) as exc:
        db_connection.execute(
            text("UPDATE campaign.timelines SET branch_world_time_id = :b WHERE timeline_id = :t"),
            {"b": lineage.time_b, "t": lineage.branch},
        )
    assert "branch_world_time_id is immutable" in str(exc.value)


def test_a_root_cannot_gain_a_parent(db_connection: Connection, lineage: Lineage) -> None:
    """NULL -> value is rejected too: this is what makes cycles structurally
    impossible (an INSERT cannot create one and an UPDATE cannot reparent)."""
    with pytest.raises(DBAPIError) as exc:
        db_connection.execute(
            text("""
                UPDATE campaign.timelines
                SET parent_timeline_id = :p, branch_world_time_id = :b
                WHERE timeline_id = :t
            """),
            {"p": lineage.root, "b": lineage.time_a, "t": lineage.other_root},
        )
    assert "immutable" in str(exc.value)


def test_a_branch_cannot_be_turned_into_a_root(db_connection: Connection, lineage: Lineage) -> None:
    with pytest.raises(DBAPIError) as exc:
        db_connection.execute(
            text("""
                UPDATE campaign.timelines
                SET parent_timeline_id = NULL, branch_world_time_id = NULL
                WHERE timeline_id = :t
            """),
            {"t": lineage.branch},
        )
    assert "immutable" in str(exc.value)


def test_ordinary_edits_to_a_branch_still_work(db_connection: Connection, lineage: Lineage) -> None:
    db_connection.execute(
        text(
            "UPDATE campaign.timelines SET name = 'Renamed', description = 'd' WHERE timeline_id = :t"
        ),
        {"t": lineage.branch},
    )
    name = db_connection.execute(
        text("SELECT name FROM campaign.timelines WHERE timeline_id = :t"), {"t": lineage.branch}
    ).scalar()
    assert name == "Renamed"


def test_branch_event_id_may_be_set_once_but_not_changed_or_cleared(
    db_connection: Connection, lineage: Lineage
) -> None:
    early = make_world_time(db_connection, lineage.world, 50)
    first_event = make_event(db_connection, lineage.world, lineage.root, early, name="First")
    second_event = make_event(db_connection, lineage.world, lineage.root, early, name="Second")

    set_timeline_branch_event(db_connection, lineage.branch, first_event)

    with pytest.raises(DBAPIError) as change:
        set_timeline_branch_event(db_connection, lineage.branch, second_event)
    assert "branch_event_id is immutable" in str(change.value)


def test_branch_event_id_cannot_be_cleared_once_set(
    db_connection: Connection, lineage: Lineage
) -> None:
    early = make_world_time(db_connection, lineage.world, 50)
    event = make_event(db_connection, lineage.world, lineage.root, early)
    set_timeline_branch_event(db_connection, lineage.branch, event)

    with pytest.raises(DBAPIError) as exc:
        set_timeline_branch_event(db_connection, lineage.branch, None)
    assert "branch_event_id is immutable" in str(exc.value)


def test_no_change_update_is_allowed(db_connection: Connection, lineage: Lineage) -> None:
    db_connection.execute(
        text("""
            UPDATE campaign.timelines
            SET parent_timeline_id = :p, branch_world_time_id = :b
            WHERE timeline_id = :t
        """),
        {"p": lineage.root, "b": lineage.time_a, "t": lineage.branch},
    )
