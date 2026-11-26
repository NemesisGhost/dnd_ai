"""R01 E2 correction C-1: party eligibility is evaluated by the final snapshot statement.

`read_authority_snapshot(..., perspective=(party_id, character_id))` returns the campaign-party association and the
membership at the campaign clock from the SAME statement and MVCC snapshot as the capability checks, with no row lock.
The effective clock is resolved in SQL (own clock row, else the parent's clock bounded at the branch point, else none)
and this module proves it equals `queries.party_membership_period.read_perspective_facts` (which uses the Python
resolver `resolve_effective_clock`) across the clock cases, including branch inheritance and the no-clock case.
Everything runs in the rolled-back `db_connection` transaction.
"""

import re
import uuid

import pytest
from sqlalchemy import Connection, event, text

from dnd_ai.domain.access import read_authority_snapshot
from dnd_ai.queries.party_membership_period import read_perspective_facts
from tests.factories import (
    make_campaign,
    make_campaign_party,
    make_character,
    make_party,
    make_party_membership,
    make_timeline,
    make_timeline_clock,
    make_user,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database


def build(
    c: Connection,
    *,
    branch: bool,
    own_clock: int | None,
    parent_clock: int | None,
    branch_key: int = 100,
    member_from: int = 10,
    member_to: int | None = None,
    associated: bool = True,
    associated_elsewhere: bool = False,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """(user, campaign, timeline, character, party). Times are world times keyed by their sort key."""
    world = make_world(c, slug=f"e2-persp-{uuid.uuid4().hex[:8]}")
    wt = {key: make_world_time(c, world, key) for key in (0, 5, 10, 40, 50, 60, 100, 150, 200)}
    root = make_timeline(c, world, "Root", is_primary=True)
    if parent_clock is not None:
        make_timeline_clock(c, root, wt[parent_clock])
    timeline = root
    if branch:
        timeline = make_timeline(
            c, world, "Branch", parent_timeline_id=root, branch_world_time_id=wt[branch_key]
        )
    if own_clock is not None:
        make_timeline_clock(c, timeline, wt[own_clock])
    campaign = make_campaign(c, timeline, lifecycle_status_code="pending")
    character = make_character(c, world, name="Hero")
    party = make_party(c, world)
    if associated:
        make_campaign_party(c, campaign, party)
    if associated_elsewhere:
        other = make_campaign(c, timeline, "Other", lifecycle_status_code="pending")
        make_campaign_party(c, other, party)
    make_party_membership(
        c,
        timeline,
        party,
        character,
        wt[member_from],
        effective_to_world_time_id=wt[member_to] if member_to is not None else None,
    )
    return make_user(c, "Anyone"), campaign, timeline, character, party


def cfg(**kwargs: object) -> dict[str, object]:
    return kwargs


# name -> (build kwargs, expected member_now)
CASES = {
    "own_clock_inside": (cfg(branch=False, own_clock=100, parent_clock=None), True),
    "no_clock_and_a_membership_covering_zero": (
        cfg(branch=False, own_clock=None, parent_clock=None, member_from=0),
        False,
    ),
    "own_clock_before_join": (cfg(branch=False, own_clock=5, parent_clock=None), False),
    "no_clock_at_all": (cfg(branch=False, own_clock=None, parent_clock=None), False),
    "membership_ended_before_clock": (
        cfg(branch=False, own_clock=100, parent_clock=None, member_from=10, member_to=50),
        False,
    ),
    "leave_boundary_is_excluded": (
        cfg(branch=False, own_clock=100, parent_clock=None, member_from=10, member_to=100),
        False,
    ),
    "join_boundary_is_included": (
        cfg(branch=False, own_clock=100, parent_clock=None, member_from=100),
        True,
    ),
    "branch_inherits_parent_clock_before_the_branch_point": (
        cfg(branch=True, own_clock=None, parent_clock=50, branch_key=100, member_from=10),
        True,
    ),
    "branch_inherited_clock_is_before_the_join": (
        cfg(branch=True, own_clock=None, parent_clock=50, branch_key=100, member_from=60),
        False,
    ),
    "branch_clock_is_bounded_at_the_branch_point": (
        cfg(
            branch=True,
            own_clock=None,
            parent_clock=150,
            branch_key=100,
            member_from=10,
            member_to=150,
        ),
        True,
    ),
    "branch_with_an_unset_parent_uses_the_branch_point": (
        cfg(branch=True, own_clock=None, parent_clock=None, branch_key=100, member_from=100),
        True,
    ),
    "branch_own_clock_wins": (
        cfg(
            branch=True,
            own_clock=60,
            parent_clock=150,
            branch_key=100,
            member_from=10,
            member_to=100,
        ),
        True,
    ),
    "branch_own_clock_after_a_leave": (
        cfg(
            branch=True,
            own_clock=200,
            parent_clock=50,
            branch_key=100,
            member_from=10,
            member_to=150,
        ),
        False,
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_snapshot_evaluates_membership_at_the_campaign_clock_like_the_python_resolver(
    name: str, db_connection: Connection
) -> None:
    kwargs, expected = CASES[name]
    user, campaign, timeline, character, party = build(db_connection, **kwargs)  # type: ignore[arg-type]
    snapshot = read_authority_snapshot(
        db_connection, user_id=user, campaign_id=campaign, perspective=(party, character)
    )
    assert snapshot.perspective is not None
    assert snapshot.perspective.party_in_campaign is True
    assert snapshot.perspective.member_now is expected, name
    reference = read_perspective_facts(
        db_connection,
        campaign_id=campaign,
        timeline_id=timeline,
        character_id=character,
        party_id=party,
    )
    assert (snapshot.perspective.party_in_campaign, snapshot.perspective.member_now) == (
        reference.party_in_campaign,
        reference.member_now,
    )


def test_a_party_outside_the_campaign_is_not_associated(db_connection: Connection) -> None:
    user, campaign, _timeline, character, party = build(
        db_connection, branch=False, own_clock=100, parent_clock=None, associated=False
    )
    snapshot = read_authority_snapshot(
        db_connection, user_id=user, campaign_id=campaign, perspective=(party, character)
    )
    assert snapshot.perspective is not None
    assert snapshot.perspective.party_in_campaign is False
    assert (
        snapshot.perspective.member_now is True
    )  # the membership fact is independent of the association


def test_a_party_associated_only_with_another_campaign_is_not_associated(
    db_connection: Connection,
) -> None:
    user, campaign, _t, character, party = build(
        db_connection,
        branch=False,
        own_clock=100,
        parent_clock=None,
        associated=False,
        associated_elsewhere=True,
    )
    snapshot = read_authority_snapshot(
        db_connection, user_id=user, campaign_id=campaign, perspective=(party, character)
    )
    assert snapshot.perspective is not None and snapshot.perspective.party_in_campaign is False


def test_without_a_declared_perspective_the_snapshot_carries_none_and_the_statement_is_unchanged(
    db_connection: Connection,
) -> None:
    user, campaign, _t, _c, _p = build(
        db_connection, branch=False, own_clock=100, parent_clock=None
    )
    snapshot = read_authority_snapshot(db_connection, user_id=user, campaign_id=campaign)
    assert snapshot.perspective is None


def test_one_statement_no_row_lock(db_connection: Connection) -> None:
    user, campaign, _t, character, party = build(
        db_connection, branch=True, own_clock=None, parent_clock=50
    )
    seen: list[str] = []

    def record(_c: object, _cur: object, statement: object, *_: object) -> None:
        seen.append(" ".join(str(statement).split()))

    event.listen(db_connection, "before_cursor_execute", record)
    try:
        read_authority_snapshot(
            db_connection, user_id=user, campaign_id=campaign, perspective=(party, character)
        )
    finally:
        event.remove(db_connection, "before_cursor_execute", record)
    assert len(seen) == 1
    assert "campaign_clock" in seen[0]
    assert not re.search(r"\bFOR (UPDATE|SHARE|KEY SHARE|NO KEY UPDATE)\b", seen[0])
    assert text  # the statement is one SELECT: the access and perspective sources share it
