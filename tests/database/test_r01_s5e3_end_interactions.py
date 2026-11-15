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
* **keyed authoring** (the author's role rows and membership, with the campaign `FOR KEY SHARE` from its reservation): a
  **characterization**, not a regression. Authoring takes the campaign (`KEY SHARE`) first and the member's role rows
  (`SHARE`) second, while every end (the untouched baseline command and the new route alike) takes the role rows
  (`UPDATE`) first and the campaign (`UPDATE`) later: the cycle exists at the baseline and is **deferred under DEF-019**
  (the authoring opt-in slice, plan 6.21.7, required before A6 and R01 closure). Each case asserts exactly one 40P01 on a
  cycle-edge statement, the 500 on the request whose statement failed, deadlock delta 1, and that the loser rolled back
  completely; the victim is not pinned (PostgreSQL chooses). A pass means the defect was characterized, not fixed.
"""

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


# --- keyed authoring: a characterization of a deferred cycle --------------------------------------------------------------

AUTHORING_WORLD = r"^SELECT lifecycle_status_id FROM core\.worlds WHERE world_id = \S+ FOR SHARE$"


@pytest.mark.parametrize("subject", ("new_end", "legacy_end"))
@pytest.mark.parametrize("arrival", ("authoring_parked", "end_parked"))
def test_characterized_keyed_authoring_by_the_member_and_the_end_of_the_member_wait_in_a_cycle_at_the_baseline_too(
    arrival: str, subject: str, w: World, pool: Pool
) -> None:
    """**Characterization (deferred cycle DEF-019, not a fix)**: the author is the GM member (`w.gm_user`) and the owner
    ends that member. Order `authoring_parked`: the keyed authoring request is parked at its `core.worlds ... FOR
    SHARE` statement (after its reservation `INSERT`, holding the campaign `FOR KEY SHARE`); the end takes the member's
    role rows `FOR UPDATE` and the membership and then wants the campaign `FOR UPDATE`; the authoring request, released,
    wants those role rows. Order `end_parked`: the end is parked at its account statement (every role and membership
    lock held, the campaign not yet); the authoring request takes the campaign `FOR KEY SHARE` and then wants the role
    rows. `subject=legacy_end` runs the *untouched baseline command* (`end_campaign_membership`) in the same positions
    and shows the same 40P01, so S5-E3 introduced no new cycle. Exactly one request is the victim of one 40P01; the
    victim rolled back whole (no authored row for the authoring victim, the membership still open for the end victim)."""
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
    else:
        gate = (
            ACTOR_ACCOUNT
            if subject == "new_end"
            else r"^UPDATE security\.membership_character_relationships"
        )
        o = race(w, pool, gate_pattern=gate, parked=end, second=authoring)
    assert len(o.failures) == 1 and o.failures[0][0] == "40P01", o.summary()
    assert o.deadlock_delta == 1, o.summary()
    codes = sorted(code(o.results[n]) for n in ("parked", "second"))
    assert 500 in codes and len(codes) == 2, o.summary()
    ended = not membership_open(w, w.gm_membership)
    authored = dungeons(w, name)
    # exactly one of the two committed; the victim left nothing behind (a rolled-back authoring request leaves no
    # authored row and no reservation, a rolled-back end leaves the membership open)
    assert ended != (authored == 1), (ended, authored, o.summary())
    assert reservations(w, key) == (1 if authored == 1 else 0), o.summary()


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
