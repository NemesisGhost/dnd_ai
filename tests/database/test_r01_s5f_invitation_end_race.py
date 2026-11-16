# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-F correction: a keyed invitation create against the migrated S5-E3 end route (not the legacy command).

The S5-D invitation tests race the create against the *legacy* `end_campaign_membership` command (labelled legacy
evidence there). This module is the route-level counterpart: the inviting manager A creates an invitation with an
`Idempotency-Key` while the keeper ends A through `POST .../memberships/{id}/end` (keyed as well), in both arrivals:

* `create_parked`: the create is held at its final authority statement (it holds A's membership `FOR KEY SHARE`, the
  campaign `FOR KEY SHARE`, ...). The end starts and **queues behind the create's backend**; the create commits (201,
  invitation, audit row, receipt), then the end commits (200).
* `end_parked`: the end is held before its campaign lock (it holds A's membership `FOR UPDATE`). The create starts and
  **queues behind the end's backend** at A's membership; the end commits (200); the create is then refused (403/404)
  and **nothing durable remains**: no invitation, no audit row, no receipt (the key is reusable).

Asserted: the competitor's blocker is observed (`pg_blocking_pids`, one blocker, the parked pid), no driver exception,
an unmoved deadlock counter, the exact statuses, the durable rows, no idle-in-transaction backend. One pair, bounded:
this is not an exhaustive schedule.
"""

import uuid
from typing import Any

import pytest

from tests.database.test_r01_s2_profile_routes import idle_in_transaction
from tests.database.test_r01_s3_authoring_routes import code, error_of, w  # noqa: F401
from tests.database.test_r01_s5d_invitation_routes import (  # noqa: F401 - autouse fixture by name
    _tidy,
    counts,
)
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixture by name
    Pool,
    assert_clean,
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
from tests.database.test_r01_s5e3_end_membership import (  # noqa: F401 - fixture by name
    CAMPAIGN_U,
    FINAL,
)

pytestmark = pytest.mark.database


def _membership_open(sc: Scene, member: uuid.UUID) -> bool:
    return bool(
        rows(
            sc.w.engine,
            "SELECT ended_at IS NULL AS open FROM security.campaign_memberships "
            "WHERE campaign_membership_id = :m",
            m=member,
        )[0]["open"]
    )


@pytest.mark.parametrize("arrival", ("create_parked", "end_parked"))
def test_a_keyed_invitation_create_and_the_migrated_end_of_the_inviting_manager_serialize(
    arrival: str, s: Scene, pool: Pool
) -> None:
    """*race* (route evidence): see the module docstring. Both requests carry their own `Idempotency-Key`."""
    create_key, end_key = str(uuid.uuid4()), str(uuid.uuid4())
    manager = s.m.manager_membership

    def create() -> Any:
        return post(
            pool,
            s.m.manager_user,
            f"{s.w.base}/invitations",
            {"invited_email": "s5f-guest@example.test"},
            **{"Idempotency-Key": create_key},
        )

    def end() -> Any:
        return post(
            pool,
            s.m.keeper_user,
            f"{s.w.base}/memberships/{manager}/end",
            None,
            **{"Idempotency-Key": end_key},
        )

    before = counts(s.w, create_key)
    if arrival == "create_parked":
        o = race(s.w, pool, gate_pattern=FINAL, parked=create, second=end)
        created, ended = o.results["parked"], o.results["second"]
    else:
        o = race(s.w, pool, gate_pattern=CAMPAIGN_U, parked=end, second=create)
        created, ended = o.results["second"], o.results["parked"]
    assert_clean(o)
    # the competitor queued behind the parked backend, and only behind it
    assert o.blocked and all(len(row["blockers"]) == 1 for row in o.blocked), o.summary()
    assert code(ended) == 200, o.summary()
    assert not _membership_open(s, manager)
    after = counts(s.w, create_key)
    if arrival == "create_parked":
        assert code(created) == 201, o.summary()
        assert after["invitations"] == before["invitations"] + 1
        assert after["audit"] == before["audit"] + 1
        assert after["receipts"] == 1
    else:
        assert code(created) in (403, 404), (code(created), error_of(created), o.summary())
        assert after == before, "a refused create leaves no invitation, audit row or receipt"
    assert idle_in_transaction(s.w.engine) == 0
