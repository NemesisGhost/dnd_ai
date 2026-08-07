"""campaign.timelines — branch structure (revision 008).

Phase 3 proves the *structure* of branching: a branch records its parent and
its branch point, both belong to the right world, a world has at most one
primary timeline, and the parent chain cannot cycle.

It deliberately does NOT prove branch *isolation* — that a timeline inherits
parent history only up to its branch point (CLAUDE.md rule 7). Phase 6
(revisions 057-059) adds narrative.events, campaign.timelines.branch_event_id,
and campaign.effective_events() to prove that; see
tests/database/test_timeline_branch_event.py for branch_event_id validation
and tests/scenario/test_branch_effective_history.py for the effective-history
exclusion scenario itself. See test_party_memberships.py for the
membership-row scoping that Phase 3 proves independently.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import make_timeline, make_world, make_world_time

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


@pytest.fixture
def world_id(db_connection: Connection) -> uuid.UUID:
    return make_world(db_connection, slug="timeline-world")


# ---------------------------------------------------------------------------
# Root and branch shape
# ---------------------------------------------------------------------------


def test_a_root_timeline_has_neither_parent_nor_branch_point(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    timeline = make_timeline(db_connection, world_id, is_primary=True)

    row = db_connection.execute(
        text("""
            SELECT parent_timeline_id, branch_world_time_id
            FROM campaign.timelines WHERE timeline_id = :t
        """),
        {"t": timeline},
    ).one()
    assert row.parent_timeline_id is None
    assert row.branch_world_time_id is None


def test_a_branch_records_its_parent_and_branch_point(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    parent = make_timeline(db_connection, world_id, is_primary=True)
    branch_time = make_world_time(db_connection, world_id, 500)
    branch = make_timeline(
        db_connection,
        world_id,
        name="What if",
        parent_timeline_id=parent,
        branch_world_time_id=branch_time,
    )

    row = db_connection.execute(
        text("""
            SELECT parent_timeline_id, branch_world_time_id
            FROM campaign.timelines WHERE timeline_id = :t
        """),
        {"t": branch},
    ).one()
    assert row.parent_timeline_id == parent
    assert row.branch_world_time_id == branch_time


def test_a_parent_without_a_branch_point_is_rejected(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    """Half a branch is not a branch: a fork with no point to fork at."""
    parent = make_timeline(db_connection, world_id, is_primary=True)

    with pytest.raises(IntegrityError) as exc:
        make_timeline(db_connection, world_id, name="Broken", parent_timeline_id=parent)
    assert "ck_timelines_branch_fields_paired" in str(exc.value)


def test_a_branch_point_without_a_parent_is_rejected(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    branch_time = make_world_time(db_connection, world_id, 500)

    with pytest.raises(IntegrityError) as exc:
        make_timeline(db_connection, world_id, name="Broken", branch_world_time_id=branch_time)
    assert "ck_timelines_branch_fields_paired" in str(exc.value)


# ---------------------------------------------------------------------------
# World agreement
# ---------------------------------------------------------------------------


def test_a_branch_cannot_belong_to_a_different_world_than_its_parent(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    parent = make_timeline(db_connection, world_id, is_primary=True)
    other_world = make_world(db_connection, slug="timeline-other-world")
    branch_time = make_world_time(db_connection, other_world, 500)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_timeline(
            db_connection,
            other_world,
            name="Cross-world",
            parent_timeline_id=parent,
            branch_world_time_id=branch_time,
        )
    assert "its parent" in str(exc.value)


def test_a_branch_point_from_another_world_is_rejected(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    parent = make_timeline(db_connection, world_id, is_primary=True)
    other_world = make_world(db_connection, slug="timeline-time-other-world")
    foreign_time = make_world_time(db_connection, other_world, 500)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_timeline(
            db_connection,
            world_id,
            name="Foreign branch point",
            parent_timeline_id=parent,
            branch_world_time_id=foreign_time,
        )
    assert "Branch world time" in str(exc.value)


# ---------------------------------------------------------------------------
# Primary timeline
# ---------------------------------------------------------------------------


def test_a_world_cannot_have_two_primary_timelines(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    make_timeline(db_connection, world_id, name="First", is_primary=True)

    with pytest.raises(IntegrityError) as exc:
        make_timeline(db_connection, world_id, name="Second", is_primary=True)
    assert "ux_timelines_one_primary_per_world" in str(exc.value)


def test_a_world_may_have_many_non_primary_timelines(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    """The uniqueness is partial on is_primary — otherwise a world could hold
    only one timeline, which defeats the point of branching."""
    make_timeline(db_connection, world_id, name="Primary", is_primary=True)
    make_timeline(db_connection, world_id, name="Alt A")
    make_timeline(db_connection, world_id, name="Alt B")

    count = db_connection.execute(
        text("SELECT count(*) FROM campaign.timelines WHERE world_id = :w"),
        {"w": world_id},
    ).scalar()
    assert count == 3


def test_two_worlds_may_each_have_a_primary_timeline(db_connection: Connection) -> None:
    first = make_world(db_connection, slug="timeline-world-a")
    second = make_world(db_connection, slug="timeline-world-b")
    make_timeline(db_connection, first, is_primary=True)
    make_timeline(db_connection, second, is_primary=True)


# ---------------------------------------------------------------------------
# Cycles
# ---------------------------------------------------------------------------


def test_a_timeline_cannot_be_its_own_parent(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    """Rejected — by the trigger's cycle walk rather than by
    ck_timelines_no_self_parent, because a BEFORE trigger runs ahead of CHECK
    evaluation and a self-parent is the shortest possible cycle. Both are real
    defences; the assertion accepts either so the test does not become a
    statement about evaluation order.
    """
    timeline = make_timeline(db_connection, world_id, is_primary=True)
    branch_time = make_world_time(db_connection, world_id, 500)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                UPDATE campaign.timelines
                SET parent_timeline_id = timeline_id, branch_world_time_id = :bt
                WHERE timeline_id = :t
            """),
            {"t": timeline, "bt": branch_time},
        )
    message = str(exc.value)
    assert "cycle" in message or "ck_timelines_no_self_parent" in message


def test_a_longer_parent_cycle_is_rejected(db_connection: Connection, world_id: uuid.UUID) -> None:
    """The CHECK only catches self-parenting. A → B → A needs the trigger,
    and an undetected cycle would make Phase 6's history walk loop forever."""
    branch_time = make_world_time(db_connection, world_id, 500)
    first = make_timeline(db_connection, world_id, name="A", is_primary=True)
    second = make_timeline(
        db_connection,
        world_id,
        name="B",
        parent_timeline_id=first,
        branch_world_time_id=branch_time,
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                UPDATE campaign.timelines
                SET parent_timeline_id = :p, branch_world_time_id = :bt
                WHERE timeline_id = :t
            """),
            {"p": second, "bt": branch_time, "t": first},
        )
    assert "cycle" in str(exc.value)
