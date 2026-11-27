# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""P15-C11-S01-T02: the three post-write clock routes and the always-on campaign clock (E32-E35).

Plan section 3.2 item 3a. The base authority statement reads the campaign clock on every call, so the final check
of `POST .../clock/advance`, `POST .../clock/correct` and `POST .../world-times` reads tables those routes write.
That is safe only because each route's two requirements read role capabilities and nothing the clock produces
(E32), the route's own decision does not change with its own clock write (E33), other members' assignments follow
the routes (E34), and the snapshot never waits for a clock writer (E35).
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.commands.campaign_clock import advance_campaign_clock
from dnd_ai.domain.access import AuthoritySnapshot, read_authority_snapshot
from dnd_ai.domain.authorization import AuthorizationPlan
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    pooled,
    pooled_factory,
)
from tests.database.test_r01_s4_operation_routes import (  # noqa: F401 - fixtures used by name
    World,
    _calendar,
    _seed,
    _time,
    code,
    run_with_role_expiring_before_final,
    state,
    w,
)
from tests.factories import (
    make_campaign_membership,
    make_character,
    make_control_assignment,
    make_user,
)
from tests.http_race_support import new_key
from tests.r01_support import fixture_plan

pytestmark = [pytest.mark.database, pytest.mark.real_relationship_policy]

Factory = Callable[[uuid.UUID], TestClient]
_REQUIREMENTS = ["route.canon.edit", "campaign.canon.edit"]


def _key(engine: Engine, world_time_id: str | uuid.UUID) -> int:
    with engine.connect() as connection:
        value = connection.execute(
            text("SELECT sort_key FROM core.world_times WHERE world_time_id = :t"),
            {"t": world_time_id},
        ).scalar_one()
    return int(value)


def _times(w: World, factory: Factory, count: int) -> list[str]:
    """`count` world times through the route, in ascending clock order."""
    made = [_time(w, factory, f"c11 {n}") for n in range(count)]
    return sorted(made, key=lambda t: _key(w.engine, t))


def _character(w: World, name: str) -> uuid.UUID:
    with w.engine.begin() as connection:
        return make_character(connection, w.world_id, name=name)


def _member(w: World) -> tuple[uuid.UUID, uuid.UUID]:
    """A role-less member: (user id, membership id)."""
    with w.engine.begin() as connection:
        user = make_user(connection, "C11 Controller")
        return user, make_campaign_membership(connection, w.campaign_id, user)


def _assign(
    w: World,
    membership: uuid.UUID,
    character: uuid.UUID,
    role: str,
    kind: str,
    *,
    frm: str | None = None,
    to: str | None = None,
) -> None:
    with w.engine.begin() as connection:
        make_control_assignment(
            connection,
            membership,
            character,
            role,
            kind,
            from_time=uuid.UUID(frm) if frm else None,
            to_time=uuid.UUID(to) if to else None,
        )


def _snapshot(w: World, user: uuid.UUID) -> AuthoritySnapshot:
    with w.engine.connect() as connection:
        return read_authority_snapshot(connection, user_id=user, campaign_id=w.campaign_id)


def _assigned(w: World, user: uuid.UUID) -> tuple[set[uuid.UUID], int | None]:
    access = _snapshot(w, user).access
    assert access is not None
    return set(access.control_assignments), access.control_clock_key


class _Spy:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple[list[Any], AuthoritySnapshot | None]] = []
        original = AuthorizationPlan.finalize
        calls = self.calls

        def spy(plan: AuthorizationPlan, connection: Any) -> Any:
            result = original(plan, connection)
            calls.append((list(plan.requirements), result))
            return result

        monkeypatch.setattr(AuthorizationPlan, "finalize", spy)


