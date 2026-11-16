# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E4: the five routes against every writer their lock sets touch, both transaction orderings.

Every case drives real routes over real connections (the 8-connection `pool` of the S5-E2 lock-order module), parks one
request on a named statement, starts the other, observes (`pg_blocking_pids`) that it queued behind the parked backend,
releases, and then asserts: no driver exception and no moved deadlock counter (`assert_clean`), the exact statuses, and
the invariant the pair must keep.

Two kinds of test live here and must not be confused (the S5-E2 E10 distinction):

1. **Regressions** (`test_*` without `characterized`): clean at HEAD, ordinary passing tests. This includes the pair the
   S5-E3 slice **retained** because the change route was still pending (`POST .../character-relationships/{id}/change`
   against the end of the member): at the parent the pair deadlocks (the untouched end command and the new end alike,
   SQLSTATE 40P01); here it is shown **clean in both orderings** after the change was migrated, and the retained
   characterization of the parent is replaced by this disposition.
2. **Characterizations** (`test_characterized_*`): cycles that exist at the untouched baseline too (the legacy command
   shows the same 40P01) and belong to the deferred authoring opt-in (DEF-019, plan 6.21.7). A pass means the pre-existing
   defect is *characterized, not fixed*; it fails when the cycle disappears, forcing reclassification.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from tests.database.test_r01_s2_profile_routes import pooled, pooled_factory  # noqa: F401
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixture by name
    World,
    code,
    error_of,
    w,
)
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixture by name
    ACTOR_ACCOUNT,
    Pool,
    assert_clean,
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
    RECOVERY_CAMPAIGN_NKU,
    RECOVERY_MEMBERSHIP,
    assert_no_deadlock,
    orchestrate,
    recovery_scene,
)
from tests.database.test_r01_s5e3_end_membership import (  # noqa: F401 - fixture by name
    Member,
    _tidy_end,
    build_member,
    e,
    open_dependents,
    state,
)
from tests.database.test_r01_s5e3_end_races import (
    FakeResponse,
    end_request,
    legacy_end,
    other_type_for,
    owner_membership,
)
from tests.database.test_r01_s5e4_access_grants import (  # noqa: F401 - fixture by name
    AUDIT_INSERT,
    CAMPAIGN_U,
    FINAL,
    GROUP_U,
    MEMBERSHIP_U,
    RELATIONSHIP_U,
    Env,
    _tidy,
    build_env,
    env,
    snap,
)
from tests.factories import make_character

pytestmark = pytest.mark.database

OK200 = (200, None)
NONE_OPEN = {
    "roles": 0,
    "delegations": 0,
    "relationships": 0,
    "grants": 0,
    "groups": 0,
    "revelations": 0,
    "snapshots": 0,
}
END_RELATIONSHIPS = r"FROM security\.membership_character_relationships WHERE .* FOR UPDATE$"
LEGACY_END_UPDATES_RELATIONSHIPS = r"^UPDATE security\.membership_character_relationships"


def change_request(s: Scene, pool: Pool, env: Env, actor: uuid.UUID | None = None) -> Any:
    return post(
        pool,
        actor or s.w.owner,
        f"{s.w.base}/character-relationships/{env.relationship}/change",
        {"new_relationship_type_id": str(env.co_controller)},
    )


def membership_open(s: Scene, member: uuid.UUID) -> bool:
    return bool(
        rows(
            s.w.engine,
            "SELECT ended_at IS NULL AS open FROM security.campaign_memberships "
            "WHERE campaign_membership_id = :m",
            m=member,
        )[0]["open"]
    )


def open_rows(s: Scene, member: uuid.UUID) -> dict[str, int]:
    return open_dependents(s, member)


# --- the retained pair: change against the end of the member --------------------------------------------------------------


