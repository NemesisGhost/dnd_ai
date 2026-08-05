"""A timeline branches twice; effective history stays scoped to each branch
point (Phase 6 exit criterion).

docs/PLAN.md's Phase 6 exit criteria require: "A branch inherits parent
events only through its branch point; a parent event after that point is
absent from the branch's effective history, with a scenario test proving the
exclusion." This scenario builds a two-level branch chain — grandparent ->
parent -> child — specifically to prove the subtle case a single branch
cannot: when a grandchild's own branch point (from its immediate parent)
falls *later* in fictional chronology than that parent's branch point from
*its* parent, the grandparent's effective history must still be capped at
the parent's branch point, not the grandchild's — a timeline never gains
access to more grandparent history than its own parent ever inherited.
"""

import uuid

import pytest
from sqlalchemy import Connection, text

from tests.factories import make_event, make_timeline, make_world, make_world_time

pytestmark = pytest.mark.scenario


def _effective_event_ids(connection: Connection, timeline_id: uuid.UUID) -> set[uuid.UUID]:
    rows = connection.execute(
        text("SELECT event_id FROM campaign.effective_events(:tl)"), {"tl": timeline_id}
    ).all()
    return {row[0] for row in rows}


def test_branch_effective_history_excludes_post_branch_parent_events(
    db_connection: Connection,
) -> None:
    conn = db_connection
    world_id = make_world(conn, slug="branch-effective-history-scenario-world")

    # ---- Grandparent (primary) timeline: three events -----------------------
    grandparent = make_timeline(conn, world_id, name="Primary", is_primary=True)
    t100 = make_world_time(conn, world_id, 100)
    t200 = make_world_time(conn, world_id, 200)
    t300 = make_world_time(conn, world_id, 300)

    gp_event_1 = make_event(conn, world_id, grandparent, t100, details="An early omen.")
    gp_branch_event = make_event(conn, world_id, grandparent, t200, details="The betrayal.")
    gp_event_after = make_event(conn, world_id, grandparent, t300, details="The coronation.")

    # ---- Parent branches from grandparent at t200 ----------------------------
    parent = make_timeline(
        conn,
        world_id,
        name="Parent Branch",
        parent_timeline_id=grandparent,
        branch_world_time_id=t200,
        branch_event_id=gp_branch_event,
    )
    t250 = make_world_time(conn, world_id, 250)
    t280 = make_world_time(conn, world_id, 280)
    t350 = make_world_time(conn, world_id, 350)

    parent_branch_event = make_event(conn, world_id, parent, t250, details="A different choice.")
    parent_event_after = make_event(
        conn, world_id, parent, t350, details="Fallout only parent sees."
    )

    # ---- Child branches from parent at t280 (AFTER parent's own branch point
    # from grandparent, t200, but BEFORE parent_event_after at t350) ----------
    child = make_timeline(
        conn,
        world_id,
        name="Child Branch",
        parent_timeline_id=parent,
        branch_world_time_id=t280,
        branch_event_id=parent_branch_event,
    )
    t400 = make_world_time(conn, world_id, 400)
    child_event = make_event(conn, world_id, child, t400, details="The child's own history.")

    # ---- Grandparent: its own full local history, nothing more --------------
    assert _effective_event_ids(conn, grandparent) == {
        gp_event_1,
        gp_branch_event,
        gp_event_after,
    }

    # ---- Parent: own events (unbounded) + grandparent events up to t200 -----
    parent_effective = _effective_event_ids(conn, parent)
    assert parent_effective == {
        parent_branch_event,
        parent_event_after,
        gp_event_1,
        gp_branch_event,
    }
    assert gp_event_after not in parent_effective, (
        "grandparent event after the branch point leaked into the parent's effective history"
    )

    # ---- Child: own events (unbounded) + parent events up to t280 + THE SAME
    # grandparent cutoff (t200) parent itself was bound by — not t280. This is
    # the exclusion the exit criterion specifically requires: the child must
    # not see more grandparent history than parent ever inherited, even though
    # child's own branch point (t280) is later than parent's (t200).
    child_effective = _effective_event_ids(conn, child)
    assert child_effective == {
        child_event,
        parent_branch_event,
        gp_event_1,
        gp_branch_event,
    }
    assert parent_event_after not in child_effective, (
        "parent event after child's branch point leaked into child's effective history"
    )
    assert gp_event_after not in child_effective, (
        "grandparent event after parent's own branch point leaked into child's effective "
        "history, even though child's branch point is later in chronology"
    )