def _post(
    w: World, factory: Factory, user: uuid.UUID, path: str, body: dict[str, Any], key: str | None
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    with factory(user) as client:
        return client.post(f"{w.base}{path}", json=body, headers=headers)


# --- E32 -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("keyed", [True, False], ids=["keyed", "unkeyed"])
@pytest.mark.parametrize("route", ["advance", "correct", "world_time"])
def test_each_clock_route_registers_exactly_its_two_role_only_requirements(
    route: str,
    keyed: bool,
    w: World,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E32 (guard): no character, perspective, world, reveal, subject-`gm` or account requirement."""
    t1, t2, t3 = _times(w, pooled_factory, 3)
    if route == "world_time":
        path, body, ok = (
            "/world-times",
            {"calendar_id": _calendar(w, pooled_factory), "year": 123},
            201,
        )
    elif route == "advance":
        path, body, ok = "/clock/advance", {"world_time_id": t1, "expected_row_version": 0}, 200
    else:
        first = _seed(
            w,
            pooled_factory,
            "/clock/advance",
            {"world_time_id": t2, "expected_row_version": 0},
            ok=200,
        )
        path = "/clock/correct"
        body = {
            "world_time_id": t1,
            "expected_row_version": 1,
            "corrects_event_id": first["event_id"],
        }
        ok = 200
    spy = _Spy(monkeypatch)
    response = _post(w, pooled_factory, w.gm_user, path, body, new_key() if keyed else None)
    assert code(response) == ok, response.text
    assert spy.calls
    for requirements, _ in spy.calls:
        assert [r.name for r in requirements] == _REQUIREMENTS
        for r in requirements:
            assert r.world_id is None and not r.reveal and not r.account
            assert r.gm_subject is None and r.perspective is None
            # S02-R2 added a declarable subject source; the clock routes declare none (E32 kept closed)
            assert r.assistant_gm_subject is None


# --- E33 -------------------------------------------------------------------------------------------------------


def test_a_clock_writers_own_final_check_sees_its_own_write_and_is_not_changed_by_it(
    w: World, pooled: Engine, pooled_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E33: the GM holds `canon.edit` from the role and two dated assignments around t2. Advance to t2 returns 200;
    the final statement's snapshot holds the post-write key, the first assignment ended and the second in effect.
    Correcting back reverses it. The clock, event and audit rows are committed."""
    t1, t2, _ = _times(w, pooled_factory, 3)
    one, two = _character(w, "First"), _character(w, "Second")
    _seed(
        w,
        pooled_factory,
        "/clock/advance",
        {"world_time_id": t1, "expected_row_version": 0},
        ok=200,
    )
    _assign(w, w.gm_membership, one, "primary_controller", "dated", frm=t1, to=t2)
    _assign(w, w.gm_membership, two, "co_controller", "dated", frm=t2)
    spy = _Spy(monkeypatch)

    advance = _post(
        w,
        pooled_factory,
        w.gm_user,
        "/clock/advance",
        {"world_time_id": t2, "expected_row_version": 1},
        new_key(),
    )
    assert code(advance) == 200, advance.text
    final = spy.calls[-1][1]
    assert final is not None and final.access is not None
    assert final.access.control_clock_key == _key(w.engine, t2)
    assert set(final.access.control_assignments) == {two}

    spy.calls.clear()
    correct = _post(
        w,
        pooled_factory,
        w.gm_user,
        "/clock/correct",
        {
            "world_time_id": t1,
            "expected_row_version": 2,
            "corrects_event_id": advance.json()["event_id"],
        },
        new_key(),
    )
    assert code(correct) == 200, correct.text
    final = spy.calls[-1][1]
    assert final is not None and final.access is not None
    assert final.access.control_clock_key == _key(w.engine, t1)
    assert set(final.access.control_assignments) == {one}
    with w.engine.connect() as connection:
        current = connection.execute(
            text(
                "SELECT k.current_world_time_id FROM campaign.timeline_clocks k "
                "JOIN campaign.campaigns c ON c.timeline_id = k.timeline_id WHERE c.campaign_id = :c"
            ),
            {"c": w.campaign_id},
        ).scalar_one()
        audited = connection.execute(
            text(
                "SELECT count(*) FROM audit.change_log WHERE world_id = :w AND command_name LIKE '%clock%'"
            ),
            {"w": w.world_id},
        ).scalar_one()
    assert str(current) == t1 and audited >= 2


@pytest.mark.parametrize("route", ["advance", "correct"])
def test_a_clock_route_whose_role_lapses_before_the_final_statement_is_refused_and_persists_nothing(
    route: str, w: World, pooled: Engine, pooled_factory: Factory
) -> None:
    """E33, refusal: whatever assignments are in effect, the role decides."""
    t1, t2, _ = _times(w, pooled_factory, 3)
    one = _character(w, "Held")
    _assign(w, w.gm_membership, one, "primary_controller", "ongoing")
    first = _seed(
        w,
        pooled_factory,
        "/clock/advance",
        {"world_time_id": t1, "expected_row_version": 0},
        ok=200,
    )
    if route == "advance":
        path, body = "/clock/advance", {"world_time_id": t2, "expected_row_version": 1}
    else:
        path = "/clock/correct"
        body = {
            "world_time_id": t2,
            "expected_row_version": 1,
            "corrects_event_id": first["event_id"],
        }
    key = new_key()
    before = state(w, key)
    response = run_with_role_expiring_before_final(
        w, pooled, lambda: _post(w, pooled_factory, w.gm_user, path, body, key)
    )
    assert code(response) in (403, 404), response.text
    assert state(w, key) == before


# --- E34 -------------------------------------------------------------------------------------------------------


def test_another_members_assignments_follow_the_clock_routes(
    w: World, pooled_factory: Factory
) -> None:
    """E34."""
    t1, t2, _ = _times(w, pooled_factory, 3)
    user, membership = _member(w)
    one, two, always = _character(w, "One"), _character(w, "Two"), _character(w, "Always")
    _assign(w, membership, one, "primary_controller", "dated", frm=t1, to=t2)
    _assign(w, membership, two, "co_controller", "dated", frm=t2)
    _assign(w, membership, always, "co_controller", "ongoing")

    assert _assigned(w, user) == ({always}, None)
    advance1 = _seed(
        w,
        pooled_factory,
        "/clock/advance",
        {"world_time_id": t1, "expected_row_version": 0},
        ok=200,
    )
    assert _assigned(w, user) == ({one, always}, _key(w.engine, t1))
    advance2 = _seed(
        w,
        pooled_factory,
        "/clock/advance",
        {"world_time_id": t2, "expected_row_version": 1},
        ok=200,
    )
    assert _assigned(w, user) == ({two, always}, _key(w.engine, t2))
    _seed(
        w,
        pooled_factory,
        "/clock/correct",
        {"world_time_id": t1, "expected_row_version": 2, "corrects_event_id": advance2["event_id"]},
        ok=200,
    )
    assert _assigned(w, user) == ({one, always}, _key(w.engine, t1))
    # a new world time between the two changes neither the key nor any assignment's effect
    _seed(
        w,
        pooled_factory,
        "/world-times",
        {"calendar_id": _calendar(w, pooled_factory), "year": 4},
        ok=201,
    )
    assert _assigned(w, user) == ({one, always}, _key(w.engine, t1))
    assert advance1["event_id"]


# --- E35 -------------------------------------------------------------------------------------------------------


def test_a_snapshot_never_waits_for_a_clock_writer_and_sees_the_committed_key(
    w: World, pooled_factory: Factory
) -> None:
    """E35: no new wait. An advance holds the clock row `FOR UPDATE` uncommitted; another connection's snapshot
    completes under a short `lock_timeout` with the committed key, the writer's own sees its key, and after the
    commit both see the new one."""
    t1, t2, _ = _times(w, pooled_factory, 3)
    user, membership = _member(w)
    one = _character(w, "Racing")
    _assign(w, membership, one, "primary_controller", "dated", frm=t2)
    _seed(
        w,
        pooled_factory,
        "/clock/advance",
        {"world_time_id": t1, "expected_row_version": 0},
        ok=200,
    )
    with w.engine.connect() as a, w.engine.connect() as b:
        a.execute(text("SELECT 1"))  # the plan binds to the transaction, which must exist first
        advance_campaign_clock(
            a,
            campaign_id=w.campaign_id,
            actor_user_id=w.owner,
            world_time_id=uuid.UUID(t2),
            expected_row_version=1,
            plan=fixture_plan(a, w.campaign_id),
        )
        own = read_authority_snapshot(a, user_id=user, campaign_id=w.campaign_id)
        b.execute(text("SET LOCAL lock_timeout = '2s'"))
        other = read_authority_snapshot(b, user_id=user, campaign_id=w.campaign_id)
        assert own.access is not None and other.access is not None
        assert own.access.control_clock_key == _key(w.engine, t2)
        assert set(own.access.control_assignments) == {one}
        assert other.access.control_clock_key == _key(w.engine, t1)
        assert other.access.control_assignments == {}
        a.commit()
        b.rollback()
        after = read_authority_snapshot(b, user_id=user, campaign_id=w.campaign_id)
        assert after.access is not None
        assert after.access.control_clock_key == _key(w.engine, t2)
        assert set(after.access.control_assignments) == {one}
        b.rollback()
