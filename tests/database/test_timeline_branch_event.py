"""campaign.timelines.branch_event_id (revision 058).

Covers the validation campaign.enforce_timeline_branch() gained in revision
058: branch_event_id, when set, must belong to the parent timeline and occur
at or before branch_world_time_id. Branch *isolation* — whether a parent
event after the branch point actually leaks into the branch's effective
history — is proven separately by
tests/scenario/test_branch_effective_history.py, which exercises
campaign.effective_events().
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_event,
    make_timeline,
    make_world,
    make_world_time,
    set_timeline_branch_event,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.parent_timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.branch_time_id = make_world_time(connection, self.world_id, 100)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "timeline-branch-event-world")


def test_branch_event_id_accepts_an_event_before_the_branch_point(
    db_connection: Connection, f: Fixture
) -> None:
    earlier_time = make_world_time(db_connection, f.world_id, 50)
    branch_event = make_event(db_connection, f.world_id, f.parent_timeline_id, earlier_time)

    branch = make_timeline(
        db_connection,
        f.world_id,
        name="Branch",
        parent_timeline_id=f.parent_timeline_id,
        branch_world_time_id=f.branch_time_id,
        branch_event_id=branch_event,
    )

    stored = db_connection.execute(
        text("SELECT branch_event_id FROM campaign.timelines WHERE timeline_id = :t"),
        {"t": branch},
    ).scalar()
    assert stored == branch_event


def test_branch_event_id_accepts_an_event_exactly_at_the_branch_point(
    db_connection: Connection, f: Fixture
) -> None:
    branch_event = make_event(db_connection, f.world_id, f.parent_timeline_id, f.branch_time_id)

    branch = make_timeline(
        db_connection,
        f.world_id,
        name="Branch",
        parent_timeline_id=f.parent_timeline_id,
        branch_world_time_id=f.branch_time_id,
        branch_event_id=branch_event,
    )
    assert branch is not None


def test_branch_event_id_rejects_an_event_after_the_branch_point(
    db_connection: Connection, f: Fixture
) -> None:
    later_time = make_world_time(db_connection, f.world_id, 150)
    later_event = make_event(db_connection, f.world_id, f.parent_timeline_id, later_time)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_timeline(
            db_connection,
            f.world_id,
            name="Branch",
            parent_timeline_id=f.parent_timeline_id,
            branch_world_time_id=f.branch_time_id,
            branch_event_id=later_event,
        )
    assert "occurs after the declared branch point" in str(exc.value)


def test_branch_event_id_rejects_an_event_from_a_different_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    unrelated_timeline = make_timeline(db_connection, f.world_id, name="Unrelated")
    unrelated_event = make_event(db_connection, f.world_id, unrelated_timeline, f.branch_time_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_timeline(
            db_connection,
            f.world_id,
            name="Branch",
            parent_timeline_id=f.parent_timeline_id,
            branch_world_time_id=f.branch_time_id,
            branch_event_id=unrelated_event,
        )
    assert "belongs to timeline" in str(exc.value)


def test_branch_event_id_requires_a_parent_timeline(db_connection: Connection, f: Fixture) -> None:
    root_event = make_event(db_connection, f.world_id, f.parent_timeline_id, f.branch_time_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_timeline(
            db_connection,
            f.world_id,
            name="Rootless branch event",
            branch_event_id=root_event,
        )
    assert "no parent_timeline_id" in str(exc.value)


def test_branch_event_id_can_be_set_after_the_timeline_already_exists(
    db_connection: Connection, f: Fixture
) -> None:
    """Exercises the UPDATE path, not just INSERT — a branch may be created
    before its causal event is known and given one later."""
    branch = make_timeline(
        db_connection,
        f.world_id,
        name="Branch",
        parent_timeline_id=f.parent_timeline_id,
        branch_world_time_id=f.branch_time_id,
    )
    branch_event = make_event(db_connection, f.world_id, f.parent_timeline_id, f.branch_time_id)

    set_timeline_branch_event(db_connection, branch, branch_event)

    stored = db_connection.execute(
        text("SELECT branch_event_id FROM campaign.timelines WHERE timeline_id = :t"),
        {"t": branch},
    ).scalar()
    assert stored == branch_event


def test_branch_event_id_update_also_rejects_a_post_branch_event(
    db_connection: Connection, f: Fixture
) -> None:
    branch = make_timeline(
        db_connection,
        f.world_id,
        name="Branch",
        parent_timeline_id=f.parent_timeline_id,
        branch_world_time_id=f.branch_time_id,
    )
    later_time = make_world_time(db_connection, f.world_id, 150)
    later_event = make_event(db_connection, f.world_id, f.parent_timeline_id, later_time)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        set_timeline_branch_event(db_connection, branch, later_event)
    assert "occurs after the declared branch point" in str(exc.value)