@pytest.mark.parametrize("subject", ("new_end", "legacy_end"))
@pytest.mark.parametrize("arrival", ("end_parked", "change_parked"))
def test_changing_a_relationship_and_ending_its_member_no_longer_wait_in_a_cycle(
    arrival: str, subject: str, s: Scene, e: Member, pool: Pool
) -> None:
    """*race*, the pair S5-E3 retained: before this slice the change locked the relationship row and then the member's
    membership (`FOR UPDATE OF mcr, cm`) while every end locked the membership and then the relationship rows, so the
    two deadlocked (SQLSTATE 40P01, one 500). The change now takes the owning membership `FOR UPDATE` **before** the
    relationship row, the order every end takes: the pair serializes at the membership.

    Both arrivals, each against the new end and the untouched baseline end command (`legacy_end`, which takes the
    membership and then updates the relationships). `end_parked`: the end holds the membership and the campaign and is
    parked where it takes the relationship rows (the legacy command at its relationship UPDATE); the change queues at
    the membership `FOR UPDATE` behind the end's backend, then judges the ended member and is refused (404 `not_found`, the baseline's join-recheck answer). `change_parked`:
    the change holds the membership, campaign, type, entity and character rows and is parked at its relationship row lock;
    the end queues at the membership behind the change's backend, then closes what is left (the change's new row too). No
    driver error, the deadlock counter does not move, and no relationship stays open."""
    other = Env(
        user=e.user,
        membership=e.membership,
        character=e.character,
        other_character=e.character,
        portrayer=e.relationship_type,
        co_controller=other_type_for(s),
        relationship=e.relationship,
        grant=e.grant,
        group=e.group,
        capability=e.capability,
    )
    actor = owner_membership(s)

    def change() -> Any:
        return change_request(s, pool, other)

    def end_new() -> Any:
        return end_request(s, pool, e.membership)

    def end_old() -> Any:
        return legacy_end(s, pool, e.membership, actor)

    end = end_new if subject == "new_end" else end_old
    if arrival == "end_parked":
        gate = END_RELATIONSHIPS if subject == "new_end" else LEGACY_END_UPDATES_RELATIONSHIPS
        o = race(s.w, pool, gate_pattern=gate, parked=end, second=change)
        end_status, change_status = o.status("parked"), o.status("second")
    else:
        o = race(s.w, pool, gate_pattern=RELATIONSHIP_U, parked=change, second=end)
        end_status, change_status = o.status("second"), o.status("parked")
    assert_clean(o)
    assert o.blocked and all(len(row["blockers"]) == 1 for row in o.blocked), o.summary()
    assert any(
        "campaign_memberships" in row["query"] and "FOR UPDATE" in row["query"] for row in o.blocked
    ), o.summary()
    assert end_status == OK200 or end_status[0] == 200, o.summary()
    if arrival == "end_parked":
        assert change_status == (404, "not_found"), o.summary()
    else:
        assert change_status[0] == 201, o.summary()
    assert open_rows(s, e.membership) == NONE_OPEN
    assert not membership_open(s, e.membership)
    assert idle(s) == 0


def idle(s: Scene) -> int:
    from tests.database.test_r01_s2_profile_routes import idle_in_transaction

    return idle_in_transaction(s.w.engine)


# --- creators against the end, closers against the end -------------------------------------------------------------------


@pytest.mark.parametrize("creator", ("grant_relationship", "create_grant"))
@pytest.mark.parametrize("arrival", ("end_parked", "creator_parked"))
def test_a_creator_and_the_end_of_its_member_serialize_in_both_orders(
    arrival: str, creator: str, s: Scene, pool: Pool
) -> None:
    """*race*: the migrated creator against the end. `end_parked` (every lock of its declaration held): the creator
    queues at the target membership, then judges the ended member and is refused (404 `not_found`/409). `creator_parked` (its
    row inserted, uncommitted): the end queues at the membership behind it and then closes the row the creator added.
    No deadlock, no open dependent row either way."""
    target = build_member(s, "S5E4 Creator")
    with s.w.engine.begin() as c:
        fresh = make_character(c, s.w.world_id, name="S5E4 Race character")
    if creator == "grant_relationship":
        path = f"{s.w.base}/memberships/{target.membership}/character-relationships"
        body: dict[str, Any] = {"character_id": str(fresh), "relationship_type_code": "viewer"}
    else:
        path = f"{s.w.base}/resource-grants"
        body = {
            "capability_code": "character.view_summary",
            "grantee_campaign_membership_id": str(target.membership),
            "character_id": str(fresh),
        }

    def create() -> Any:
        return post(pool, s.w.owner, path, body)

    def end() -> Any:
        return end_request(s, pool, target.membership)

    if arrival == "end_parked":
        o = race(s.w, pool, gate_pattern=FINAL, parked=end, second=create)
        created, ended = o.results["second"], o.results["parked"]
        assert code(created) in (404, 409), o.summary()
    else:
        o = race(s.w, pool, gate_pattern=AUDIT_INSERT, parked=create, second=end)
        created, ended = o.results["parked"], o.results["second"]
        assert code(created) == 201, o.summary()
    assert_clean(o)
    assert o.blocked and all(len(row["blockers"]) == 1 for row in o.blocked), o.summary()
    assert code(ended) == 200, o.summary()
    assert open_rows(s, target.membership) == NONE_OPEN
    assert not membership_open(s, target.membership)


