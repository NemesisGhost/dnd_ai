"""Branches created through `create_timeline_branch` inherit parent history only
through their branch point (CLAUDE.md rule 7), proven with the production
command and `campaign.effective_events`.

Events are recorded with the raw factory because no production event-authoring
command exists until Phase 15E (test data with no production command).
"""

import uuid

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands.timelines import ExistingWorldTime, LatestPoint, create_timeline_branch
from tests.builders import make_authored_world
from tests.factories import make_event, make_user, make_world_time

pytestmark = pytest.mark.scenario


def _effective(connection: Connection, timeline_id: uuid.UUID) -> set[uuid.UUID]:
    return {
        row[0]
        for row in connection.execute(
            text("SELECT event_id FROM campaign.effective_events(:t)"), {"t": timeline_id}
        )
    }


def test_a_branch_excludes_parent_events_after_its_branch_point(db_connection: Connection) -> None:
    owner = make_user(db_connection)
    world = make_authored_world(db_connection, owner_user_id=owner)
    w, main = world.world_id, world.primary_timeline_id

    t100, t200, t300 = (make_world_time(db_connection, w, k) for k in (100, 200, 300))
    early = make_event(db_connection, w, main, t100, name="early")
    at_branch = make_event(db_connection, w, main, t200, name="at branch point")
    later = make_event(db_connection, w, main, t300, name="later")

    branch = create_timeline_branch(
        db_connection,
        world_id=w,
        parent_timeline_id=main,
        actor_user_id=owner,
        name="Branch",
        description=None,
        branch_point=ExistingWorldTime(world_time_id=t200),
    )
    assert _effective(db_connection, branch.timeline_id) == {early, at_branch}
    assert _effective(db_connection, main) == {early, at_branch, later}

    # A parent event recorded *after* the branch exists, at a later world time,
    # does not leak into the branch.
    t400 = make_world_time(db_connection, w, 400)
    newest = make_event(db_connection, w, main, t400, name="newest")
    assert newest not in _effective(db_connection, branch.timeline_id)

    # The branch's own events are its own.
    t250 = make_world_time(db_connection, w, 250)
    own = make_event(db_connection, w, branch.timeline_id, t250, name="own")
    assert _effective(db_connection, branch.timeline_id) == {early, at_branch, own}
    assert own not in _effective(db_connection, main)


def test_a_latest_branch_sees_present_history_but_not_what_the_parent_records_later(
    db_connection: Connection,
) -> None:
    owner = make_user(db_connection)
    world = make_authored_world(db_connection, owner_user_id=owner)
    w, main = world.world_id, world.primary_timeline_id
    before = make_event(db_connection, w, main, make_world_time(db_connection, w, 100), name="b")

    branch = create_timeline_branch(
        db_connection,
        world_id=w,
        parent_timeline_id=main,
        actor_user_id=owner,
        name="Now Branch",
        description=None,
        branch_point=LatestPoint(label="Now"),
    )
    after = make_event(db_connection, w, main, make_world_time(db_connection, w, 500), name="a")

    assert _effective(db_connection, branch.timeline_id) == {before}
    assert after in _effective(db_connection, main)


def test_a_grandchild_never_sees_ancestor_history_newer_than_its_own_branch_point(
    db_connection: Connection,
) -> None:
    """The reason a branch may not precede its parent's own branch point."""
    owner = make_user(db_connection)
    world = make_authored_world(db_connection, owner_user_id=owner)
    w, main = world.world_id, world.primary_timeline_id
    times = {k: make_world_time(db_connection, w, k) for k in (100, 200, 300)}
    events = {k: make_event(db_connection, w, main, times[k], name=f"e{k}") for k in times}

    child = create_timeline_branch(
        db_connection,
        world_id=w,
        parent_timeline_id=main,
        actor_user_id=owner,
        name="Child",
        description=None,
        branch_point=ExistingWorldTime(world_time_id=times[300]),
    )
    grandchild = create_timeline_branch(
        db_connection,
        world_id=w,
        parent_timeline_id=child.timeline_id,
        actor_user_id=owner,
        name="Grandchild",
        description=None,
        branch_point=ExistingWorldTime(world_time_id=times[300]),
    )
    assert _effective(db_connection, grandchild.timeline_id) == set(events.values())
