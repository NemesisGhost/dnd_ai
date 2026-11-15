# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E2 BA-404: `POST .../memberships/{m}/roles` to a membership that ENDED WHILE THE ASSIGN WAITED answers
404 `not_found`, as the pre-S5-E2 baseline (`0edb94d`) did.

The baseline's 404 was a PostgreSQL EvalPlanQual effect of its joined `FOR UPDATE OF cm` statement: the re-check of the
`cm JOIN membership_statuses` found no row for the ended membership. The S5-E2 plan locks the membership with a plain
`SELECT ... FOR UPDATE` and then reads it fresh, so it sees the ended membership. The restored rule (design section 9)
classifies *only the fresh-read-ineligible-and-status-changed-since-the-unlocked-snapshot case* as "not in campaign";
every other refusal and its precedence are unchanged:

* an already-ended membership (no race) is a 409 `conflict`;
* a membership of another campaign is a 404 `not_found`;
* a recipient whose account was deactivated while the assign waited is a 409 `conflict`;
* `change` and `transfer` keep their 409s (the end-vs-transfer case is in test_r01_s5e2_lock_order.py).

Nothing is persisted by the refused request: no role row, no audit row, no idempotency receipt.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixture by name
    World,
    code,
    error_of,
    w,
)
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixture by name
    END_ACTOR_KEY_SHARE,
    OK200,
    Pool,
    assert_clean,
    live_roles,
    membership_pair,
    pool,
    post,
    race,
    rows,
)
from tests.factories import make_campaign, make_campaign_membership, make_user, system_role_id
from tests.r01_s5d_support import make_managers

pytestmark = pytest.mark.database

ASSIGN_AUDITS = (
    "SELECT count(*) AS n FROM audit.change_log WHERE command_name = 'assign_membership_role' "
    "AND world_id = :w"
)


def assign_audits(w: World) -> int:
    return int(rows(w.engine, ASSIGN_AUDITS, w=w.world_id)[0]["n"])


def receipts(w: World, key: str) -> int:
    return int(
        rows(
            w.engine,
            "SELECT count(*) AS n FROM security.idempotent_requests WHERE idempotency_key = :k",
            k=key,
        )[0]["n"]
    )


def assign(
    p: Pool, w: World, actor: uuid.UUID, target: uuid.UUID, role: uuid.UUID, key: str | None
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    return post(p, actor, f"{w.base}/memberships/{target}/roles", {"role_id": str(role)}, **headers)


@pytest.mark.parametrize("keyed", (False, True))
@pytest.mark.parametrize("order", ("cmC_below_cmX", "cmC_above_cmX"))
def test_assign_to_a_membership_that_ended_while_it_waited_is_a_404_and_persists_nothing(
    order: str, keyed: bool, w: World, pool: Pool
) -> None:
    make_managers(w.engine, w.campaign_id, label="BA404")
    cast = membership_pair(w, order, "BA404", c_roles=("campaign_owner",), x_roles=("player",))
    with w.engine.connect() as c:
        observer = system_role_id(c, "observer")
    key = str(uuid.uuid4()) if keyed else None
    audits = assign_audits(w)
    o = race(
        w,
        pool,
        gate_pattern=END_ACTOR_KEY_SHARE,
        parked=lambda: post(pool, cast.c_user, f"{w.base}/memberships/{cast.x_m}/end"),
        second=lambda: assign(pool, w, cast.c_user, cast.x_m, observer, key),
    )
    assert_clean(o)
    assert o.blocked, f"the assign must have queued behind the end: {o.summary()}"
    assert (o.status("parked"), o.status("second")) == (OK200, (404, "not_found")), o.summary()
    assert "observer" not in live_roles(w.engine, [cast.x_m])
    assert assign_audits(w) == audits, "no audit row"
    if key is not None:
        assert receipts(w, key) == 0, "the refused request left no receipt"
        # the same key, sent again, EXECUTES (it is not a replay of the 404) and now meets an already-ended membership
        again = assign(pool, w, cast.c_user, cast.x_m, observer, key)
        assert (code(again), error_of(again)) == (409, "conflict")
        assert receipts(w, key) == 0
        assert assign_audits(w) == audits


def test_assign_to_an_already_ended_membership_is_a_409_without_any_race(
    w: World, pool: Pool
) -> None:
    make_managers(w.engine, w.campaign_id, label="BA404c")
    cast = membership_pair(
        w, "cmC_below_cmX", "BA404c", c_roles=("campaign_owner",), x_roles=("player",)
    )
    with w.engine.connect() as c:
        observer = system_role_id(c, "observer")
    ended = post(pool, cast.c_user, f"{w.base}/memberships/{cast.x_m}/end")
    assert code(ended) == 200
    audits = assign_audits(w)
    response = assign(pool, w, cast.c_user, cast.x_m, observer, None)
    assert (code(response), error_of(response)) == (409, "conflict")
    assert assign_audits(w) == audits


def test_assign_to_a_membership_of_another_campaign_is_still_a_404(w: World, pool: Pool) -> None:
    make_managers(w.engine, w.campaign_id, label="BA404d")
    cast = membership_pair(
        w, "cmC_below_cmX", "BA404d", c_roles=("campaign_owner",), x_roles=("player",)
    )
    with w.engine.begin() as c:
        timeline = c.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": w.campaign_id},
        ).scalar_one()
        other_campaign = make_campaign(c, timeline, "BA404 other", lifecycle_status_code="pending")
        stranger = make_campaign_membership(c, other_campaign, make_user(c, "BA404 stranger"))
        observer = system_role_id(c, "observer")
    response = assign(pool, w, cast.c_user, stranger, observer, None)
    assert (code(response), error_of(response)) == (404, "not_found")
    missing = assign(pool, w, cast.c_user, uuid.uuid4(), observer, None)
    assert (code(missing), error_of(missing)) == (404, "not_found")


def test_a_recipient_account_deactivated_while_the_assign_waited_is_still_a_409(
    w: World, pool: Pool
) -> None:
    """The membership stays open (its status did not change): the unchanged account check answers 409."""
    from tests.database.test_r01_s5e2_lock_order import ACTOR_ACCOUNT, park_and_probe

    make_managers(w.engine, w.campaign_id, label="BA404e")
    cast = membership_pair(
        w, "cmC_below_cmX", "BA404e", c_roles=("campaign_owner",), x_roles=("player",)
    )
    with w.engine.connect() as c:
        observer = system_role_id(c, "observer")

    def deactivate() -> None:
        with w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.users SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                    "core.lifecycle_statuses WHERE code = 'archived') WHERE user_id = :u"
                ),
                {"u": cast.x_user},
            )

    response, _ = park_and_probe(
        w,
        pool,
        gate_pattern=ACTOR_ACCOUNT,
        request=lambda: assign(pool, w, cast.c_user, cast.x_m, observer, None),
        probes={},
        meanwhile=deactivate,
    )
    assert (code(response), error_of(response)) == (409, "conflict")
    assert "observer" not in live_roles(w.engine, [cast.x_m])