# --- the same row from two requests -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("arrival", ("first_parked", "second_parked"))
@pytest.mark.parametrize(
    "pair", ("change_change", "change_revoke", "revoke_change", "revoke_revoke")
)
def test_two_requests_for_one_relationship_serialize_without_a_cycle(
    pair: str, arrival: str, s: Scene, env: Env, pool: Pool
) -> None:
    """*race*: the same relationship from two requests, both arrivals. A change that arrives after another closed the row
    is the unchanged 409; a revoke after another closed it is the documented no-op 200; a change after a revoke is 409. No
    cycle: the revoke holds the campaign `FOR KEY SHARE` and the row, the change holds the membership, the campaign
    `FOR UPDATE` and then the row, and neither waits for what the other holds first."""
    base = s.w.base
    change_path = f"{base}/character-relationships/{env.relationship}/change"
    revoke_path = f"{base}/character-relationships/{env.relationship}/revoke"
    body = {"new_relationship_type_id": str(env.co_controller)}

    def req(kind: str) -> Any:
        return (
            post(pool, s.w.owner, change_path, body)
            if kind == "change"
            else post(pool, s.w.owner, revoke_path, {})
        )

    first, second = pair.split("_")
    if arrival == "first_parked":
        o = race(
            s.w,
            pool,
            gate_pattern=AUDIT_INSERT,
            parked=lambda: req(first),
            second=lambda: req(second),
        )
        first_status, second_status = o.status("parked"), o.status("second")
    else:
        o = race(
            s.w,
            pool,
            gate_pattern=AUDIT_INSERT,
            parked=lambda: req(second),
            second=lambda: req(first),
        )
        first_status, second_status = o.status("second"), o.status("parked")
    assert_clean(o)
    assert o.blocked and all(len(row["blockers"]) == 1 for row in o.blocked), o.summary()
    # whichever committed first closed the row; the other finds it closed
    wins = {"change": 201, "revoke": 200}
    statuses = {first: first_status, second: second_status} if first != second else {}
    committed = [c for c in (first_status, second_status) if c[0] in (200, 201)]
    assert committed, o.summary()
    if first == second == "change":
        assert sorted(c[0] for c in (first_status, second_status)) == [201, 409], o.summary()
    elif first == second == "revoke":
        assert first_status[0] == second_status[0] == 200, o.summary()
    else:
        assert statuses["revoke"][0] == 200, o.summary()
        assert statuses["change"][0] in (201, 409), o.summary()
    del wins
    assert sum(1 for r in snap(s).relationships if r[0] == env.relationship and r[1]) == 1


def test_two_creates_of_the_same_grant_one_commits_and_the_other_is_the_unchanged_409(
    s: Scene, env: Env, pool: Pool
) -> None:
    """*race*, `ux_resource_grants_active`: two identical creates. Both lock the same membership, so the second queues at
    the membership behind the first (not at the index) and then meets the unique index: the unchanged 409. One grant."""
    with s.w.engine.begin() as c:
        fresh = make_character(c, s.w.world_id, name="S5E4 Twin")
    path = f"{s.w.base}/resource-grants"
    body = {
        "capability_code": "character.view_summary",
        "grantee_campaign_membership_id": str(env.membership),
        "character_id": str(fresh),
    }

    def create() -> Any:
        return post(pool, s.w.owner, path, body)

    o = race(s.w, pool, gate_pattern=AUDIT_INSERT, parked=create, second=create)
    # the loser's unique violation (23505) is the one expected driver exception; never a deadlock
    assert [f[0] for f in o.failures] == ["23505"] and o.deadlock_delta == 0, o.summary()
    assert o.blocked and all(len(row["blockers"]) == 1 for row in o.blocked), o.summary()
    assert sorted(code(o.results[n]) for n in ("parked", "second")) == [201, 409], o.summary()
    assert (
        len([g for g in snap(s).grants if not g[1]]) == 2
    )  # the fixture grant and the one new row


# --- the group grantee -----------------------------------------------------------------------------------------------------------------


def group_grant_request(s: Scene, pool: Pool, env: Env, character: uuid.UUID) -> Any:
    return post(
        pool,
        s.w.owner,
        f"{s.w.base}/resource-grants",
        {
            "capability_code": "character.view_summary",
            "grantee_access_group_id": str(env.group),
            "character_id": str(character),
        },
    )


DEACTIVATE_UPDATE = r"^UPDATE security\.access_groups SET lifecycle_status_id"
ADD_MEMBERS_NKU = r"FROM security\.campaign_memberships .* FOR NO KEY UPDATE"


