# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E5: the six access-group routes against the writers their lock sets touch, both transaction orderings.

* **T-5** (correction design section 5): the three-party schedule of the NF-1 cycle with each of **update, deactivate,
  reactivate and add** as the group locker (the S5-E4 grant is T-2 in `test_r01_s5e5_group_races.py`), both role-id orders. X
  (the group route) is parked right after its group lock (it holds its role rows `FOR SHARE` and the group `FOR UPDATE`); C
  (revelation creation) is *observed* waiting at the group on X's backend; V (C's revoke of X's role) is *observed* waiting at its
  ordered role statement holding no row. Released: no driver exception, the deadlock counter unmoved, X then C then V.
* **T-7** (CA-1): keyed authoring by M (it holds the campaign `FOR KEY SHARE` from its reservation, then waits for M's role row),
  the revoke of M's role by Y (it holds M's row and waits for Y's rows) and create or reactivate by Y (it holds Y's rows and
  wants the campaign). With the campaign at `FOR UPDATE` (the legacy mode) that is a three-party cycle (the DEF-019 family);
  with `FOR KEY SHARE` (CA-1) it is clean.
* **Pairs** (design section 10.7, items 1-9): a group route and one other writer, each *parked at its final authority statement*
  (every lock held) in turn; the other is observed queued or finished; no driver exception, no moved deadlock counter, the
  statuses the pair allows, and the invariant the pair must keep.

