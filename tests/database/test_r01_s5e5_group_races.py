# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E5 correction (AO-1, SA-1; finding NF-1): the group-grantee grant, revelation creation and role writers, after the
correction.

The three parties (`tests/r01_s5e5_cycle_support.py`): **X** creates a grant to an access group (it takes its actor's role rows `FOR
SHARE`, then the group row `FOR UPDATE`); **C** creates a revelation for the group (authority role rows `FOR SHARE`, then the group
`FOR KEY SHARE`); **V** is C's revoke of X's role (one ordered `FOR UPDATE` statement over C's rows and X's row). Before the
correction X locked the group *first* and the three formed a cycle (one SQLSTATE 40P01 per run, a different victim each time);
the S5-E4 parent was clean (T-4, `partA/T4_baseline.log` in the retained evidence).

Every case enforces **arrival**: a party starts only after the previous one is *observed* waiting on the expected backend and
statement (`pg_blocking_pids`, `pg_stat_activity`); nothing assumes a number of queued sessions. A gate that cannot be reached is a
SETUP failure and says so; it is never read as a product outcome. The corrected schedule may block **earlier** than the old
deadlock schedule (X now holds its role rows and the group before it is parked; V waits at the first row it needs), so the gate is
placed *after the group lock* (at X's actor-membership statement) and V is only required to wait on X or on C, holding no row.

Also here: **T-6a**, the rejected class order (the group after the campaign) still deadlocks with the grant, exactly once. The
other rejected order (the actor's membership before the group) is pinned in `test_r01_s5e4_access_races.py`.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from tests.database.test_r01_s2_profile_routes import pooled, pooled_factory  # noqa: F401
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixture by name
    World,
    code,
    w,
)
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixture by name
    Pool,
    pool,
    post,
    race,
    rows,
)
from tests.database.test_r01_s5e2_membership_routes import (  # noqa: F401 - fixture by name
    Scene,
    m,
    s,
)
from tests.database.test_r01_s5e3_end_races import FakeResponse
from tests.database.test_r01_s5e4_access_grants import (  # noqa: F401 - fixture by name
    CAMPAIGN_U,
    Env,
    _tidy,
    build_env,
    env,
)
from tests.factories import make_character
from tests.r01_s5e5_cycle_support import (
    AUTHORITY_ROLES_SHARE,
    GROUP_KEY_SHARE,
    GROUP_LOCK_STATEMENT,
    MEMBERSHIP_FOR_SHARE,
    ROLE_FOR_SHARE,
    ROLE_FOR_UPDATE,
    V_DELEGATIONS,
    assert_clean_in_order_x_c_v,
    assert_no_deadlock,
    assert_v_first_clean,
    build_scene,
    c_request,
    run_cycle_schedule,
    run_pair,
    run_v_first_schedule,
    v_request,
    x_request,
)

pytestmark = pytest.mark.database

ORDERS = ("x_row_below_c_rows", "c_rows_below_x_row")
GROUP_FOR_UPDATE = r"FROM security\.access_groups WHERE .* FOR UPDATE"


def owner_membership_of(w: World) -> uuid.UUID:
    return rows(
        w.engine,
        "SELECT campaign_membership_id AS id FROM security.campaign_memberships "
        "WHERE campaign_id = :c AND user_id = :u",
        c=w.campaign_id,
        u=w.owner,
    )[0]["id"]


def scene(w: World, order: str, label: str):  # type: ignore[no-untyped-def]
    return build_scene(w, w.owner, owner_membership_of(w), order, label)


# --- T-2: the cycle schedule after the correction, both id orders ----------------------------------------------------------------


@pytest.mark.parametrize("order", ORDERS)
def test_t2_the_three_party_schedule_is_clean_after_the_correction(
    order: str, w: World, pool: Pool
) -> None:
    """*race*: X is parked **right after its group lock** (`AfterStatementGate`: its next statement is the actor's membership
    lock, so it holds its role rows `FOR SHARE` and the group `FOR UPDATE`); C is observed waiting at the group `FOR KEY SHARE` on **X's** backend; V is observed waiting at its ordered
    role statement on **X's or C's** backend (whichever holds the row V reaches first: X's row when it is the lower id, C's otherwise)
    **holding no row** (a `NOWAIT` probe shows only the `FOR SHARE` of X and C, never V's `FOR UPDATE`). Released: **no driver
    exception, the deadlock counter unmoved**, X 201, C 201, V 200, completing in the order X, C, V, with all three writes durable."""
    sc = scene(w, order, "T2")
    res = run_cycle_schedule(
        w, pool, sc, park_after=GROUP_LOCK_STATEMENT, v_blockers_within={"x", "c"}
    )
    assert_no_deadlock(
        res
    )  # first: the regression detector (the mutation "group before the role rows" fails here, 40P01)
    assert res.modes == {"x_row": "S", "c_row": "S"}, (
        res.summary()
    )  # V holds neither of the rows it waits for
    waiting_on = res.pids["x"] if order == "x_row_below_c_rows" else res.pids["c"]
    assert res.arrivals["c"].blockers == [res.pids["x"]], res.summary()
    assert res.arrivals["v"].blockers == [waiting_on], res.summary()
    assert_clean_in_order_x_c_v(res)


# --- T-1c: the V-first control, on the corrected tree ------------------------------------------------------------------------------


@pytest.mark.parametrize("order", ORDERS)
def test_t1c_v_first_both_id_orders_after_the_correction(order: str, w: World, pool: Pool) -> None:
    """*race*: V is parked holding X's and C's rows `FOR UPDATE`; X and C are each observed waiting at their role statements on **V's**
    backend (C never reaches the group). Released: V 200, then X refused (its authority was revoked), C 201; no driver exception,
    delta 0."""
    sc = scene(w, order, "T1C")
    assert_v_first_clean(run_v_first_schedule(w, pool, sc))


# --- T-3: pairwise, both arrivals ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("order", ORDERS)
def test_t3_grant_against_revelation_creation_x_parked(order: str, w: World, pool: Pool) -> None:
    """*race*: X parked holding the group; C observed waiting at the group on X; X 201 then C 201."""
    sc = scene(w, order, "T3a1")
    pair = run_pair(
        w,
        pool,
        parked=lambda: x_request(w, pool, sc),
        gate_pattern=MEMBERSHIP_FOR_SHARE,
        second=lambda: c_request(w, pool, sc),
        second_pattern=GROUP_KEY_SHARE,
        names=("x", "c"),
    )
    assert pair.failures == [] and pair.delta == 0, pair
    assert pair.statuses == {"x": (201, None), "c": (201, None)}, pair
    assert pair.ended["x"] <= pair.ended["c"]


@pytest.mark.parametrize("order", ORDERS)
def test_t3_grant_against_revelation_creation_c_parked(order: str, w: World, pool: Pool) -> None:
    """*race*: C parked after its group lock (holding its role rows `FOR SHARE` and the group `FOR KEY SHARE`); X observed waiting at
    the group `FOR UPDATE` on C; C 201 then X 201."""
    sc = scene(w, order, "T3a2")
    pair = run_pair(
        w,
        pool,
        parked=lambda: c_request(w, pool, sc),
        gate_pattern=MEMBERSHIP_FOR_SHARE,
        second=lambda: x_request(w, pool, sc),
        second_pattern=GROUP_FOR_UPDATE,
        names=("c", "x"),
    )
    assert pair.failures == [] and pair.delta == 0, pair
    assert pair.statuses == {"c": (201, None), "x": (201, None)}, pair
    assert pair.ended["c"] <= pair.ended["x"]


@pytest.mark.parametrize("order", ORDERS)
def test_t3_grant_against_the_revoke_of_the_grant_actors_role_x_parked(
    order: str, w: World, pool: Pool
) -> None:
    """*race*: X parked after its group lock (holding its role rows `FOR SHARE`); V observed waiting for X's row on X; X 201 then V
    200 (the revoke acts after the grant)."""
    sc = scene(w, order, "T3b1")
    pair = run_pair(
        w,
        pool,
        parked=lambda: x_request(w, pool, sc),
        gate_pattern=MEMBERSHIP_FOR_SHARE,
        second=lambda: v_request(w, pool, sc),
        second_pattern=ROLE_FOR_UPDATE,
        names=("x", "v"),
    )
    assert pair.failures == [] and pair.delta == 0, pair
    assert pair.statuses == {"x": (201, None), "v": (200, None)}, pair
    assert pair.ended["x"] <= pair.ended["v"]


@pytest.mark.parametrize("order", ORDERS)
def test_t3_grant_against_the_revoke_of_the_grant_actors_role_v_parked(
    order: str, w: World, pool: Pool
) -> None:
    """*race*: V parked holding X's and C's rows `FOR UPDATE`; X observed waiting at its role `FOR SHARE` on V, holding nothing
    (it has not reached the group); V 200 then X refused, no grant."""
    sc = scene(w, order, "T3b2")
    pair = run_pair(
        w,
        pool,
        parked=lambda: v_request(w, pool, sc),
        gate_pattern=V_DELEGATIONS,
        second=lambda: x_request(w, pool, sc),
        second_pattern=ROLE_FOR_SHARE,
        names=("v", "x"),
    )
    assert pair.failures == [] and pair.delta == 0, pair
    assert pair.statuses["v"] == (200, None) and pair.statuses["x"][0] in (403, 404), pair
    assert (
        rows(
            w.engine,
            "SELECT count(*) AS n FROM security.resource_grants WHERE grantee_access_group_id = :g",
            g=sc.group,
        )[0]["n"]
        == 0
    )


@pytest.mark.parametrize("order", ORDERS)
def test_t3_revelation_creation_against_the_revoke_of_its_callers_role_c_parked(
    order: str, w: World, pool: Pool
) -> None:
    """*race*: C parked after its group lock (holding its role rows `FOR SHARE`); the revoke of C's role (by X) observed waiting for
    C's row on C; C 201 then the revoke 200."""
    sc = scene(w, order, "T3c1")
    pair = run_pair(
        w,
        pool,
        parked=lambda: c_request(w, pool, sc),
        gate_pattern=MEMBERSHIP_FOR_SHARE,
        second=lambda: post(
            pool, sc.cast.x_user, f"{w.base}/memberships/roles/{sc.r_c}/revoke", {}
        ),
        second_pattern=ROLE_FOR_UPDATE,
        names=("c", "v"),
    )
    assert pair.failures == [] and pair.delta == 0, pair
    assert pair.statuses == {"c": (201, None), "v": (200, None)}, pair
    assert pair.ended["c"] <= pair.ended["v"]


@pytest.mark.parametrize("order", ORDERS)
def test_t3_revelation_creation_against_the_revoke_of_its_callers_role_revoke_parked(
    order: str, w: World, pool: Pool
) -> None:
    """*race*: the revoke of C's role (by X) parked holding both rows `FOR UPDATE`; C observed waiting at its authority role statement
    on the revoke; the revoke 200 then C refused (no revelation)."""
    sc = scene(w, order, "T3c2")
    pair = run_pair(
        w,
        pool,
        parked=lambda: post(
            pool, sc.cast.x_user, f"{w.base}/memberships/roles/{sc.r_c}/revoke", {}
        ),
        gate_pattern=V_DELEGATIONS,
        second=lambda: c_request(w, pool, sc),
        second_pattern=AUTHORITY_ROLES_SHARE,
        names=("v", "c"),
    )
    assert pair.failures == [] and pair.delta == 0, pair
    assert pair.statuses["v"] == (200, None) and pair.statuses["c"][0] in (403, 404), pair
    assert (
        rows(
            w.engine,
            "SELECT count(*) AS n FROM security.character_revelations WHERE target_access_group_id = :g",
            g=sc.group,
        )[0]["n"]
        == 0
    )


# --- T-6a: the rejected class order still deadlocks ----------------------------------------------------------------------------------


@pytest.mark.parametrize("route", ("update", "deactivate"))
def test_t6a_the_rejected_class_order_still_deadlocks_with_the_group_grantee_grant_exactly_once(
    route: str, s: Scene, env: Env, pool: Pool
) -> None:
    """*race*: the group-grantee grant (corrected: role rows, then the group `FOR UPDATE`) is parked at its campaign `FOR UPDATE`. A
    request that follows the **rejected** class order for `update` or `deactivate` (the campaign `FOR KEY SHARE`, *then* the group
    row) queues at the group row holding the campaign `KEY SHARE`; released, the grant wants the campaign `FOR UPDATE`, which that
    `KEY SHARE` blocks: a cycle, aborted with exactly one SQLSTATE 40P01 (the counter moves by one). The group still precedes the
    campaign; the other rejected order (the actor's membership before the group) is pinned in `test_r01_s5e4_access_races.py`."""
    with s.w.engine.begin() as c:
        character = make_character(c, s.w.world_id, name="T6a character")

    def rejected_order() -> Any:
        try:
            with pool.engine.begin() as c:
                c.execute(
                    text("SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c FOR KEY SHARE"),
                    {"c": s.w.campaign_id},
                )
                c.execute(
                    text(
                        "SELECT 1 FROM security.access_groups WHERE access_group_id = :g FOR UPDATE"
                    ),
                    {"g": env.group},
                )
                if route == "update":
                    c.execute(
                        text(
                            "UPDATE security.access_groups SET description = 't6a' WHERE access_group_id = :g"
                        ),
                        {"g": env.group},
                    )
        except Exception as exc:  # noqa: BLE001 - the deadlock victim
            return FakeResponse(500, {"error": type(exc).__name__})
        return FakeResponse(200)

    o = race(
        s.w,
        pool,
        gate_pattern=CAMPAIGN_U,
        parked=lambda: post(
            pool,
            s.w.owner,
            f"{s.w.base}/resource-grants",
            {
                "capability_code": "character.view_summary",
                "grantee_access_group_id": str(env.group),
                "character_id": str(character),
            },
        ),
        second=rejected_order,
    )
    assert o.blocked and all(len(r["blockers"]) == 1 for r in o.blocked), o.summary()
    assert any("access_groups" in r["query"] for r in o.blocked), o.summary()
    assert len(o.failures) == 1 and o.failures[0][0] == "40P01", o.summary()
    assert o.deadlock_delta == 1, o.summary()
    codes = sorted(code(o.results[n]) for n in ("parked", "second"))
    assert 500 in codes and len(codes) == 2, o.summary()
