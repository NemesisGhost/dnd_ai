# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 O-2 (design 5.3, N-4): the three-party NF-4 cycle (G-3) has an executable reproduction and is serialized.

NF-4 (plan 6.33.7) is a **three-party** wait cycle that every opted-in keyed authoring request closes through its
reservation's immediate campaign foreign key (the common edge E*, design 3.1):

* A (`w.gm_user`, keyed authoring) holds the campaign row `FOR KEY SHARE` (the reservation's FK check) and waits for its
  own role row;
* V (a role writer: the S5-E2 revoke of A's role) holds A's role row `FOR UPDATE` and waits for Y's role row;
* Y (the S5-E1 campaign update) holds its role rows `FOR SHARE` and waits for the campaign row `FOR UPDATE`, which A's
  `KEY SHARE` blocks.

`order = m_row_first` is the schedule with the cycle (A's role row has the lower id, so V locks it first and then waits
for Y's); `y_rows_first` is the control (V waits at Y's row first and holds nothing). At the unchanged source the first
fails with exactly one 40P01 (the fail-before, recorded in the O-2 evidence); after the opt-in A takes the campaign only
at its scope, after its role rows, so Y commits first, V proceeds, and A is refused at its scope by the revoke that
committed: no driver exception, deadlock counter unmoved, the exact serial outcome.
"""

import uuid
from typing import Any

import pytest

from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixture by name
    World,
    w,
)
from tests.database.test_r01_s5e2_authoring_transfer_cycles import AUTHORING_WORLD
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixture by name
    NthGate,
    Pool,
    cast_two,
    deadlocks_now,
    finish,
    pool,
    post,
    rows,
    settled_deadlock_delta,
)
from tests.database.test_r01_s5e5_group_interactions import (
    AUTHOR_ROLES,
    CAMPAIGN_LOCK,
    OK_AUTHORING_RESPONSE,
    OK_REVOKE,
    author_rows,
    keyed_author,
    outcome,
    revoke_rows,
)
from tests.http_race_support import run_in_thread
from tests.r01_s5e5_cycle_support import ROLE_FOR_UPDATE, WAIT_SECONDS, observe_waiter

pytestmark = pytest.mark.database


def _campaign_name(w: World) -> str | None:
    found = rows(
        w.engine, "SELECT name FROM campaign.campaigns WHERE campaign_id = :c", c=w.campaign_id
    )
    return str(found[0]["name"]) if found else None


def _campaign_row_version(w: World) -> int:
    return int(
        rows(
            w.engine,
            "SELECT row_version FROM campaign.campaigns WHERE campaign_id = :c",
            c=w.campaign_id,
        )[0]["row_version"]
    )


@pytest.mark.parametrize("order", ("m_row_first", "y_rows_first"))
def test_n4_the_three_party_nf4_schedule_serializes_in_both_role_id_orders(
    order: str, w: World, pool: Pool
) -> None:
    """*race* (N-4): Y (an owner) updates the campaign (`FOR UPDATE`, parked at its campaign lock, holding its role rows
    `FOR SHARE`); A authors, keyed (parked right after its reservation); V (Y revokes A's `gm` role) waits for Y's role
    rows. Released, A and Y can no longer wait on each other: A holds nothing on the campaign until its scope."""
    m_first = order == "m_row_first"
    cast = cast_two(
        w, label="N4", roles={"r_y": ("c", "campaign_owner", "high:b1" if m_first else "low:b1")}
    )
    y_user = cast.c_user
    assert (w.gm_role < cast.ids["r_y"]) == m_first, (
        "premise: the role-row id order of the schedule"
    )
    new_name = f"N4 renamed {uuid.uuid4().hex[:8]}"
    author_name, author_key = f"N4 dungeon {uuid.uuid4().hex[:8]}", str(uuid.uuid4())
    admin = w.engine
    name_before = _campaign_name(w)
    version = _campaign_row_version(w)
    author_before = author_rows(w, name=author_name, key=author_key)
    revoke_before = revoke_rows(w, revoker=y_user)
    before = deadlocks_now(admin)
    results: dict[str, Any] = {}
    # both gates are registered before any request starts: a plan refuses a change of the engine's listeners while it is open
    with (
        NthGate(pool.engine, CAMPAIGN_LOCK) as ygate,
        NthGate(pool.engine, AUTHORING_WORLD) as agate,
    ):
        y = run_in_thread(
            "y",
            lambda: post(
                pool,
                y_user,
                f"{w.base}/update",
                {"expected_row_version": version, "name": new_name, "description": "d"},
            ),
        )
        assert ygate.reached.wait(WAIT_SECONDS), "SETUP: Y never reached its campaign lock"
        assert ygate.pid is not None
        y_pid = ygate.pid
        a = run_in_thread("a", lambda: keyed_author(pool, w, author_name, author_key))
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
                what="the author waiting for its role row behind V, holding nothing Y wants",
            )
        else:
            results["a"] = finish(a, "the author finishes while Y is parked")
        ygate.release()
        results["y"] = finish(y, "y finishes")
        results["w"] = finish(wreq, "w finishes")
        if "a" not in results:
            results["a"] = finish(a, "a finishes")
    delta = settled_deadlock_delta(admin, pool, before)
    failures = list(pool.failures)
    summary = f"failures={failures} delta={delta} outcomes={ {k: outcome(v) for k, v in results.items()} }"
    assert failures == [] and delta == 0, summary
    assert outcome(results["y"]) == (200, None), summary
    assert outcome(results["w"]) == OK_REVOKE, summary
    assert _campaign_name(w) == new_name, "Y's update committed"
    revoked = revoke_rows(w, revoker=y_user)
    assert revoked["role_row"]["revoked_at"] is not None, summary
    assert len(revoked["audits"]) == len(revoke_before["audits"]) + 1, summary
    state = author_rows(w, name=author_name, key=author_key)
    if m_first:
        # A waited for the row V held; V committed the revoke, so A's scope refuses it with its existing early-check error:
        # nothing authored, no audit row, no reservation (the key is reusable)
        assert outcome(results["a"])[0] == 404, summary
        assert state["entities"] == [] and state["audits"] == [], summary
        assert state["receipts"] == [], summary
    else:
        assert outcome(results["a"]) == OK_AUTHORING_RESPONSE, summary
        assert len(state["entities"]) == 1 and len(state["audits"]) == 1, summary
        assert [r["completed"] for r in state["receipts"]] == [True], summary
    assert author_before["entities"] == [] and name_before != new_name