@pytest.mark.parametrize("arrival", ("grant_parked", "deactivate_parked"))
def test_a_group_grant_and_the_deactivation_of_the_group_serialize_in_both_orders(
    arrival: str, s: Scene, env: Env, pool: Pool
) -> None:
    """*race*: the deactivation (a still-pending route: the group row, then bulk updates of the group's links and grants)
    against a grant to that group. `grant_parked` (the group row `FOR UPDATE` held): the deactivation queues at the group
    row, then closes the new grant with the others. `deactivate_parked` (the group row held, the group updated): the grant
    queues at its **first** lock, the group row, then judges the inactive group and is refused with the unchanged 409. No
    cycle: the grant holds nothing before the group row, and the deactivation never waits for anything the grant holds."""
    with s.w.engine.begin() as c:
        fresh = make_character(c, s.w.world_id, name="S5E4 Group character")
    grant = lambda: group_grant_request(s, pool, env, fresh)  # noqa: E731

    def deactivate() -> Any:
        return post(pool, s.w.owner, f"{s.w.base}/access-groups/{env.group}/deactivate", {})

    if arrival == "grant_parked":
        o = race(s.w, pool, gate_pattern=FINAL, parked=grant, second=deactivate)
        granted, deactivated = o.results["parked"], o.results["second"]
        assert code(granted) == 201 and code(deactivated) == 200, o.summary()
        open_group_grants = rows(
            s.w.engine,
            "SELECT count(*) AS n FROM security.resource_grants WHERE grantee_access_group_id = :g "
            "AND revoked_at IS NULL",
            g=env.group,
        )[0]["n"]
        assert open_group_grants == 0, "the deactivation closed the new grant too"
    else:
        o = race(s.w, pool, gate_pattern=DEACTIVATE_UPDATE, parked=deactivate, second=grant)
        granted, deactivated = o.results["second"], o.results["parked"]
        assert code(deactivated) == 200 and code(granted) == 409, o.summary()
    assert_clean(o)
    assert o.blocked and all(len(row["blockers"]) == 1 for row in o.blocked), o.summary()
    assert any("access_groups" in row["query"] for row in o.blocked), o.summary()


@pytest.mark.parametrize("arrival", ("grant_parked", "add_members_parked"))
def test_a_group_grant_by_a_manager_who_is_being_added_to_the_group_never_waits_in_a_cycle(
    arrival: str, s: Scene, env: Env, pool: Pool
) -> None:
    """*race*, the reason the group row precedes the actor's membership (R01 S5-E4 correction SA-1: it follows only the actor's role rows): the owner grants to the group while another request adds that
    **owner** to the group. The add (a still-pending route) holds the group row `FOR UPDATE` and then takes the added
    member's membership `FOR NO KEY UPDATE`, which conflicts with the grant's `FOR SHARE` on the actor's own membership.
    A grant that took the actor's membership before the group row would hold the one and wait for the other while the add
    held the other and waited for the first. With the group row first the pair serializes at the group row, both arrivals."""
    owner_m = owner_membership(s)
    with s.w.engine.begin() as c:
        fresh = make_character(c, s.w.world_id, name="S5E4 Added character")
    grant = lambda: group_grant_request(s, pool, env, fresh)  # noqa: E731
    add = lambda: post(  # noqa: E731
        pool,
        s.m.manager_user,
        f"{s.w.base}/access-groups/{env.group}/members",
        {"campaign_membership_ids": [str(owner_m)]},
    )
    if arrival == "grant_parked":
        o = race(s.w, pool, gate_pattern=FINAL, parked=grant, second=add)
        granted, added = o.results["parked"], o.results["second"]
    else:
        o = race(s.w, pool, gate_pattern=ADD_MEMBERS_NKU, parked=add, second=grant)
        granted, added = o.results["second"], o.results["parked"]
    assert_clean(o)
    assert code(granted) == 201, o.summary()
    assert code(added) in (200, 201), o.summary()


