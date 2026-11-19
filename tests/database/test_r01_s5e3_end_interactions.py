# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E3: the end route against recovery, invitation acceptance, campaign archive and keyed authoring.

The writers of the other module (`test_r01_s5e3_end_races.py`) are routes whose rows the cascade touches. These four reach
the same membership or the same campaign row from the other side:

* **recovery** (`recover_campaign_access_manager`, S5-B: the promoted member's membership `FOR UPDATE`, then the campaign
  `FOR NO KEY UPDATE`) and **invitation acceptance** (S5-B correction: the membership `FOR NO KEY UPDATE`, then the
  campaign `FOR SHARE`): both take the membership before any campaign lock, as the end does, so they serialize at the
  membership. Executed for the removal and the no-op branches of the end (the same coverage boundary as plan 6.29).
* **campaign archive** (the campaign `FOR UPDATE`): conflicts with the end's campaign lock; exactly one wins and
  `finalize` re-resolves the route requirement against the archived campaign.
* **keyed authoring** (the author's role rows and membership): a **serialization regression** since R01 O-2. It was a
  characterized DEF-019 cycle: authoring took the campaign (`KEY SHARE`) first, through its reservation, and the member's
  role rows (`SHARE`) second, while every end (the untouched baseline command and the new route alike) takes the role rows
  (`UPDATE`) first and the campaign (`UPDATE`) later. The reservation no longer locks the campaign (its foreign key is
  deferred), so both arrivals serialize: no driver exception, the deadlock counter unmoved, the end wins, the author is
  refused at its scope with nothing left. At the parent (`369bd8a`) the cases fail with exactly one 40P01.
"""

import re
import uuid
from datetime import timedelta
from typing import Any

import pytest

from dnd_ai.commands.campaign_invitations import (
    accept_campaign_invitation,
    create_campaign_invitation,
)
from dnd_ai.commands.recovery import recover_campaign_access_manager
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixture by name
    World,
    code,
    error_of,
    w,
)
from tests.database.test_r01_s5e2_authoring_transfer_cycles import dungeons, reservations
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixture by name
    ACTOR_ACCOUNT,
    Pool,
    membership_pair,
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
from tests.database.test_r01_s5e2_transfer_interactions import (  # noqa: F401 - fixture by name
    ACCEPT_CAMPAIGN_SHARE,
    RECOVERY_CAMPAIGN_NKU,
    RECOVERY_MEMBERSHIP,
    assert_no_deadlock,
    orchestrate,
    recovery_scene,
)
from tests.database.test_r01_s5e3_end_membership import (  # noqa: F401 - fixture by name
    FINAL,
    _tidy_end,
)
from tests.database.test_r01_s5e3_end_races import FakeResponse
from tests.r01_s5d_support import make_managers

pytestmark = pytest.mark.database

NONE_OPEN = dict.fromkeys(
    ("roles", "delegations", "relationships", "grants", "groups", "revelations", "snapshots"), 0
)
OK200 = (200, None)


def has_manager(w: World) -> bool:
    from sqlalchemy import text

    with w.engine.connect() as c:
        return bool(
            c.execute(
                text("SELECT security.campaign_has_access_manager(:c)"), {"c": w.campaign_id}
            ).scalar_one()
        )


def membership_open(w: World, m: uuid.UUID) -> bool:
    return bool(
        rows(
            w.engine,
            "SELECT ended_at IS NULL AS open FROM security.campaign_memberships "
            "WHERE campaign_membership_id = :m",
            m=m,
        )[0]["open"]
    )


# --- recovery ----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("promoted", ("the_ended_member", "another_member"))
@pytest.mark.parametrize("arrival", ("end_parked", "recovery_parked"))
def test_recovery_against_the_end_serializes_and_never_deadlocks(
    arrival: str, promoted: str, w: World, pool: Pool
) -> None:
    """*race*: the campaign's creator is archived and its actor holds a finite owner row, so recovery may run
    (E8's scene). The finite owner ends member R while recovery promotes R (the same membership: serialize there) or
    another member M (a different membership: serialize, if at all, at the campaign `NO KEY UPDATE` x `UPDATE`). Both
    arrivals; no deadlock; the campaign keeps its manager; R's membership is ended or, when recovery won, promoted and
    ended by the end that follows it (the serial order recovery, end), and never left with an open dependent."""
    c_user, c_m, r_user, r_m, m_user, admin = recovery_scene(w)
    target_user = r_user if promoted == "the_ended_member" else m_user

    def end() -> Any:
        return post(pool, c_user, f"{w.base}/memberships/{r_m}/end")

    def recovery() -> Any:
        with pool.engine.begin() as connection:
            return recover_campaign_access_manager(
                connection,
                admin_user_id=admin,
                campaign_id=w.campaign_id,
                new_user_id=target_user,
                reason="S5E3 recovery",
            ).campaign_membership_id

    if arrival == "end_parked":
        raw = orchestrate(w, pool, gate_pattern=FINAL, parked=end, second=recovery)
        end_result, recovery_result = raw.results["parked"], raw.results["second"]
    else:
        raw = orchestrate(
            w,
            pool,
            gate_pattern=RECOVERY_CAMPAIGN_NKU
            if promoted == "the_ended_member"
            else RECOVERY_MEMBERSHIP,
            nth=1 if promoted == "the_ended_member" else 2,
            parked=recovery,
            second=end,
        )
        end_result, recovery_result = raw.results["second"], raw.results["parked"]
    assert_no_deadlock(raw)
    assert end_result == OK200, raw.summary()
    # recovery always promotes: for the ended member it creates a fresh membership for the same user (the ended one is
    # never reopened), for another member it promotes the open one
    assert recovery_result[0] == "ok", raw.summary()
    assert has_manager(w)
    assert not membership_open(w, r_m)
    assert open_dependents_of(w, r_m) == NONE_OPEN


def open_dependents_of(w: World, member: uuid.UUID) -> dict[str, int]:
    from sqlalchemy import text

    with w.engine.connect() as c:
        return {
            "roles": int(
                c.execute(
                    text(
                        "SELECT count(*) FROM security.membership_roles "
                        "WHERE campaign_membership_id = :m AND revoked_at IS NULL"
                    ),
                    {"m": member},
                ).scalar_one()
            ),
            "delegations": 0,
            "relationships": 0,
            "grants": 0,
            "groups": 0,
            "revelations": 0,
            "snapshots": 0,
        }


# --- invitation acceptance -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("arrival", ("accept_parked", "end_parked"))
def test_reopening_a_membership_by_invitation_against_an_end_of_it_serializes(
    arrival: str, w: World, pool: Pool
) -> None:
    """*race*: member X's membership ended and its user accepts an invitation (reopening it in place) while the owner ends
    it again. Acceptance takes the membership `FOR NO KEY UPDATE` and then the campaign `FOR SHARE`; the end takes the
    membership `FOR UPDATE` first. Acceptance parked (holding the membership): the end queues and then ends the reopened
    membership (serial order: reopen, end). End parked (the documented no-op, holding the membership and the campaign
    `FOR KEY SHARE`): acceptance queues and then reopens (serial order: end, reopen). No deadlock either way."""
    make_managers(w.engine, w.campaign_id, label="S5E3I")
    cast = membership_pair(
        w, "cmC_below_cmX", "S5E3I", c_roles=("campaign_owner",), x_roles=("player",)
    )
    assert code(post(pool, cast.c_user, f"{w.base}/memberships/{cast.x_m}/end")) == 200
    with w.engine.begin() as c:
        invitation = create_campaign_invitation(
            c,
            campaign_id=w.campaign_id,
            invited_by_membership_id=cast.c_m,
            ttl=timedelta(days=1),
        )

    def accept() -> Any:
        with pool.engine.begin() as connection:
            return accept_campaign_invitation(
                connection, token=invitation.token, accepting_user_id=cast.x_user
            ).campaign_membership_id

    def end() -> Any:
        return post(pool, cast.c_user, f"{w.base}/memberships/{cast.x_m}/end")

    if arrival == "accept_parked":
        raw = orchestrate(w, pool, gate_pattern=ACCEPT_CAMPAIGN_SHARE, parked=accept, second=end)
        accept_result, end_result = raw.results["parked"], raw.results["second"]
        expect_open = False
    else:
        raw = orchestrate(w, pool, gate_pattern=FINAL, parked=end, second=accept)
        accept_result, end_result = raw.results["second"], raw.results["parked"]
        expect_open = True
    assert_no_deadlock(raw)
    assert accept_result == ("ok", cast.x_m), raw.summary()
    assert end_result == OK200, raw.summary()
    assert membership_open(w, cast.x_m) is expect_open
    assert open_dependents_of(w, cast.x_m)["roles"] == 0, (
        "a reopened membership starts with no role"
    )


# --- campaign archive ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("arrival", ("end_parked", "archive_parked"))
def test_campaign_archive_against_an_end_serializes_and_one_never_corrupts_the_other(
    arrival: str, w: World, pool: Pool
) -> None:
    """*race*: archive takes the campaign `FOR UPDATE`; the end (removal) takes it `FOR UPDATE` after the member's rows.
    They conflict. End parked: the archive queues, then commits (an active campaign keeps a manager: the end left one);
    archive parked after its campaign lock: the end queues at its campaign lock, then `finalize` re-resolves the route
    requirement against the archived campaign and refuses it (nothing written). No deadlock; the member is ended
    exactly when the end answered 200."""
    managers = make_managers(w.engine, w.campaign_id, label="S5E3A")
    cast = membership_pair(
        w, "cmC_below_cmX", "S5E3A", c_roles=("campaign_owner",), x_roles=("player",)
    )
    version = rows(
        w.engine,
        "SELECT row_version FROM campaign.campaigns WHERE campaign_id = :c",
        c=w.campaign_id,
    )[0]["row_version"]

    def archive() -> Any:
        return post(
            pool,
            managers.manager_user,
            f"{w.base}/archive",
            {"expected_row_version": version, "reason": "S5E3"},
        )

    def end() -> Any:
        return post(pool, cast.c_user, f"{w.base}/memberships/{cast.x_m}/end")

    after_campaign_lock = (
        r"^SELECT c\.name, c\.description, c\.row_version, c\.lifecycle_status_id, c\.timeline_id "
        r"FROM campaign\.campaigns c WHERE c\.campaign_id = \S+$"
    )
    if arrival == "end_parked":
        raw = orchestrate(w, pool, gate_pattern=FINAL, parked=end, second=archive)
        end_result, archive_result = raw.results["parked"], raw.results["second"]
    else:
        raw = orchestrate(w, pool, gate_pattern=after_campaign_lock, parked=archive, second=end)
        end_result, archive_result = raw.results["second"], raw.results["parked"]
    assert_no_deadlock(raw)
    assert archive_result == OK200, raw.summary()
    # end parked: the end commits and the archive follows; archive parked: `finalize` re-resolves the route requirement
    # against the archived campaign and refuses the end (404), which leaves the member's membership and role open
    expected_end = OK200 if arrival == "end_parked" else (404, "not_found")
    assert end_result == expected_end, raw.summary()
    assert (end_result == OK200) is (not membership_open(w, cast.x_m)), raw.summary()
    assert open_dependents_of(w, cast.x_m)["roles"] == (0 if end_result == OK200 else 1)


# --- keyed authoring against the end of its member: serialized by the authoring opt-in (R01 O-2) ------------------------

AUTHORING_WORLD = r"^SELECT lifecycle_status_id FROM core\.worlds WHERE world_id = \S+ FOR SHARE$"
AUTHOR_ROLE_ROWS = re.compile(
    r"^SELECT mr\.membership_role_id FROM security\.membership_roles mr JOIN"
)


@pytest.mark.parametrize("subject", ("new_end", "legacy_end"))
@pytest.mark.parametrize("arrival", ("authoring_parked", "end_parked"))
def test_keyed_authoring_by_the_member_and_the_end_of_the_member_serialize_after_the_authoring_opt_in(
    arrival: str, subject: str, w: World, pool: Pool
) -> None:
    """The author is the GM member (`w.gm_user`) and the owner ends that member. This was the **characterized** DEF-019 cycle
    (one 40P01 at the baseline and at every HEAD until R01 O-2): the keyed authoring request's reservation held the campaign
    `FOR KEY SHARE` while it wanted the member's role rows, which the end held and held while it wanted the campaign
    `FOR UPDATE`. The reservation no longer locks the campaign (its foreign key is deferred; the campaign is first locked at
    the scope, after the role rows and the membership), so the two serialize in both arrivals and the end always wins:

    * `authoring_parked` (parked at its `core.worlds ... FOR SHARE` statement, after its reservation): the end does not wait for
      it at all and commits; the released author is refused at its scope;
    * `end_parked` (parked where every role and membership lock is held, the campaign not yet taken: the account statement of the
      route, the relationship `UPDATE` of the legacy command): the author queues at its role rows behind that backend alone,
      holding nothing on the campaign; released, the end commits and the author is refused.

    `subject=legacy_end` runs the *untouched baseline command* (`end_campaign_membership`) in the same positions: the opt-in is
    the authoring side's. Both: no driver exception, the deadlock counter unmoved, the end a 200 and the membership ended, the
    author a 404 `not_found` (its scope's existing early check) with no authored row, no reservation, and the same key reusable
    (the retry is refused by the route's capability check and still writes nothing)."""
    name = f"S5E3 {uuid.uuid4().hex[:8]}"
    key = str(uuid.uuid4())
    actor = owner_membership_of_owner(w)

    def authoring() -> Any:
        return post(
            pool,
            w.gm_user,
            f"{w.base}/authoring/dungeons",
            {"name": name, "summary": None},
            **{"Idempotency-Key": key},
        )

    def end_new() -> Any:
        return post(pool, w.owner, f"{w.base}/memberships/{w.gm_membership}/end")

    def end_old() -> Any:
        return legacy_end_for(w, pool, w.gm_membership, actor)

    end = end_new if subject == "new_end" else end_old
    if arrival == "authoring_parked":
        o = race(w, pool, gate_pattern=AUTHORING_WORLD, parked=authoring, second=end)
        author_response, end_response = o.results["parked"], o.results["second"]
    else:
        gate = (
            ACTOR_ACCOUNT
            if subject == "new_end"
            else r"^UPDATE security\.membership_character_relationships"
        )
        o = race(w, pool, gate_pattern=gate, parked=end, second=authoring)
        end_response, author_response = o.results["parked"], o.results["second"]
    assert not o.failures, f"driver exceptions (40P01 = deadlock): {o.summary()}"
    assert o.deadlock_delta == 0, o.summary()
    if arrival == "authoring_parked":
        assert o.blocked is None, f"the end waited for the parked author: {o.summary()}"
    else:
        assert o.blocked, f"the author never queued behind the parked end: {o.summary()}"
        for row in o.blocked:
            assert len(row["blockers"]) == 1, f"more than one blocker: {o.summary()}"
            assert AUTHOR_ROLE_ROWS.search(row["query"].strip()), row["query"]
    assert (code(end_response), error_of(end_response)) == (200, None), o.summary()
    assert (code(author_response), error_of(author_response)) == (404, "not_found"), o.summary()
    assert not membership_open(w, w.gm_membership), "the end committed"
    assert dungeons(w, name) == 0, o.summary()
    assert reservations(w, key) == 0, o.summary()
    # the key is reusable: a fresh request is refused by the route's capability check and writes nothing
    again = authoring()
    assert code(again) in (403, 404), again.text
    assert dungeons(w, name) == 0 and reservations(w, key) == 0
    assert not pool.failures, pool.failures


def owner_membership_of_owner(w: World) -> uuid.UUID:
    return rows(
        w.engine,
        "SELECT campaign_membership_id AS id FROM security.campaign_memberships "
        "WHERE campaign_id = :c AND user_id = :u",
        c=w.campaign_id,
        u=w.owner,
    )[0]["id"]


def legacy_end_for(w: World, pool: Pool, target: uuid.UUID, actor_membership: uuid.UUID) -> Any:
    from dnd_ai.commands.memberships import end_campaign_membership

    try:
        with pool.engine.begin() as connection:
            end_campaign_membership(
                connection,
                campaign_membership_id=target,
                campaign_id=w.campaign_id,
                ended_by_membership_id=actor_membership,
            )
    except Exception as exc:  # noqa: BLE001 - the deadlock victim
        return FakeResponse(500, {"error": type(exc).__name__})
    return FakeResponse(200)