Every wait is observed (`pg_blocking_pids`), never assumed; a gate that cannot be reached is a SETUP failure.
"""

import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text

from tests.database.test_r01_s2_profile_routes import FINAL, pooled, pooled_factory  # noqa: F401
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixture by name
    World,
    code,
    w,
)
from tests.database.test_r01_s5e2_authoring_transfer_cycles import AUTHORING_WORLD
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixture by name
    PATIENCE,
    NthGate,
    Pool,
    assert_clean,
    author_request,
    cast_two,
    deadlocks_now,
    finish,
    pool,
    post,
    race,
    rows,
    settled_deadlock_delta,
    transfer_body,
)
from tests.database.test_r01_s5e2_membership_routes import (  # noqa: F401 - fixture by name
    Scene,
    m,
    s,
)
from tests.database.test_r01_s5e4_access_grants import AUDIT_INSERT, MEMBERSHIP_S
from tests.database.test_r01_s5e5_group_routes import (  # noqa: F401 - fixture by name
    BY_NAME,
    GEnv,
    _tidy,
    build_genv,
    e,
    release_profile,
)
from tests.factories import (
    make_access_group,
    make_campaign_membership,
    make_character,
    make_user,
)
from tests.http_race_support import run_in_thread, sessions_blocked_by
from tests.r01_s5e5_cycle_support import (
    GROUP_LOCK_STATEMENT,
    ROLE_FOR_UPDATE,
    WAIT_SECONDS,
    assert_no_deadlock,
    build_scene,
    observe_waiter,
    run_cycle_schedule,
)

pytestmark = pytest.mark.database

ORDERS = ("x_row_below_c_rows", "c_rows_below_x_row")
AUTHOR_ROLES = r"FROM security\.membership_roles mr JOIN"
CAMPAIGN_LOCK = r"FROM campaign\.campaigns WHERE .* FOR (KEY SHARE|UPDATE)$"


def owner_membership_of(w: World) -> uuid.UUID:
    return rows(
        w.engine,
        "SELECT campaign_membership_id AS id FROM security.campaign_memberships "
        "WHERE campaign_id = :c AND user_id = :u",
        c=w.campaign_id,
        u=w.owner,
    )[0]["id"]


# =====================================================================================================
# T-5: the three-party cycle schedule with each group route as the group locker
# =====================================================================================================

#: route -> (X's status, C's status). C's revelation to a deactivated group is refused after X commits; every other C succeeds.
T5_STATUS = {
    "update": (200, 201),
    "deactivate": (200, 409),
    "reactivate": (200, 201),
    "add": (201, 201),
}


@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize("route", tuple(T5_STATUS))
def test_t5_the_three_party_schedule_is_clean_with_each_group_route_as_the_group_locker(
    route: str, order: str, w: World, pool: Pool
) -> None:
    """*race* (T-5, AO-1): the T-2 schedule with X's request replaced by the S5-E5 route. No driver exception and the deadlock
    counter unmoved (asserted first: the mutation "the route's group lock before `ACTOR_ROLES_LOCK`" fails here, 40P01); C waits at
    the group on **X's** backend; V waits at its ordered role statement on X's or C's backend **holding no row** (`NOWAIT` probes
    show `FOR SHARE` only); X, C and V complete in that order; every write the statuses promise is durable."""
    sc = build_scene(w, w.owner, owner_membership_of(w), order, f"T5 {route}")
    with w.engine.begin() as c:
        member = make_campaign_membership(c, w.campaign_id, make_user(c, f"T5 member {route}"))
        if route == "reactivate":
            c.execute(
                text(
                    "UPDATE security.access_groups SET lifecycle_status_id = (SELECT lifecycle_status_id "
                    "FROM core.lifecycle_statuses WHERE code = 'archived') WHERE access_group_id = :g"
                ),
                {"g": sc.group},
            )

    def x_call(w_: Any, pool_: Pool, sc_: Any) -> Any:
        base = f"{w_.base}/access-groups/{sc_.group}"
        user = sc_.cast.x_user
        if route == "update":
            return post(
                pool_, user, f"{base}/update", {"name": f"T5 renamed {order}", "description": "d"}
            )
        if route == "deactivate":
            return post(pool_, user, f"{base}/deactivate", {})
        if route == "reactivate":
            return post(pool_, user, f"{base}/reactivate", {})
        return post(pool_, user, f"{base}/members", {"campaign_membership_ids": [str(member)]})

    res = run_cycle_schedule(
        w, pool, sc, park_after=GROUP_LOCK_STATEMENT, v_blockers_within={"x", "c"}, x_call=x_call
    )
    assert_no_deadlock(res)
    assert res.modes == {"x_row": "S", "c_row": "S"}, res.summary()
    waiting_on = res.pids["x"] if order == "x_row_below_c_rows" else res.pids["c"]
    assert res.arrivals["c"].blockers == [res.pids["x"]], res.summary()
    assert res.arrivals["v"].blockers == [waiting_on], res.summary()
    x_status, c_status = T5_STATUS[route]
    assert res.statuses == {
        "x": (x_status, None),
        "c": (c_status, None if c_status == 201 else res.statuses["c"][1]),
        "v": (200, None),
    }, res.summary()
    assert res.ended["x"] <= res.ended["c"] <= res.ended["v"], res.summary()
    assert res.state["x_row_revoked"] is True and res.state["group_grants"] == 0, res.summary()
    assert res.state["revelations"] == (1 if c_status == 201 else 0), res.summary()


# =====================================================================================================
# T-7: CA-1, keyed authoring + the revoke of the author's role + create / reactivate by the revoker
# =====================================================================================================


@pytest.mark.parametrize("order", ("m_row_first", "y_rows_first"))
@pytest.mark.parametrize("route", ("create", "reactivate"))
def test_characterized_t7_the_specified_three_party_schedule_closes_the_deferred_two_party_authoring_cycle(
    route: str, order: str, w: World, pool: Pool
) -> None:
    """*race*, a **characterization** of the schedule T-7 specified (correction design section 5), *not* a CA-1 discriminator: M (`w.gm_user`) authors, keyed: its reservation holds the campaign `FOR KEY SHARE`, then it waits for
    its role rows. Y (an owner) revokes **M's role** (V: it holds M's row `FOR UPDATE` when that row is the lower id, and waits for
    Y's rows) and, in the same schedule, creates or reactivates an access group (Y is parked at its campaign lock statement, holding
    its role rows `FOR SHARE`). With the legacy campaign `FOR UPDATE` Y would wait for the author's `KEY SHARE` while the author waits
    for V and V waits for Y: one 40P01 (the DEF-019 family). With `FOR KEY SHARE` (CA-1) Y is unaffected: **no driver exception, the
    deadlock counter unmoved**, Y succeeds, the revoke commits, the author is refused (its role was revoked while it waited) or,
    when V waits for Y's rows first and holds nothing, completes. `y_rows_first` is the control: V waits at Y's rows first.

    **What the run showed (the conflict with the design, recorded as NF-5).** With Y at `FOR KEY SHARE` the schedule still ends in
    exactly one 40P01 when M's row is the lower id (`m_row_first`): after Y commits, the revoke (W) proceeds to *its own* campaign
    lock, and the S5-E2 role revoke takes the campaign `FOR UPDATE`, which the author's `KEY SHARE` blocks while the author waits for
    the row W holds. That is the **two-party** DEF-019 cycle (keyed authoring against a role writer, CL-E10-1) and it closes whatever
    Y does, so this schedule cannot tell CA-1 from the legacy mode. It is kept as the characterization of that pre-existing
    defect (a pass means *characterized, not fixed*; it fails when the cycle disappears). CA-1 itself is shown by
    `test_t7a_...` and `test_t7b_...` below. `y_rows_first` is clean."""
    m_first = order == "m_row_first"
    cast = cast_two(
        w,
        label=f"T7 {route}",
        roles={"r_y": ("c", "campaign_owner", "high:b1" if m_first else "low:b1")},
    )
    y_user = cast.c_user
    assert (w.gm_role < cast.ids["r_y"]) == m_first, (
        "premise: the role-row id order of the schedule"
    )
    with w.engine.begin() as c:
        archived = make_access_group(
            c,
            w.campaign_id,
            name=f"T7 archived {uuid.uuid4().hex[:6]}",
            lifecycle_status_code="archived",
        )

    def y_call() -> Any:
        if route == "create":
            return post(
                pool, y_user, f"{w.base}/access-groups", {"name": f"T7 {uuid.uuid4().hex[:6]}"}
            )
        return post(pool, y_user, f"{w.base}/access-groups/{archived}/reactivate", {})

    admin = w.engine
    before = deadlocks_now(admin)
    statuses: dict[str, int] = {}
    # both gates are registered before any request starts: a plan refuses a change of the engine's listeners while it is open
    with (
        NthGate(pool.engine, CAMPAIGN_LOCK) as ygate,
        NthGate(pool.engine, AUTHORING_WORLD) as agate,
    ):
        y = run_in_thread("y", y_call)
        assert ygate.reached.wait(WAIT_SECONDS), "SETUP: Y never reached its campaign lock"
        assert ygate.pid is not None
        y_pid = ygate.pid
        a = run_in_thread("a", lambda: author_request(pool, w))
        assert agate.reached.wait(WAIT_SECONDS), "SETUP: the author never reached its world lock"
        assert agate.pid is not None
        a_pid = agate.pid
        wreq = run_in_thread(
            "w", lambda: post(pool, y_user, f"{w.base}/memberships/roles/{w.gm_role}/revoke", {})
        )
        w_wait = observe_waiter(
            admin,
            pattern=ROLE_FOR_UPDATE,
            exclude={y_pid, a_pid},
            blockers_are={y_pid},
            what="V waiting for Y's role rows",
        )
        agate.release()
        if m_first:
            observe_waiter(
                admin,
                pattern=AUTHOR_ROLES,
                exclude={y_pid, w_wait.pid},
                blockers_are={w_wait.pid},
                what="the author waiting for its role row behind V",
            )
        else:
            statuses["a"] = code(finish(a, "the author finishes while Y is parked"))
        ygate.release()
        results = {"y": finish(y, "y finishes"), "w": finish(wreq, "w finishes")}
        if "a" not in statuses:
            results["a"] = finish(a, "a finishes")
    delta = settled_deadlock_delta(admin, pool, before)
    statuses |= {k: code(v) for k, v in results.items()}
    assert statuses["y"] == (201 if route == "create" else 200), statuses
    assert statuses["w"] == 200, statuses
    if m_first:
        # the deferred two-party cycle: exactly one 40P01, at the author's role statement or the revoke's campaign lock
        assert len(pool.failures) == 1 and pool.failures[0][0] == "40P01", (statuses, pool.failures)
        assert delta == 1, (statuses, pool.failures, delta)
        assert 500 in statuses.values(), statuses
    else:
        assert pool.failures == [] and delta == 0, (statuses, pool.failures, delta)
        assert statuses["a"] == 201, statuses


@pytest.mark.parametrize("route", ("create", "reactivate"))
def test_t7a_create_and_reactivate_do_not_wait_for_an_in_flight_keyed_authoring_request(
    route: str, w: World, pool: Pool
) -> None:
    """*race* (T-7a, CA-1): a keyed authoring request is parked right after its reservation INSERT (it holds the campaign `FOR KEY
    SHARE` through the reservation's foreign key). Create and reactivate take the campaign `FOR KEY SHARE`, which does not conflict:
    **they run to completion while the author is still parked**, nothing queued behind the author's backend. (Taken `FOR UPDATE`,
    as the legacy commands did, each would queue behind it: the new instances of the DEF-019 family that CA-1 avoids. The mutation
    "create or reactivate at campaign U" fails this test.)"""
    with w.engine.begin() as c:
        archived = make_access_group(
            c,
            w.campaign_id,
            name=f"T7a archived {uuid.uuid4().hex[:6]}",
            lifecycle_status_code="archived",
        )

    def y_call() -> Any:
        if route == "create":
            return post(
                pool, w.owner, f"{w.base}/access-groups", {"name": f"T7a {uuid.uuid4().hex[:6]}"}
            )
        return post(pool, w.owner, f"{w.base}/access-groups/{archived}/reactivate", {})

    admin = w.engine
    before = deadlocks_now(admin)
    with NthGate(pool.engine, AUTHORING_WORLD) as agate:
        a = run_in_thread("a", lambda: author_request(pool, w))
        assert agate.reached.wait(WAIT_SECONDS), "SETUP: the author never reached its world lock"
        assert agate.pid is not None
        y = run_in_thread("y", y_call)
        deadline = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < deadline and not y.finished():
            assert sessions_blocked_by(admin, agate.pid) == 0, (
                "the group route queued behind the in-flight keyed authoring request"
            )
            time.sleep(0.02)
        assert y.finished(), "the group route did not finish while the author was parked"
        y_status = code(finish(y, "y finishes"))
        agate.release()
        a_status = code(finish(a, "a finishes"))
    delta = settled_deadlock_delta(admin, pool, before)
    assert (y_status, a_status) == ((201 if route == "create" else 200), 201)
    assert pool.failures == [] and delta == 0


def test_t7b_the_two_party_authoring_cycle_with_a_role_revoke_exists_without_any_group_route(
    w: World, pool: Pool
) -> None:
    """*race*, a **characterization** (T-7b, the control of the characterization above): keyed authoring parked after its
    reservation, and the revoke of the author's role by an owner. The revoke locks the author's row and its own, then wants the
    campaign `FOR UPDATE`, which the author's `KEY SHARE` blocks; released, the author wants the row the revoke holds. Exactly one
    40P01, **with no S5-E5 route in the schedule**: the deferred DEF-019 cycle (plan 6.29, CL-E10-1), pre-existing at `0edb94d`."""
    admin = w.engine
    before = deadlocks_now(admin)
    with NthGate(pool.engine, AUTHORING_WORLD) as agate:
        a = run_in_thread("a", lambda: author_request(pool, w))
        assert agate.reached.wait(WAIT_SECONDS), "SETUP: the author never reached its world lock"
        assert agate.pid is not None
        wreq = run_in_thread(
            "w", lambda: post(pool, w.owner, f"{w.base}/memberships/roles/{w.gm_role}/revoke", {})
        )
        observe_waiter(
            admin,
            pattern=r"FROM campaign\.campaigns WHERE .* FOR UPDATE",
            exclude={agate.pid},
            blockers_are={agate.pid},
            what="the revoke waiting for the campaign behind the author",
        )
        agate.release()
        results = {"a": finish(a, "a finishes"), "w": finish(wreq, "w finishes")}
    delta = settled_deadlock_delta(admin, pool, before)
    assert len(pool.failures) == 1 and pool.failures[0][0] == "40P01", pool.failures
    assert delta == 1 and sorted(code(r) for r in results.values()).count(500) == 1


# =====================================================================================================
# pairs: a group route and one other writer, each parked at its final statement in turn
# =====================================================================================================

ARRIVALS = ("group_parked", "other_parked")


def group_call(
    name: str,
    s: Scene,
    e: GEnv,
    pool: Pool,
    *,
    actor: uuid.UUID | None = None,
    group: uuid.UUID | None = None,
) -> Callable[[], Any]:
    path, body = BY_NAME[name].make(s, e)
    if group is not None:
        path = path.replace(str(e.group), str(group)).replace(str(e.archived), str(group))
    user = actor or s.m.manager_user
    return lambda: post(pool, user, path, body)


def open_rows_of_group(sc: Scene, group: uuid.UUID) -> dict[str, int]:
    def count(sql: str) -> int:
        return int(rows(sc.w.engine, sql, g=group)[0]["n"])

    return {
        "links": count(
            "SELECT count(*) AS n FROM security.access_group_memberships WHERE access_group_id = :g AND removed_at IS NULL"
        ),
        "grants": count(
            "SELECT count(*) AS n FROM security.resource_grants WHERE grantee_access_group_id = :g AND revoked_at IS NULL"
        ),
        "revelations": count(
            "SELECT count(*) AS n FROM security.character_revelations WHERE target_access_group_id = :g AND ended_at IS NULL"
        ),
    }


def group_status(sc: Scene, group: uuid.UUID) -> str:
    return str(
        rows(
            sc.w.engine,
            "SELECT ls.code AS code FROM security.access_groups ag JOIN core.lifecycle_statuses ls "
            "ON ls.lifecycle_status_id = ag.lifecycle_status_id WHERE ag.access_group_id = :g",
            g=group,
        )[0]["code"]
    )


def run(
    s: Scene,
    pool: Pool,
    arrival: str,
    group_request: Callable[[], Any],
    other_request: Callable[[], Any],
    *,
    group_gate: str = FINAL,
    other_gate: str = FINAL,
) -> tuple[Any, Any, Any]:
    """Both arrivals; returns (outcome, the group route's response, the other's response). Each party is parked at its own gate
    (default: its final authority statement, every lock held and no write yet)."""
    if arrival == "group_parked":
        o = race(s.w, pool, gate_pattern=group_gate, parked=group_request, second=other_request)
        return o, o.results["parked"], o.results["second"]
    o = race(s.w, pool, gate_pattern=other_gate, parked=other_request, second=group_request)
    return o, o.results["second"], o.results["parked"]


def assert_no_deadlock_only(o: Any, allowed: tuple[str, ...] = ("23505",)) -> None:
    """No 40P01 and an unmoved deadlock counter; the SQLSTATEs in `allowed` (the unique index doing its job) are not failures."""
    bad = [f for f in o.failures if f[0] not in allowed]
    assert not bad, f"unexpected driver exceptions: {o.summary()}"
    assert o.deadlock_delta == 0, f"the deadlock counter moved: {o.summary()}"


def new_group_grant(s: Scene, pool: Pool, group: uuid.UUID) -> Callable[[], Any]:
    with s.w.engine.begin() as c:
        character = make_character(c, s.w.world_id, name=f"pair {uuid.uuid4().hex[:6]}")
    return lambda: post(
        pool,
        s.w.owner,
        f"{s.w.base}/resource-grants",
        {
            "capability_code": "character.view_summary",
            "grantee_access_group_id": str(group),
            "character_id": str(character),
        },
    )


@pytest.mark.parametrize("arrival", ARRIVALS)
@pytest.mark.parametrize("name", ("update", "deactivate", "reactivate", "add"))
def test_a_group_route_and_a_group_grantee_grant_on_the_same_group_serialize_in_both_orders(
    name: str, arrival: str, s: Scene, e: GEnv, pool: Pool
) -> None:
    """*race* (design 10.7 item 1): the route and a grant to **the same group**. The second queues at the group row (the route holds
    it `FOR UPDATE`, the grant takes it `FOR UPDATE`); after the first commits the second proceeds. Deactivate closes a grant that
    committed first and refuses (409) one that arrives after; reactivate refuses (409) a grant that arrives while the group is
    still archived and accepts one that arrives after; update and add never conflict with the grant."""
    group = e.archived if name == "reactivate" else e.group
    o, routed, granted = run(
        s,
        pool,
        arrival,
        group_call(name, s, e, pool),
        new_group_grant(s, pool, group),
        # a grant to an archived group is refused before its final statement: park it holding the group row instead
        other_gate=MEMBERSHIP_S if name == "reactivate" else FINAL,
    )
    assert_clean(o)
    assert code(routed) == BY_NAME[name].status, o.summary()
    group_first = arrival == "group_parked"
    expected_grant = {
        "update": 201,
        "add": 201,
        "deactivate": 409 if group_first else 201,
        "reactivate": 201 if group_first else 409,
    }[name]
    assert code(granted) == expected_grant, o.summary()
    assert o.blocked and all(len(r["blockers"]) == 1 for r in o.blocked), o.summary()
    if name == "deactivate":
        assert open_rows_of_group(s, group)["grants"] == 0 and group_status(s, group) == "archived"


@pytest.mark.parametrize("arrival", ARRIVALS)
def test_the_add_of_the_grant_actor_and_that_actors_group_grant_serialize_in_both_orders(
    arrival: str, s: Scene, e: GEnv, pool: Pool
) -> None:
    """*race* (design 10.7 item 2, the reason the group row precedes the actor's membership): the owner grants to the group
    while another request adds **that owner** to the group. Both arrivals are clean; the grant is 201 and the add is 201."""
    owner_m = owner_membership_of(s.w)
    group_request = group_call(
        "add",
        s,
        e,
        pool,
    )
    path = f"{s.w.base}/access-groups/{e.group}/members"
    group_request = lambda: post(  # noqa: E731
        pool, s.m.manager_user, path, {"campaign_membership_ids": [str(owner_m)]}
    )
    o, added, granted = run(s, pool, arrival, group_request, new_group_grant(s, pool, e.group))
    assert_clean(o)
    assert code(granted) == 201 and code(added) == 201, o.summary()


def _end_member(s: Scene, pool: Pool, member: uuid.UUID) -> Callable[[], Any]:
    return lambda: post(pool, s.w.owner, f"{s.w.base}/memberships/{member}/end", {})


def _revelation_create(s: Scene, e: GEnv, pool: Pool) -> Callable[[], Any]:
    with s.w.engine.begin() as c:
        character = make_character(c, s.w.world_id, name=f"pair rev {uuid.uuid4().hex[:6]}")
    release_profile(s, character)
    return lambda: post(
        pool,
        s.w.owner,
        f"{s.w.base}/characters/{character}/revelations",
        {"audience_kind": "access_group", "target_access_group_id": str(e.group), "reason": "pair"},
    )


DEACTIVATE_PEERS = (
    "add",
    "remove",
    "end_member",
    "revoke_group_grant",
    "revelation_create",
    "revelation_revoke",
)


@pytest.mark.parametrize("arrival", ARRIVALS)
@pytest.mark.parametrize("peer", DEACTIVATE_PEERS)
def test_a_deactivation_and_a_writer_of_its_dependents_serialize_in_both_orders(
    peer: str, arrival: str, s: Scene, e: GEnv, pool: Pool
) -> None:
    """*race* (design 10.7 item 3, the cascade-completeness argument): the deactivation against each creator or closer of the
    dependents it closes (an add, a remove, the end of the member, the revoke of a group grant, a revelation creation for the
    group, the revoke of its revelation). Whatever the order, **the group ends archived with no open link, grant or revelation**
    (creators wait at the group row and are then refused; closers lock one row last and the deactivation finishes the rest), no
    driver exception, the deactivation 200."""
    other: Callable[[], Any]
    if peer == "add":
        other = group_call("add", s, e, pool)
    elif peer == "remove":
        other = group_call("remove", s, e, pool)
    elif peer == "end_member":
        other = _end_member(s, pool, e.members[0])
    elif peer == "revoke_group_grant":
        other = lambda: post(  # noqa: E731
            pool, s.w.owner, f"{s.w.base}/resource-grants/{e.grant}/revoke", {}
        )
    elif peer == "revelation_create":
        other = _revelation_create(s, e, pool)
    else:
        other = lambda: post(  # noqa: E731
            pool,
            s.w.owner,
            f"{s.w.base}/characters/{e.character}/revelations/{e.revelation}/revoke",
            {"reason": "pair"},
        )
    o, deactivated, theirs = run(s, pool, arrival, group_call("deactivate", s, e, pool), other)
    assert_clean(o)
    assert code(deactivated) == 200, o.summary()
    assert code(theirs) in (200, 201, 409), o.summary()
    assert open_rows_of_group(s, e.group) == {"links": 0, "grants": 0, "revelations": 0}, (
        o.summary()
    )
    assert group_status(s, e.group) == "archived"


@pytest.mark.parametrize("arrival", ARRIVALS)
@pytest.mark.parametrize("name", ("create", "reactivate", "add"))
def test_a_widening_route_and_the_campaign_archive_serialize_in_both_orders(
    name: str, arrival: str, s: Scene, e: GEnv, pool: Pool
) -> None:
    """*race* (design 10.7 item 4): create, reactivate and add each take the campaign `FOR KEY SHARE`; the archive takes it `FOR
    UPDATE`. They serialize at the campaign row in both orders, no driver exception: the route first (it commits; the archive then
    commits) or the archive first (the route is refused 409, the campaign not being active, or 404 once the access is gone)."""
    version = rows(
        s.w.engine,
        "SELECT row_version FROM campaign.campaigns WHERE campaign_id = :c",
        c=s.w.campaign_id,
    )[0]["row_version"]
    archive = lambda: post(  # noqa: E731
        pool, s.w.owner, f"{s.w.base}/archive", {"expected_row_version": version, "reason": "pair"}
    )
    o, routed, archived = run(s, pool, arrival, group_call(name, s, e, pool), archive)
    assert_clean(o)
    assert code(archived) == 200, o.summary()
    if arrival == "group_parked":
        assert code(routed) == BY_NAME[name].status, o.summary()
    else:
        assert code(routed) in (403, 404, 409), o.summary()


def _member_pair_other(
    kind: str, s: Scene, e: GEnv, pool: Pool
) -> tuple[Callable[[], Any], uuid.UUID | None]:
    """The other party of an add of `members[1]`, `members[2]` by the manager, and (for the actor cases) the actor to add."""
    manager = s.m.manager_membership
    if kind == "end_added_member":
        return _end_member(s, pool, e.members[1]), None
    if kind == "end_actor":
        return _end_member(s, pool, manager), None
    if kind == "membership_grant_to_added_member":
        with s.w.engine.begin() as c:
            character = make_character(c, s.w.world_id, name=f"pair mg {uuid.uuid4().hex[:6]}")
        return (
            lambda: post(
                pool,
                s.w.owner,
                f"{s.w.base}/resource-grants",
                {
                    "capability_code": "character.view_summary",
                    "grantee_campaign_membership_id": str(e.members[1]),
                    "character_id": str(character),
                },
            ),
            None,
        )
    if kind == "relationship_grant_to_added_member":
        with s.w.engine.begin() as c:
            character = make_character(c, s.w.world_id, name=f"pair rel {uuid.uuid4().hex[:6]}")
        return (
            lambda: post(
                pool,
                s.w.owner,
                f"{s.w.base}/memberships/{e.members[1]}/character-relationships",
                {"character_id": str(character), "relationship_type_code": "viewer"},
            ),
            None,
        )
    if kind == "role_assign_to_actor":
        return (
            lambda: post(
                pool,
                s.w.owner,
                f"{s.w.base}/memberships/{manager}/roles",
                {"role_id": str(s.observer)},
            ),
            None,
        )
    if kind == "role_revoke_of_actor":
        return (
            lambda: post(
                pool, s.w.owner, f"{s.w.base}/memberships/roles/{s.m.manager_role}/revoke", {}
            ),
            None,
        )
    if kind == "transfer_by_actor":
        return (
            lambda: post(
                pool,
                s.w.owner,
                f"{s.w.base}/ownership-transfer",
                transfer_body(e.members[3], False),
            ),
            None,
        )
    raise AssertionError(kind)


ADD_PEERS = (
    "end_added_member",
    "end_actor",
    "membership_grant_to_added_member",
    "relationship_grant_to_added_member",
    "role_assign_to_actor",
    "role_revoke_of_actor",
    "transfer_by_actor",
)


@pytest.mark.parametrize("arrival", ARRIVALS)
@pytest.mark.parametrize("peer", ADD_PEERS)
def test_an_add_and_a_writer_of_a_member_or_of_its_actor_serialize_in_both_orders(
    peer: str, arrival: str, s: Scene, e: GEnv, pool: Pool
) -> None:
    """*race* (design 10.7 item 5): the add (members at `FOR NO KEY UPDATE`, accounts at `FOR KEY SHARE`, campaign at `FOR KEY
    SHARE`) against the end of a member being added or of the actor, a membership-grantee grant or a relationship grant to a member
    being added, a role assign or revoke of the actor, and an ownership transfer: no driver exception, no 500, and the add is
    **all-or-nothing** (201 with both links, or a refusal with none)."""
    other, _ = _member_pair_other(peer, s, e, pool)

    def link_rows() -> int:
        return int(
            rows(
                s.w.engine,
                "SELECT count(*) AS n FROM security.access_group_memberships WHERE access_group_id = :g",
                g=e.group,
            )[0]["n"]
        )

    before = link_rows()
    o, added, theirs = run(s, pool, arrival, group_call("add", s, e, pool), other)
    assert_clean(o)
    assert code(added) in (201, 403, 404, 409), o.summary()
    assert code(theirs) in (200, 201, 403, 404, 409), o.summary()
    # all-or-nothing: both links were created (open or since closed by an end), or neither
    assert link_rows() - before == (2 if code(added) == 201 else 0), o.summary()


@pytest.mark.parametrize("arrival", ARRIVALS)
@pytest.mark.parametrize("peer", ("end_member", "end_actor", "deactivate", "re_add"))
def test_a_remove_and_a_writer_of_its_link_serialize_in_both_orders(
    peer: str, arrival: str, s: Scene, e: GEnv, pool: Pool
) -> None:
    """*race* (design 10.7 item 6): remove against the end of the member (the link's own member), the end of the actor, the
    deactivation of the group, and an add that re-adds the same member (it waits on the unique index, then succeeds). No driver
    exception; the link ends closed in every ordering."""
    other: Callable[[], Any]
    if peer == "end_member":
        other = _end_member(s, pool, e.members[0])
    elif peer == "end_actor":
        other = _end_member(s, pool, s.m.manager_membership)
    elif peer == "deactivate":
        other = group_call("deactivate", s, e, pool)
    else:
        other = lambda: post(  # noqa: E731
            pool,
            s.m.manager_user,
            f"{s.w.base}/access-groups/{e.group}/members",
            {"campaign_membership_ids": e.ids(0)},
        )
    o, removed, theirs = run(
        s,
        pool,
        arrival,
        group_call("remove", s, e, pool),
        other,
        # a re-add queues on the unique index only after the remove's closing UPDATE has run: park it at its audit insert
        group_gate=AUDIT_INSERT if peer == "re_add" else FINAL,
    )
    assert_clean(o)
    assert code(removed) in (200, 403, 404), o.summary()
    assert code(theirs) in (200, 201, 403, 404, 409), o.summary()
    closed = rows(
        s.w.engine,
        "SELECT removed_at IS NOT NULL AS closed FROM security.access_group_memberships "
        "WHERE access_group_membership_id = :l",
        l=e.link,
    )[0]["closed"]
    if code(removed) == 200:
        assert closed, o.summary()


@pytest.mark.parametrize("arrival", ARRIVALS)
@pytest.mark.parametrize("name", ("create", "update", "deactivate", "reactivate", "add", "remove"))
def test_each_route_and_the_revocation_of_the_actors_access_manage_role_serialize_in_both_orders(
    name: str, arrival: str, s: Scene, e: GEnv, pool: Pool
) -> None:
    """*race* (design 10.7 item 7): the route holds the actor's role row `FOR SHARE` until it commits, so the revoke queues behind
    it; a revoke that commits first makes the route refuse (403/404) with **nothing persisted**. No driver exception either way."""
    revoke = lambda: post(  # noqa: E731
        pool, s.w.owner, f"{s.w.base}/memberships/roles/{s.m.manager_role}/revoke", {}
    )
    audits_before = rows(
        s.w.engine,
        "SELECT count(*) AS n FROM audit.change_log WHERE world_id = :w AND command_name = :c",
        w=s.w.world_id,
        c=BY_NAME[name].command,
    )[0]["n"]
    o, routed, revoked = run(s, pool, arrival, group_call(name, s, e, pool), revoke)
    assert_clean(o)
    assert code(revoked) == 200, o.summary()
    audits_after = rows(
        s.w.engine,
        "SELECT count(*) AS n FROM audit.change_log WHERE world_id = :w AND command_name = :c",
        w=s.w.world_id,
        c=BY_NAME[name].command,
    )[0]["n"]
    if arrival == "group_parked":
        assert code(routed) == BY_NAME[name].status, o.summary()
        assert audits_after == audits_before + BY_NAME[name].audits
    else:
        assert code(routed) in (403, 404), o.summary()
        assert audits_after == audits_before


@pytest.mark.parametrize("arrival", ARRIVALS)
def test_two_adds_to_one_group_with_an_overlapping_member_serialize_one_wins_the_other_is_the_409(
    arrival: str, s: Scene, e: GEnv, pool: Pool
) -> None:
    """*race* (design 10.7 item 9): two adds to one group naming one member in common. They serialize at the group row; the first
    commits both links, the second is refused on the open link of the common member (409) with nothing persisted, in both orders."""
    first = lambda: post(  # noqa: E731
        pool,
        s.m.manager_user,
        f"{s.w.base}/access-groups/{e.group}/members",
        {"campaign_membership_ids": e.ids(1, 2)},
    )
    second = lambda: post(  # noqa: E731
        pool,
        s.w.owner,
        f"{s.w.base}/access-groups/{e.group}/members",
        {"campaign_membership_ids": e.ids(2, 3)},
    )
    before = open_rows_of_group(s, e.group)["links"]
    o, a, b = run(s, pool, arrival, first, second)
    assert_no_deadlock_only(
        o
    )  # the loser's INSERT meets the winner's open link: SQLSTATE 23505, the 409
    assert sorted((code(a), code(b))) == [201, 409], o.summary()
    assert open_rows_of_group(s, e.group)["links"] == before + 2, o.summary()


@pytest.mark.parametrize("arrival", ARRIVALS)
def test_two_adds_naming_overlapping_members_in_different_groups_are_both_201(
    arrival: str, s: Scene, e: GEnv, pool: Pool
) -> None:
    """*race* (design 10.7 item 9): the member rows are `FOR NO KEY UPDATE`, so two adds that share a member serialize on it
    (ascending id order, no cycle) and both commit: the groups differ, so no link conflicts."""
    first = lambda: post(  # noqa: E731
        pool,
        s.m.manager_user,
        f"{s.w.base}/access-groups/{e.group}/members",
        {"campaign_membership_ids": e.ids(1, 2)},
    )
    second = lambda: post(  # noqa: E731
        pool,
        s.w.owner,
        f"{s.w.base}/access-groups/{e.other_group}/members",
        {"campaign_membership_ids": e.ids(2, 3)},
    )
    o, a, b = run(s, pool, arrival, first, second)
    assert_clean(o)
    assert code(a) == 201 and code(b) == 201, o.summary()


@pytest.mark.parametrize("arrival", ARRIVALS)
@pytest.mark.parametrize("name", ("add", "create", "reactivate"))
def test_keyed_authoring_by_a_member_and_a_group_route_never_wait_in_a_cycle(
    name: str, arrival: str, s: Scene, e: GEnv, pool: Pool
) -> None:
    """*race* (design 10.7 item 8): keyed authoring (its reservation holds the campaign `FOR KEY SHARE`) by the GM against an add
    of that GM to a group, and against create and reactivate. All three take the campaign `FOR KEY SHARE`, which does not conflict
    with the author's: no driver exception in either order."""
    gm_membership = rows(
        s.w.engine,
        "SELECT campaign_membership_id AS id FROM security.campaign_memberships "
        "WHERE campaign_id = :c AND user_id = :u",
        c=s.w.campaign_id,
        u=s.w.gm_user,
    )[0]["id"]
    if name == "add":
        group_request = lambda: post(  # noqa: E731
            pool,
            s.m.manager_user,
            f"{s.w.base}/access-groups/{e.group}/members",
            {"campaign_membership_ids": [str(gm_membership)]},
        )
    else:
        group_request = group_call(name, s, e, pool)
    author = lambda: author_request(pool, s.w)  # noqa: E731
    if arrival == "group_parked":
        o = race(s.w, pool, gate_pattern=FINAL, parked=group_request, second=author)
        routed, authored = o.results["parked"], o.results["second"]
    else:
        o = race(s.w, pool, gate_pattern=AUTHORING_WORLD, parked=author, second=group_request)
        routed, authored = o.results["second"], o.results["parked"]
    assert_clean(o)
    assert code(routed) == BY_NAME[name].status and code(authored) == 201, o.summary()


def test_the_pause_constant_is_the_shared_patience() -> None:
    """A guard that the shared harness constant these races depend on is still the one the lock-order module defines."""
    assert PATIENCE >= 30


# --- the add against recovery and against invitation acceptance (design 10.7 item 5) ----------------------------------------------


@pytest.mark.parametrize("promoted", ("the_added_member", "another_member"))
@pytest.mark.parametrize("arrival", ("add_parked", "recovery_parked"))
def test_an_add_and_administrative_recovery_serialize_in_both_orders(
    arrival: str, promoted: str, w: World, pool: Pool
) -> None:
    """*race*: recovery (the promoted member's membership `FOR UPDATE`, then the campaign `FOR NO KEY UPDATE`) against an add of a
    member (the member `FOR NO KEY UPDATE`, the campaign `FOR KEY SHARE`), the promoted member being the one added or another.
    Both take the membership before the campaign: no deadlock, the recovery succeeds, the add is all-or-nothing."""
    from dnd_ai.commands.recovery import recover_campaign_access_manager
    from tests.database.test_r01_s5e2_transfer_interactions import (
        RECOVERY_CAMPAIGN_NKU,
        RECOVERY_MEMBERSHIP,
        orchestrate,
        recovery_scene,
    )
    from tests.database.test_r01_s5e2_transfer_interactions import (
        assert_no_deadlock as assert_raw_no_deadlock,
    )

    c_user, _c_m, r_user, r_m, m_user, admin = recovery_scene(w)
    with w.engine.begin() as c:
        group = make_access_group(c, w.campaign_id, name=f"recovery group {uuid.uuid4().hex[:6]}")
    promote_user = r_user if promoted == "the_added_member" else m_user

    def add() -> Any:
        return post(
            pool,
            c_user,
            f"{w.base}/access-groups/{group}/members",
            {"campaign_membership_ids": [str(r_m)]},
        )

    def recovery() -> Any:
        with pool.engine.begin() as connection:
            return recover_campaign_access_manager(
                connection,
                admin_user_id=admin,
                campaign_id=w.campaign_id,
                new_user_id=promote_user,
                reason="S5E5 recovery",
            ).campaign_membership_id

    if arrival == "add_parked":
        raw = orchestrate(w, pool, gate_pattern=FINAL, parked=add, second=recovery)
        added, recovered = raw.results["parked"], raw.results["second"]
    else:
        raw = orchestrate(
            w,
            pool,
            gate_pattern=RECOVERY_CAMPAIGN_NKU
            if promoted == "the_added_member"
            else RECOVERY_MEMBERSHIP,
            nth=1 if promoted == "the_added_member" else 2,
            parked=recovery,
            second=add,
        )
        added, recovered = raw.results["second"], raw.results["parked"]
    assert_raw_no_deadlock(raw)
    assert recovered[0] == "ok", raw.summary()
    assert added[0] in (201, 403, 404, 409), raw.summary()


@pytest.mark.parametrize("arrival", ("accept_parked", "add_parked"))
def test_an_add_and_the_invitation_acceptance_of_an_open_member_serialize_in_both_orders(
    arrival: str, w: World, pool: Pool
) -> None:
    """*race*: an add of member X to a group against X accepting an invitation while X's membership is open (acceptance takes the
    membership `FOR NO KEY UPDATE`, then the campaign `FOR SHARE`; the add takes it `FOR NO KEY UPDATE`, then the campaign `FOR KEY
    SHARE`). No deadlock; the add is 201 and acceptance reports the open membership."""
    from datetime import timedelta

    from dnd_ai.commands.campaign_invitations import (
        accept_campaign_invitation,
        create_campaign_invitation,
    )
    from tests.database.test_r01_s5e2_lock_order import membership_pair
    from tests.database.test_r01_s5e2_transfer_interactions import (
        ACCEPT_CAMPAIGN_SHARE,
        orchestrate,
    )
    from tests.database.test_r01_s5e2_transfer_interactions import (
        assert_no_deadlock as assert_raw_no_deadlock,
    )
    from tests.r01_s5d_support import make_managers

    make_managers(w.engine, w.campaign_id, label="S5E5I")
    cast = membership_pair(
        w, "cmC_below_cmX", "S5E5I", c_roles=("campaign_owner",), x_roles=("player",)
    )
    with w.engine.begin() as c:
        group = make_access_group(c, w.campaign_id, name=f"accept group {uuid.uuid4().hex[:6]}")
        invitation = create_campaign_invitation(
            c, campaign_id=w.campaign_id, invited_by_membership_id=cast.c_m, ttl=timedelta(days=1)
        )

    def accept() -> Any:
        with pool.engine.begin() as connection:
            return accept_campaign_invitation(
                connection, token=invitation.token, accepting_user_id=cast.x_user
            ).campaign_membership_id

    def add() -> Any:
        return post(
            pool,
            cast.c_user,
            f"{w.base}/access-groups/{group}/members",
            {"campaign_membership_ids": [str(cast.x_m)]},
        )

    if arrival == "accept_parked":
        raw = orchestrate(w, pool, gate_pattern=ACCEPT_CAMPAIGN_SHARE, parked=accept, second=add)
        accepted, added = raw.results["parked"], raw.results["second"]
    else:
        raw = orchestrate(w, pool, gate_pattern=FINAL, parked=add, second=accept)
        accepted, added = raw.results["second"], raw.results["parked"]
    assert_raw_no_deadlock(raw)
    assert accepted == ("ok", cast.x_m), raw.summary()
    assert added == (201, None), raw.summary()