def test_taking_the_actors_membership_before_the_group_row_would_deadlock_with_the_add_of_that_actor(
    s: Scene, env: Env, pool: Pool
) -> None:
    """*race* (why the group is first, shown by the opposite order): two raw transactions in the opposite orders. One
    holds the actor's membership `FOR SHARE` and wants the group `FOR UPDATE` (a grant that locked its actor first); the
    other holds the group `FOR UPDATE` and wants the same membership `FOR NO KEY UPDATE` (the add). PostgreSQL aborts one
    with SQLSTATE 40P01. This is a demonstration of the rejected order, not of the route."""
    import threading
    import time

    from sqlalchemy.exc import OperationalError

    owner_m = owner_membership(s)
    errors: list[str] = []
    ready = threading.Barrier(2)

    def actor_first() -> None:
        try:
            with pool.engine.begin() as c:
                c.execute(
                    text(
                        "SELECT 1 FROM security.campaign_memberships WHERE campaign_membership_id = :m FOR SHARE"
                    ),
                    {"m": owner_m},
                )
                ready.wait(10)
                time.sleep(0.4)
                c.execute(
                    text(
                        "SELECT 1 FROM security.access_groups WHERE access_group_id = :g FOR UPDATE"
                    ),
                    {"g": env.group},
                )
        except OperationalError as exc:
            errors.append(getattr(exc.orig, "sqlstate", "?"))

    def add() -> None:
        try:
            with pool.engine.begin() as c:
                c.execute(
                    text(
                        "SELECT 1 FROM security.access_groups WHERE access_group_id = :g FOR UPDATE"
                    ),
                    {"g": env.group},
                )
                ready.wait(10)
                time.sleep(0.4)
                c.execute(
                    text(
                        "SELECT 1 FROM security.campaign_memberships WHERE campaign_membership_id = :m "
                        "FOR NO KEY UPDATE"
                    ),
                    {"m": owner_m},
                )
        except OperationalError as exc:
            errors.append(getattr(exc.orig, "sqlstate", "?"))

    threads = [threading.Thread(target=actor_first), threading.Thread(target=add)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert errors == ["40P01"], errors


# --- role operations, transfer, recovery, archive ------------------------------------------------------------------------------------


@pytest.mark.parametrize("arrival", ("grant_parked", "role_parked"))
def test_assigning_a_role_to_the_target_and_granting_it_a_relationship_serialize_at_its_membership(
    arrival: str, s: Scene, env: Env, pool: Pool
) -> None:
    """*race*: assign (the target membership `FOR UPDATE`, the actor's `FOR SHARE`) against the relationship grant (the same
    classes): they conflict at the target membership and nowhere else. No cycle; both commit."""
    with s.w.engine.begin() as c:
        fresh = make_character(c, s.w.world_id, name="S5E4 Role character")
    grant = lambda: post(  # noqa: E731
        pool,
        s.w.owner,
        f"{s.w.base}/memberships/{env.membership}/character-relationships",
        {"character_id": str(fresh), "relationship_type_code": "viewer"},
    )
    assign = lambda: post(  # noqa: E731
        pool,
        s.w.owner,
        f"{s.w.base}/memberships/{env.membership}/roles",
        {"role_id": str(s.observer)},
    )
    if arrival == "grant_parked":
        o = race(s.w, pool, gate_pattern=FINAL, parked=grant, second=assign)
        granted, assigned = o.results["parked"], o.results["second"]
    else:
        o = race(s.w, pool, gate_pattern=AUDIT_INSERT, parked=assign, second=grant)
        granted, assigned = o.results["second"], o.results["parked"]
    assert_clean(o)
    assert o.blocked and all(len(row["blockers"]) == 1 for row in o.blocked), o.summary()
    assert code(granted) == 201 and code(assigned) == 201, o.summary()


@pytest.mark.parametrize("arrival", ("create_parked", "revoke_role_parked"))
def test_revoking_the_actors_own_manager_role_and_a_create_by_that_actor_serialize(
    arrival: str, s: Scene, env: Env, pool: Pool
) -> None:
    """*race*: the manager creates a grant while the keeper revokes the manager's `access.manage` role. The create holds the
    actor's role rows `FOR SHARE` from its first lock: the revoke (`FOR UPDATE` on the role row) queues behind it and runs
    after it. In the other order the create arrives after the revoke is parked holding the role row and queues at its role
    pass; once the revoke commits the create is refused (authority lost), nothing written. No cycle."""
    with s.w.engine.begin() as c:
        fresh = make_character(c, s.w.world_id, name="S5E4 Authority character")
    path = f"{s.w.base}/resource-grants"
    body = {
        "capability_code": "character.view_summary",
        "grantee_campaign_membership_id": str(env.membership),
        "character_id": str(fresh),
    }
    create = lambda: post(pool, s.m.manager_user, path, body)  # noqa: E731
    revoke = lambda: post(  # noqa: E731
        pool,
        s.m.keeper_user,
        f"{s.w.base}/memberships/roles/{s.m.manager_role}/revoke",
        {},
    )
    if arrival == "create_parked":
        o = race(s.w, pool, gate_pattern=FINAL, parked=create, second=revoke)
        created, revoked = o.results["parked"], o.results["second"]
        assert code(created) == 201 and code(revoked) == 200, o.summary()
    else:
        o = race(s.w, pool, gate_pattern=AUDIT_INSERT, parked=revoke, second=create)
        created, revoked = o.results["second"], o.results["parked"]
        assert code(revoked) == 200 and code(created) in (403, 404), o.summary()
    assert_clean(o)
    assert o.blocked and all(len(row["blockers"]) == 1 for row in o.blocked), o.summary()


@pytest.mark.parametrize("promoted", ("the_target", "another_member"))
@pytest.mark.parametrize("arrival", ("grant_parked", "recovery_parked"))
def test_recovery_and_a_grant_to_a_member_serialize_in_both_orders(
    arrival: str, promoted: str, w: World, pool: Pool
) -> None:
    """*race*: recovery (the promoted member's membership `FOR UPDATE`, then the campaign `FOR NO KEY UPDATE`) against a
    relationship grant to a member (the target membership `FOR UPDATE`, then the campaign `FOR UPDATE`), the target being the
    promoted member or another. Both take the membership before the campaign, so they serialize at the membership; for
    different members they serialize at the campaign (`NO KEY UPDATE` against `UPDATE`) with neither holding what the other
    wants. No deadlock; the campaign keeps its manager."""
    from dnd_ai.commands.recovery import recover_campaign_access_manager

    c_user, c_m, r_user, r_m, m_user, admin = recovery_scene(w)
    with w.engine.begin() as c:
        fresh = make_character(c, w.world_id, name="S5E4 Recovery character")
    target_membership = r_m if promoted == "the_target" else m_user
    del target_membership
    member_for_grant = r_m
    promote_user = r_user if promoted == "the_target" else m_user

    def grant() -> Any:
        return post(
            pool,
            c_user,
            f"{w.base}/memberships/{member_for_grant}/character-relationships",
            {"character_id": str(fresh), "relationship_type_code": "viewer"},
        )

    def recovery() -> Any:
        with pool.engine.begin() as connection:
            return recover_campaign_access_manager(
                connection,
                admin_user_id=admin,
                campaign_id=w.campaign_id,
                new_user_id=promote_user,
                reason="S5E4 recovery",
            ).campaign_membership_id

    if arrival == "grant_parked":
        raw = orchestrate(w, pool, gate_pattern=FINAL, parked=grant, second=recovery)
        grant_result, recovery_result = raw.results["parked"], raw.results["second"]
    else:
        raw = orchestrate(
            w,
            pool,
            gate_pattern=RECOVERY_CAMPAIGN_NKU if promoted == "the_target" else RECOVERY_MEMBERSHIP,
            nth=1 if promoted == "the_target" else 2,
            parked=recovery,
            second=grant,
        )
        grant_result, recovery_result = raw.results["second"], raw.results["parked"]
    assert_no_deadlock(raw)
    assert recovery_result[0] == "ok", raw.summary()
    assert grant_result in (OK200, (201, None), (404, "not_found"), (409, "conflict")), (
        raw.summary()
    )


@pytest.mark.parametrize("arrival", ("grant_parked", "archive_parked"))
def test_campaign_archive_and_a_create_serialize_in_both_orders(
    arrival: str, s: Scene, env: Env, pool: Pool
) -> None:
    """*race*: archive (the campaign `FOR UPDATE`) against a grant (the campaign `FOR UPDATE` after the membership rows).
    `grant_parked`: archive queues at the campaign lock and commits after. `archive_parked`: the grant queues at its campaign
    lock, then `finalize` re-resolves the route requirement against the archived campaign and refuses it (nothing written).
    No deadlock."""
    with s.w.engine.begin() as c:
        fresh = make_character(c, s.w.world_id, name="S5E4 Archive character")
    version = rows(
        s.w.engine,
        "SELECT row_version FROM campaign.campaigns WHERE campaign_id = :c",
        c=s.w.campaign_id,
    )[0]["row_version"]
    grant = lambda: post(  # noqa: E731
        pool,
        s.m.manager_user,
        f"{s.w.base}/resource-grants",
        {
            "capability_code": "character.view_summary",
            "grantee_campaign_membership_id": str(env.membership),
            "character_id": str(fresh),
        },
    )
    archive = lambda: post(  # noqa: E731
        pool,
        s.m.manager_user,
        f"{s.w.base}/archive",
        {"expected_row_version": version, "reason": "S5E4"},
    )
    after_campaign_lock = (
        r"^SELECT c\.name, c\.description, c\.row_version, c\.lifecycle_status_id, c\.timeline_id "
        r"FROM campaign\.campaigns c WHERE c\.campaign_id = \S+$"
    )
    before = snap(s)
    if arrival == "grant_parked":
        o = race(s.w, pool, gate_pattern=FINAL, parked=grant, second=archive)
        granted, archived = o.results["parked"], o.results["second"]
        assert code(granted) == 201 and code(archived) == 200, o.summary()
    else:
        o = race(s.w, pool, gate_pattern=after_campaign_lock, parked=archive, second=grant)
        granted, archived = o.results["second"], o.results["parked"]
        assert code(archived) == 200 and code(granted) in (403, 404, 409), o.summary()
        assert snap(s).grants == before.grants
    assert_clean(o)


# --- self-targeted requests ----------------------------------------------------------------------------------------------------------------


def test_a_manager_granting_themselves_takes_their_membership_once_exclusively(
    s: Scene, env: Env, pool: Pool
) -> None:
    """*race* (mode probe): the actor is the grantee. The shared row is locked once, `FOR UPDATE` (the target, the
    stronger), the actor's `FOR SHARE` request landing on the row already held: no upgrade. Authority is the pre-command
    authority (the grant succeeds)."""
    from tests.database.test_r01_s5e2_lock_order import MEMBERSHIP_ROW, park_and_probe

    actor = s.m.manager_membership
    response, modes = park_and_probe(
        s.w,
        pool,
        gate_pattern=FINAL,
        request=lambda: post(
            pool,
            s.m.manager_user,
            f"{s.w.base}/memberships/{actor}/character-relationships",
            {"character_id": str(env.other_character), "relationship_type_code": "viewer"},
        ),
        probes={"actor_and_target": (MEMBERSHIP_ROW, actor)},
    )
    assert code(response) == 201, response.text
    assert modes["actor_and_target"] == "U", modes


def test_a_manager_changing_their_own_relationship_and_ending_themselves_serialize(
    s: Scene, pool: Pool
) -> None:
    """*race*: the manager holds a relationship and changes it while the keeper ends the manager. Both arrivals are
    covered by the member-end pair above; this is the self-targeted shape: the actor is the owning membership, locked once
    `FOR UPDATE`. The change succeeds on the pre-command authority, then the keeper's end closes the new row."""
    with s.w.engine.begin() as c:
        character = make_character(c, s.w.world_id, name="S5E4 Self character")
        types = {
            r[0]: r[1]
            for r in c.execute(
                text(
                    "SELECT code, character_relationship_type_id FROM security.character_relationship_types "
                    "WHERE code IN ('portrayer', 'co_controller')"
                )
            )
        }
        relationship = c.execute(
            text(
                "INSERT INTO security.membership_character_relationships (campaign_membership_id, character_id, "
                "character_relationship_type_id, granted_by_membership_id) VALUES (:m, :c, :t, :m) "
                "RETURNING membership_character_relationship_id"
            ),
            {"m": s.m.manager_membership, "c": character, "t": types["portrayer"]},
        ).scalar_one()
    changed = post(
        pool,
        s.m.manager_user,
        f"{s.w.base}/character-relationships/{relationship}/change",
        {"new_relationship_type_id": str(types["co_controller"])},
    )
    assert code(changed) == 201, changed.text
    ended = end_request(s, pool, s.m.manager_membership, actor=s.m.keeper_user)
    assert code(ended) == 200
    assert open_rows(s, s.m.manager_membership)["relationships"] == 0


# --- the target's account (S5-A) ---------------------------------------------------------------------------------------------------


def _route_for(name: str, s: Scene, env: Env) -> tuple[str, dict[str, Any], int]:
    if name == "grant_relationship":
        return (
            f"{s.w.base}/memberships/{env.membership}/character-relationships",
            {"character_id": str(env.other_character), "relationship_type_code": "viewer"},
            201,
        )
    if name == "change_relationship":
        return (
            f"{s.w.base}/character-relationships/{env.relationship}/change",
            {"new_relationship_type_id": str(env.co_controller)},
            201,
        )
    return (
        f"{s.w.base}/resource-grants",
        {
            "capability_code": "character.view_summary",
            "grantee_campaign_membership_id": str(env.membership),
            "character_id": str(env.other_character),
        },
        201,
    )


def _deactivate_account(user: uuid.UUID) -> Any:
    """The real account writer's shape: `SELECT ... FOR UPDATE` on the row, then the lifecycle update."""

    def run(c: Any) -> None:
        c.execute(text("SELECT 1 FROM security.users WHERE user_id = :u FOR UPDATE"), {"u": user})
        c.execute(
            text(
                "UPDATE security.users SET lifecycle_status_id = (SELECT lifecycle_status_id "
                "FROM core.lifecycle_statuses WHERE code = 'archived') WHERE user_id = :u"
            ),
            {"u": user},
        )

    return run


@pytest.mark.parametrize(
    "route_name", ("grant_relationship", "change_relationship", "create_grant")
)
@pytest.mark.parametrize("arrival", ("route_parked", "deactivation_held"))
def test_deactivating_the_targets_account_and_a_route_that_names_it_serialize_in_both_orders(
    arrival: str, route_name: str, s: Scene, env: Env, pool: Pool
) -> None:
    """*race*, S5-A on the new routes: the route takes the target's account `FOR KEY SHARE`, which conflicts with the real
    writer's `FOR UPDATE`. `route_parked` (every lock held): the deactivation queues behind the route's backend and runs
    after it. `deactivation_held` (the writer holds the row, the status updated, uncommitted): the route queues at its account
    lock behind the writer, then refuses the now inactive account with the unchanged 409 and writes nothing."""
    from tests.database.test_r01_s5e2_lock_order import NthGate, blocked_view, finish
    from tests.http_race_support import run_in_thread
    from tests.lock_race_support import LockRace

    path, body, status = _route_for(route_name, s, env)
    before = snap(s)
    if arrival == "route_parked":
        with NthGate(pool.engine, FINAL) as gate:
            request = run_in_thread("route", lambda: post(pool, s.w.owner, path, body))
            assert gate.reached.wait(30)
            with LockRace(s.w.engine) as race:
                writer = race.start("deactivate", _deactivate_account(env.user))
                race.wait_blocked_by(gate, expected=1)
                assert gate.pid is not None
                assert any("users" in r["query"] for r in blocked_view(s.w.engine, gate.pid))
                gate.release()
                response = finish(request, "the route finishes")
                race.join_all()
        assert code(response) == status and writer.error is None
    else:
        with LockRace(s.w.engine) as race:
            hold = race.hold(_deactivate_account(env.user))
            request = run_in_thread("route", lambda: post(pool, s.w.owner, path, body))
            import time

            deadline = time.monotonic() + 30
            queued: list[dict[str, Any]] = []
            while time.monotonic() < deadline and not queued:
                queued = blocked_view(s.w.engine, hold.pid)
                time.sleep(0.02)
            assert queued and all(len(r["blockers"]) == 1 for r in queued)
            assert any("FOR KEY SHARE" in r["query"] and "users" in r["query"] for r in queued)
            hold.commit()
            response = finish(request, "the route finishes")
        assert code(response) == 409, response.text
        assert snap(s) == before
    del before


# --- the deferred authoring cycle: characterized ----------------------------------------------------------------------------------------------


def legacy_create_grant(
    s: Scene, pool: Pool, env: Env, character: uuid.UUID, actor: uuid.UUID
) -> Any:
    """The pre-S5-E4 command, run as the command: the baseline for the comparison. A driver exception is a 500."""
    from dnd_ai.commands.access_grants import create_resource_grant

    try:
        with pool.engine.begin() as connection:
            create_resource_grant(
                connection,
                campaign_id=s.w.campaign_id,
                grantee_campaign_membership_id=env.membership,
                grantee_access_group_id=None,
                character_id=character,
                capability_code="character.view_summary",
                effect="allow",
                expected_world_id=s.w.world_id,
                granted_by_membership_id=actor,
            )
    except Exception as exc:  # noqa: BLE001 - the deadlock victim
        return FakeResponse(500, {"error": type(exc).__name__})
    return FakeResponse(201)


AUTHORING_WORLD = r"^SELECT lifecycle_status_id FROM core\.worlds WHERE world_id = \S+ FOR SHARE$"


@pytest.mark.parametrize("subject", ("new_route", "legacy_command"))
def test_characterized_keyed_authoring_by_the_grantee_and_a_grant_to_the_grantee_wait_in_a_cycle_at_the_baseline_too(
    subject: str, s: Scene, pool: Pool
) -> None:
    """**Characterization (deferred cycle DEF-019, not a fix)**: the grantee is the GM member and also the author of a
    keyed authoring request. The authoring request takes the campaign `FOR KEY SHARE` (its reservation) and then the
    author's role rows and membership `FOR SHARE`; the grant (the **untouched baseline command** and the new route alike)
    takes the grantee's membership `FOR UPDATE` and then wants the campaign `FOR UPDATE`. Interleaved (authoring parked at
    its world statement, holding the campaign `FOR KEY SHARE`; the grant holding the membership and queued at the
    campaign) they deadlock: one request is aborted (SQLSTATE 40P01), the other commits. `subject=legacy_command` shows
    the same 40P01 at the baseline, so S5-E4 introduced no new cycle; it is **deferred under DEF-019** (the authoring
    opt-in slice, plan 6.21.7, required before A6 and R01 closure). PostgreSQL chooses the victim; which request loses
    is not asserted. A pass means the defect was characterized, not fixed; it fails when the cycle disappears."""
    from tests.database.test_r01_s5e2_authoring_transfer_cycles import dungeons

    w = s.w
    env_gm = Env(
        user=w.gm_user,
        membership=w.gm_membership,
        character=uuid.uuid4(),
        other_character=uuid.uuid4(),
        portrayer=uuid.uuid4(),
        co_controller=uuid.uuid4(),
        relationship=uuid.uuid4(),
        grant=uuid.uuid4(),
        group=uuid.uuid4(),
        capability=uuid.uuid4(),
    )
    with w.engine.begin() as c:
        fresh = make_character(c, w.world_id, name="S5E4 Authoring character")
    actor = owner_membership(s)
    name = f"S5E4 {uuid.uuid4().hex[:8]}"
    key = str(uuid.uuid4())

    def authoring() -> Any:
        return post(
            pool,
            w.gm_user,
            f"{w.base}/authoring/dungeons",
            {"name": name, "summary": None},
            **{"Idempotency-Key": key},
        )

    def grant_new() -> Any:
        return post(
            pool,
            w.owner,
            f"{w.base}/resource-grants",
            {
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(env_gm.membership),
                "character_id": str(fresh),
            },
        )

    def grant_old() -> Any:
        return legacy_create_grant(s, pool, env_gm, fresh, actor)

    grant = grant_new if subject == "new_route" else grant_old
    o = race(w, pool, gate_pattern=AUTHORING_WORLD, parked=authoring, second=grant)
    assert len(o.failures) == 1 and o.failures[0][0] == "40P01", o.summary()
    assert o.deadlock_delta == 1, o.summary()
    codes = sorted(code(o.results[n]) for n in ("parked", "second"))
    assert 500 in codes and len(codes) == 2, o.summary()
    authored = dungeons(w, name)
    granted = rows(
        w.engine,
        "SELECT count(*) AS n FROM security.resource_grants WHERE grantee_campaign_membership_id = :m "
        "AND character_id = :c",
        m=w.gm_membership,
        c=fresh,
    )[0]["n"]
    assert (authored == 1) != (granted == 1), (authored, granted, o.summary())
