# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E3: the end route against every writer its cascade or its lock set touches, both transaction orderings.

Every case drives real routes over real connections (the 8-connection `pool` of the S5-E2 lock-order module), parks one
request on a named statement, starts the other, observes (`pg_blocking_pids`) that it queued behind the parked backend,
releases, and then asserts: no driver exception and no moved deadlock counter (`assert_clean`), the exact statuses, and the
**completeness invariant** (a member whose membership ended owns no open dependent row of any of the seven kinds).

Two kinds of test live here and must not be confused (the S5-E2 E10 distinction):

1. **New-cycle regressions** (`test_*` without `characterized`): clean at HEAD, ordinary passing tests.
2. **Characterizations** (`test_characterized_*`): cycles that exist at the untouched baseline too (the legacy end
   command shows the same 40P01) and belong to writers still pending in S5-E4/E5 or to the deferred authoring opt-in
   (DEF-019, plan 6.21.7). A pass means the pre-existing defect is *characterized, not fixed*; it fails when the cycle
   disappears, forcing reclassification. They are never presented as a clean result.
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
    CAMPAIGN_ROW,
    MEMBERSHIP_ROW,
    ROLE_ROW,
    Pool,
    assert_clean,
    insert_role,
    park_and_probe,
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
    AUDIT_INSERT,
    CAMPAIGN_U,
    DELEGATIONS_U,
    FINAL,
    GRANTS_U,
    GROUPS_U,
    RELATIONSHIPS_U,
    REVELATIONS_U,
    ROLE_ROW_U,
    Member,
    _tidy_end,
    audit_row,
    build_member,
    e,
    open_dependents,
    state,
)
from tests.factories import make_access_group, make_character
from tests.r01_s5d_support import make_managers

pytestmark = pytest.mark.database

NONE_OPEN = {
    "roles": 0,
    "delegations": 0,
    "relationships": 0,
    "grants": 0,
    "groups": 0,
    "revelations": 0,
    "snapshots": 0,
}
END_STATE_CHANGED = (409, "membership_end_state_changed")
KINDS_ALL = ("role", "delegation", "relationship", "grant", "group")
KINDS = KINDS_ALL
#: What each creator answers once the end has committed (its own, unchanged refusal of an ended membership).
REFUSED = {
    "role": (404, "not_found"),  # BA-404
    "delegation": (409, "reveal_delegation_recipient_not_gm"),
    "relationship": (404, "not_found"),
    "grant": (404, "not_found"),
    "group": (409, "conflict"),
}
#: What the end answers when the creator held first (order C): the new row of every kind is found under the membership
#: lock; a role or delegation row that appeared after the early pass is locked `NOWAIT` (nobody holds it) and closed.
END_AFTER_CREATOR = dict.fromkeys(KINDS_ALL, (200, None))


def end_request(s: Scene, pool: Pool, target: uuid.UUID, actor: uuid.UUID | None = None) -> Any:
    return post(pool, actor or s.w.owner, f"{s.w.base}/memberships/{target}/end")


def creator_request(kind: str, s: Scene, e: Member) -> tuple[str, dict[str, Any]]:
    """The supported creator of one dependent-row kind, aimed at the member `e`."""
    base = s.w.base
    if kind == "role":
        return f"{base}/memberships/{e.membership}/roles", {"role_id": str(s.observer)}
    if kind == "delegation":
        return f"{base}/reveal-delegations", {
            "grantee_campaign_membership_id": str(e.membership),
            "reason": "e",
        }
    if kind == "relationship":
        with s.w.engine.begin() as c:
            other = make_character(c, s.w.world_id, name="S5E3 Other character")
        return f"{base}/memberships/{e.membership}/character-relationships", {
            "character_id": str(other),
            "relationship_type_code": "viewer",
        }
    if kind == "grant":
        with s.w.engine.begin() as c:
            other = make_character(c, s.w.world_id, name="S5E3 Grant character")
        return f"{base}/resource-grants", {
            "capability_code": "character.view_summary",
            "grantee_campaign_membership_id": str(e.membership),
            "character_id": str(other),
        }
    assert kind == "group"
    with s.w.engine.begin() as c:
        group = make_access_group(c, s.w.campaign_id, name="S5E3 Fresh group")
    return f"{base}/access-groups/{group}/members", {"campaign_membership_ids": [str(e.membership)]}


@pytest.mark.parametrize("gate", (FINAL, CAMPAIGN_U), ids=("end_at_final", "end_at_campaign_lock"))
@pytest.mark.parametrize("kind", KINDS)
def test_a_creator_that_arrives_after_the_end_holds_its_locks_is_queued_then_refused_and_creates_nothing(
    kind: str, gate: str, s: Scene, pool: Pool
) -> None:
    """*race*, order E: the end is parked at its final statement holding every lock of its declaration. The
    supported creator of a row of this kind queues behind the end's backend (its foreign key or explicit lock on the
    membership conflicts with the end's `FOR UPDATE`); the end commits; the creator then judges the ended membership
    and is refused. No driver error, no deadlock, and no open dependent row remains: nothing is added behind the
    cascade."""
    e = build_member(s, with_delegation=kind != "delegation")
    path, body = creator_request(kind, s, e)
    o = race(
        s.w,
        pool,
        gate_pattern=gate,
        parked=lambda: end_request(s, pool, e.membership),
        second=lambda: post(pool, s.w.owner, path, body),
    )
    assert_clean(o)
    assert o.blocked and all(len(row["blockers"]) == 1 for row in o.blocked), o.summary()
    assert o.status("parked") == (200, None), o.summary()
    assert o.status("second") == REFUSED[kind], o.summary()
    assert open_dependents(s, e.membership) == NONE_OPEN
    assert state(s, e.membership).membership[0] is True


@pytest.mark.parametrize("kind", KINDS)
def test_a_creator_that_holds_its_locks_first_makes_the_end_wait_and_the_end_closes_what_it_created(
    kind: str, s: Scene, pool: Pool
) -> None:
    """*race*, order C: the creator is parked at its audit insert (its row inserted, uncommitted). The end queues
    behind the creator's backend. When the creator commits, the target-class kinds (relationship, grant, group) are
    discovered under the membership lock and closed with the rest (200); the role-class kinds (a new role row, a
    new delegation) were not among the rows locked before the membership, so the end refuses them with the retryable
    409 `membership_end_state_changed` and writes nothing; its retry closes them. Either way no deadlock and, once
    the end has succeeded, no open dependent row."""
    e = build_member(s, with_delegation=kind != "delegation")
    path, body = creator_request(kind, s, e)
    o = race(
        s.w,
        pool,
        gate_pattern=AUDIT_INSERT,
        parked=lambda: post(pool, s.w.owner, path, body),
        second=lambda: end_request(s, pool, e.membership),
    )
    assert_clean(o)
    assert o.blocked and all(len(row["blockers"]) == 1 for row in o.blocked), o.summary()
    assert code(o.results["parked"]) in (200, 201), o.summary()
    status = o.status("second")
    assert status == END_AFTER_CREATOR[kind], o.summary()
    if status == END_STATE_CHANGED:
        assert state(s, e.membership).membership[0] is False, (
            "nothing was written by the refused end"
        )
        assert audit_row(s, e.membership) == []
        assert code(end_request(s, pool, e.membership)) == 200
    else:
        assert status == (200, None), o.summary()
    assert open_dependents(s, e.membership) == NONE_OPEN
    assert state(s, e.membership).membership[0] is True
    [(_, _, _, _, changed)] = audit_row(s, e.membership)
    # the row the creator added is among the closed ids the audit row names (delegations are closed but, as
    # before, not listed in `changed_fields`)
    field, table, pk, column = {
        "role": (
            "revoked_membership_role_ids",
            "membership_roles",
            "membership_role_id",
            "campaign_membership_id",
        ),
        "relationship": (
            "revoked_membership_character_relationship_ids",
            "membership_character_relationships",
            "membership_character_relationship_id",
            "campaign_membership_id",
        ),
        "grant": (
            "revoked_resource_grant_ids",
            "resource_grants",
            "resource_grant_id",
            "grantee_campaign_membership_id",
        ),
        "group": (
            "removed_access_group_membership_ids",
            "access_group_memberships",
            "access_group_membership_id",
            "campaign_membership_id",
        ),
        "delegation": (None, None, None, None),
    }[kind]
    if field is not None:
        created = rows(
            s.w.engine,
            f"SELECT {pk} AS id FROM security.{table} WHERE {column} = :m",  # noqa: S608 - fixed names
            m=e.membership,
        )
        assert {str(r["id"]) for r in created} == set(changed[field]), (created, changed)


def closer_request(kind: str, s: Scene, e: Member) -> tuple[str, dict[str, Any]]:
    """The supported closer of one dependent row of the member `e`."""
    base = s.w.base
    if kind == "role":
        return f"{base}/memberships/roles/{e.player_row}/revoke", {}
    if kind == "relationship":
        return f"{base}/character-relationships/{e.relationship}/revoke", {}
    if kind == "grant":
        return f"{base}/resource-grants/{e.grant}/revoke", {}
    if kind == "group":
        return f"{base}/access-group-memberships/{e.group_membership}/remove", {}
    if kind == "delegation":
        return f"{base}/reveal-delegations/{e.membership}/revoke", {"reason": "e"}
    assert kind == "revelation"
    return f"{base}/characters/{e.character}/revelations/{e.revelation}/revoke", {"reason": "e"}


CLOSERS = ("role", "relationship", "grant", "group", "delegation", "revelation")


#: The statement that takes each kind's lock in the end route: the end is parked *at* it (before it runs), so it holds
#: every lock of the classes before it and none of this class or after.
END_GATE = {
    "role": ROLE_ROW_U,
    "delegation": DELEGATIONS_U,
    "relationship": RELATIONSHIPS_U,
    "grant": GRANTS_U,
    "group": GROUPS_U,
    "revelation": REVELATIONS_U,
}


@pytest.mark.parametrize("arrival", ("end_at_the_kinds_lock", "closer_parked_after_its_row"))
@pytest.mark.parametrize("kind", CLOSERS)
def test_a_closer_of_a_dependent_row_and_the_end_never_wait_in_a_cycle(
    kind: str, arrival: str, s: Scene, e: Member, pool: Pool
) -> None:
    """*race*: the supported closer of one dependent row (revoke role, relationship, grant or delegation; remove from
    group; revoke revelation) against the end, both orderings. Order `end_at_the_kinds_lock`: the end is parked at the
    statement that locks this kind's rows, holding every earlier class. Order `closer_parked_after_its_row`: the closer
    is parked at its audit insert, its row updated and uncommitted. The queued request waits behind the parked
    backend, no driver error, the deadlock counter does not move, both answer 200 (the loser finds the row already
    closed: a revoke is the documented no-op, the end closes what is left), and no dependent row stays open."""
    path, body = closer_request(kind, s, e)
    closer = lambda: post(pool, s.w.owner, path, body)  # noqa: E731
    end_ = lambda: end_request(s, pool, e.membership)  # noqa: E731
    if arrival == "end_at_the_kinds_lock":
        o = race(s.w, pool, gate_pattern=END_GATE[kind], parked=end_, second=closer)
    else:
        o = race(s.w, pool, gate_pattern=AUDIT_INSERT, parked=closer, second=end_)
    print(
        "PROBE",
        kind,
        arrival,
        o.status("parked"),
        o.status("second"),
        o.failures,
        o.deadlock_delta,
        bool(o.blocked),
    )
    assert_clean(o)
    assert open_dependents(s, e.membership) == NONE_OPEN
    assert state(s, e.membership).membership[0] is True


class FakeResponse:
    """What `Outcome.status` reads from a response: the legacy command's answer."""

    def __init__(self, status_code: int, body: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}
        self.text = str(self._body)

    def json(self) -> dict[str, Any]:
        return self._body


def legacy_end(s: Scene, pool: Pool, target: uuid.UUID, actor_membership: uuid.UUID) -> Any:
    """The pre-S5-E3 end, run as the command (`end_campaign_membership`): the baseline for every comparison below.
    A driver exception is reported as a 500, as the application's handler would."""
    from dnd_ai.commands.memberships import end_campaign_membership

    try:
        with pool.engine.begin() as connection:
            end_campaign_membership(
                connection,
                campaign_membership_id=target,
                campaign_id=s.w.campaign_id,
                ended_by_membership_id=actor_membership,
            )
    except Exception as exc:  # noqa: BLE001 - the deadlock victim
        return FakeResponse(500, {"error": type(exc).__name__})
    return FakeResponse(200)


def owner_membership(s: Scene) -> uuid.UUID:
    return rows(
        s.w.engine,
        "SELECT campaign_membership_id AS id FROM security.campaign_memberships "
        "WHERE campaign_id = :c AND user_id = :u",
        c=s.w.campaign_id,
        u=s.w.owner,
    )[0]["id"]


def other_type_for(s: Scene) -> uuid.UUID:
    with s.w.engine.begin() as c:
        return c.execute(
            text(
                "SELECT character_relationship_type_id FROM security.character_relationship_types WHERE code = 'co_controller'"
            )
        ).scalar_one()


@pytest.mark.parametrize("subject", ("new_end", "legacy_end"))
def test_characterized_changing_a_relationship_and_ending_its_member_wait_in_a_cycle_at_the_baseline_too(
    subject: str, s: Scene, e: Member, pool: Pool
) -> None:
    """**Characterization (a pre-existing cycle, not a fix)**: `POST .../character-relationships/{id}/change` locks the
    relationship row and then the member's membership (`FOR UPDATE OF mcr, cm` in one statement); every end locks the
    membership and then the member's relationship rows. Interleaved (the end holds the membership and wants the
    relationship row, the change holds the row and wants the membership) they deadlock: one request is aborted
    (SQLSTATE 40P01 on a cycle-edge statement, the 500 on the request whose statement failed, the deadlock counter
    +1), the other commits. **The untouched end command has the same cycle** (`legacy_end`, parked at the statement
    where it updates the relationships): this is `subject=legacy_end`, so S5-E3 introduced no new cycle. PostgreSQL
    chooses the victim, so which request loses is not asserted. The fix is the order of the *change* route, which is a
    pending route (S5-E4/E5): it must lock the membership before the relationship row. When it is fixed this test
    fails on "exactly one 40P01", which forces the reclassification."""
    other_type = other_type_for(s)
    path = f"{s.w.base}/character-relationships/{e.relationship}/change"
    body = {"new_relationship_type_id": str(other_type)}

    def change() -> Any:
        return post(pool, s.w.owner, path, body)

    if subject == "new_end":
        o = race(
            s.w,
            pool,
            gate_pattern=RELATIONSHIPS_U,
            parked=lambda: end_request(s, pool, e.membership),
            second=change,
        )
    else:
        actor = owner_membership(s)
        o = race(
            s.w,
            pool,
            gate_pattern=r"^UPDATE security\.membership_character_relationships",
            parked=lambda: legacy_end(s, pool, e.membership, actor),
            second=change,
        )
    assert len(o.failures) == 1 and o.failures[0][0] == "40P01", o.summary()
    assert o.deadlock_delta == 1, o.summary()
    codes = sorted(code(o.results[name]) for name in ("parked", "second"))
    survivors = [c for c in codes if c != 500]
    assert len(survivors) == 1 and survivors[0] in (200, 201) and len(codes) == 2, o.summary()
    # the victim rolled back whole; a retry of the end completes when it was the end that lost
    if state(s, e.membership).membership[0] is False:
        assert code(end_request(s, pool, e.membership)) == 200
    assert open_dependents(s, e.membership) == NONE_OPEN


# --- the held modes ------------------------------------------------------------------------------------------------------

REL_ROW = ("security.membership_character_relationships", "membership_character_relationship_id")
GRANT_ROW = ("security.resource_grants", "resource_grant_id")
GROUP_ROW = ("security.access_group_memberships", "access_group_membership_id")
REVELATION_ROW = ("security.character_revelations", "character_revelation_id")
SNAPSHOT_ROW = ("security.character_revelation_members", "character_revelation_member_id")
DELEGATION_ROW = ("security.character_reveal_delegations", "character_reveal_delegation_id")


def test_the_end_holds_each_row_at_the_mode_it_needs_at_the_final_statement(
    s: Scene, pool: Pool
) -> None:
    """*race* (mode probes through `NOWAIT`, the S5-E2 `held_mode`): at its final authority statement the end holds the
    actor's role rows `FOR SHARE`, every role row of the member `FOR UPDATE`, the actor's membership `FOR SHARE` and
    the member's `FOR UPDATE`, the campaign `FOR UPDATE`, the delegation and the five dependent classes `FOR UPDATE`,
    and nothing stronger than it needs on the actor. Run with the actor an owner (distinct from the member)."""
    e = build_member(s)
    actor = owner_membership(s)
    owner_row = rows(
        s.w.engine,
        "SELECT membership_role_id AS id FROM security.membership_roles "
        "WHERE campaign_membership_id = :m AND revoked_at IS NULL",
        m=actor,
    )[0]["id"]
    response, modes = park_and_probe(
        s.w,
        pool,
        gate_pattern=FINAL,
        request=lambda: end_request(s, pool, e.membership),
        probes={
            "actor role row": (ROLE_ROW, owner_row),
            "player row": (ROLE_ROW, e.player_row),
            "gm row": (ROLE_ROW, e.gm_row),
            "actor membership": (MEMBERSHIP_ROW, actor),
            "member membership": (MEMBERSHIP_ROW, e.membership),
            "campaign": (CAMPAIGN_ROW, s.w.campaign_id),
            "delegation": (DELEGATION_ROW, e.delegation),
            "relationship": (REL_ROW, e.relationship),
            "grant": (GRANT_ROW, e.grant),
            "group membership": (GROUP_ROW, e.group_membership),
            "revelation": (REVELATION_ROW, e.revelation),
            "snapshot row": (SNAPSHOT_ROW, e.snapshot_row),
        },
    )
    assert code(response) == 200
    assert modes == {
        "actor role row": "S",
        "player row": "U",
        "gm row": "U",
        "actor membership": "S",
        "member membership": "U",
        "campaign": "U",
        "delegation": "U",
        "relationship": "U",
        "grant": "U",
        "group membership": "U",
        "revelation": "U",
        "snapshot row": "U",
    }


def test_a_self_end_holds_the_shared_rows_exclusively_once(s: Scene, pool: Pool) -> None:
    """*race*: the actor is the member: the actor's rows are the member's, held `FOR UPDATE` once, the membership
    `FOR UPDATE` once. No shared mode survives on a row the request also writes (no upgrade occurred)."""
    actor = owner_membership(s)
    own_rows = [
        r["id"]
        for r in rows(
            s.w.engine,
            "SELECT membership_role_id AS id FROM security.membership_roles "
            "WHERE campaign_membership_id = :m AND revoked_at IS NULL",
            m=actor,
        )
    ]
    response, modes = park_and_probe(
        s.w,
        pool,
        gate_pattern=FINAL,
        request=lambda: end_request(s, pool, actor),
        probes={
            "own role row": (ROLE_ROW, own_rows[0]),
            "own membership": (MEMBERSHIP_ROW, actor),
        },
    )
    assert code(response) == 200
    assert modes == {"own role row": "U", "own membership": "U"}


# --- a row that appeared in the window ------------------------------------------------------------------------------------


def test_a_role_that_appeared_while_the_end_waited_and_is_held_by_another_request_is_a_retryable_409(
    s: Scene, e: Member, pool: Pool
) -> None:
    """*race*: the early role pass cannot lock a row that does not exist yet. A creator commits a new role row for the
    member while the end waits for the membership; the end then (parked after its membership read, holding the
    membership) finds the new row and takes it `NOWAIT`. Here another transaction holds that row first, so the end
    cannot take it and is refused with the retryable 409 `membership_end_state_changed`: it never waits (a wait could
    close a cycle with a request that holds the row and wants the campaign). Nothing is written, and the retry,
    with the row free, closes it."""
    from tests.database.test_r01_s5e2_lock_order import NthGate, finish
    from tests.http_race_support import run_in_thread

    read_after_locks = r"^SELECT campaign_id, ended_at FROM security\.campaign_memberships WHERE campaign_membership_id"
    created: dict[str, uuid.UUID] = {}
    with NthGate(pool.engine, read_after_locks) as gate:
        request = run_in_thread("end", lambda: end_request(s, pool, e.membership))
        assert gate.reached.wait(30)
        # the end holds the member's membership; the "creator" cannot insert behind it, so the row is created by a
        # transaction that committed before the end got the membership: simulated by inserting the row with the
        # end's membership lock bypassed (replica role skips the foreign key's lock)
        with s.w.engine.begin() as c:
            c.execute(text("SET LOCAL session_replication_role = replica"))
            created["row"] = insert_role(c, None, e.membership, s.observer)
        holder = s.w.engine.connect()
        try:
            holder.execute(
                text(
                    "SELECT 1 FROM security.membership_roles WHERE membership_role_id = :r FOR SHARE"
                ),
                {"r": created["row"]},
            ).all()
            gate.release()
            response = finish(request, "the end finishes")
        finally:
            holder.rollback()
            holder.close()
    assert code(response) == 409 and error_of(response) == "membership_end_state_changed"
    assert state(s, e.membership).membership[0] is False and audit_row(s, e.membership) == []
    assert code(end_request(s, pool, e.membership)) == 200
    assert open_dependents(s, e.membership) == NONE_OPEN
    [(_, _, _, _, changed)] = audit_row(s, e.membership)
    assert str(created["row"]) in changed["revoked_membership_role_ids"]


def test_a_role_that_appeared_in_the_window_and_is_free_is_closed_with_the_rest(
    s: Scene, e: Member, pool: Pool
) -> None:
    """*race*: the same window with nobody holding the new row: the `NOWAIT` lock succeeds and the end closes it
    through its own declared step (`end_revoke_late_role`), listing it in the audit row."""
    from tests.database.test_r01_s5e2_lock_order import NthGate, finish
    from tests.http_race_support import run_in_thread

    read_after_locks = r"^SELECT campaign_id, ended_at FROM security\.campaign_memberships WHERE campaign_membership_id"
    with NthGate(pool.engine, read_after_locks) as gate:
        request = run_in_thread("end", lambda: end_request(s, pool, e.membership))
        assert gate.reached.wait(30)
        with s.w.engine.begin() as c:
            c.execute(text("SET LOCAL session_replication_role = replica"))
            new_row = insert_role(c, None, e.membership, s.observer)
        gate.release()
        response = finish(request, "the end finishes")
    assert code(response) == 200, response.text
    assert open_dependents(s, e.membership) == NONE_OPEN
    [(_, _, _, _, changed)] = audit_row(s, e.membership)
    assert str(new_row) in changed["revoked_membership_role_ids"]
    assert len(changed["revoked_membership_role_ids"]) == 3


# --- overlapping actors and targets ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "third_manager", (False, True), ids=("only_two_managers", "a_third_survives")
)
@pytest.mark.parametrize("order", ("cmC_below_cmX", "cmC_above_cmX"))
@pytest.mark.parametrize("arrival", ("first_end_parked", "second_end_parked"))
def test_two_managers_ending_each_other_serialize_without_a_cycle_and_exactly_one_wins(
    arrival: str, order: str, third_manager: bool, s: Scene, pool: Pool
) -> None:
    """*race* (concurrent manager removal): two managers end each other at once, both orders of the two memberships.
    One ascending pass over the union of their role rows means whoever takes the lowest row first proceeds; the other
    waits holding nothing. Exactly one end succeeds. With only the two managers the loser would leave the campaign
    with none (the winner's target is the loser): the retention pre-check, judged under the held campaign lock before
    `finalize`, refuses it with the unchanged 400 and the campaign keeps its manager. With a third non-expiring manager
    the pre-check passes and the loser, whose authority the winner took, is refused at the final check (403/404)."""
    if not third_manager:  # otherwise the campaign's creator keeps their non-expiring role
        with s.w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.membership_roles SET expires_at = now() + interval '1 day' "
                    "WHERE campaign_membership_id IN (SELECT campaign_membership_id FROM "
                    "security.campaign_memberships WHERE campaign_id = :c) "
                    "AND membership_role_id <> ALL(:keep)"
                ),
                {"c": s.w.campaign_id, "keep": [s.m.manager_role, _keeper_role(s)]},
            )
    c_user, c_m, x_user, x_m = _two_managers(s, order)

    def c_ends_x() -> Any:
        return post(pool, c_user, f"{s.w.base}/memberships/{x_m}/end")

    def x_ends_c() -> Any:
        return post(pool, x_user, f"{s.w.base}/memberships/{c_m}/end")

    parked, second = (c_ends_x, x_ends_c) if arrival == "first_end_parked" else (x_ends_c, c_ends_x)
    o = race(s.w, pool, gate_pattern=FINAL, parked=parked, second=second)
    assert_clean(o)
    assert o.status("parked") == (200, None), o.summary()
    if third_manager:
        assert code(o.results["second"]) in (403, 404), o.summary()
    else:
        assert o.status("second") == (400, "validation_failed"), o.summary()
    with s.w.engine.connect() as c:
        open_count = c.execute(
            text(
                "SELECT count(*) FROM security.campaign_memberships WHERE campaign_membership_id "
                "IN (:a, :b) AND ended_at IS NULL"
            ),
            {"a": c_m, "b": x_m},
        ).scalar_one()
        assert c.execute(
            text("SELECT security.campaign_has_access_manager(:c)"), {"c": s.w.campaign_id}
        ).scalar_one()
    assert open_count == 1


def _keeper_role(s: Scene) -> uuid.UUID:
    return rows(
        s.w.engine,
        "SELECT membership_role_id AS id FROM security.membership_roles WHERE campaign_membership_id = :m",
        m=s.m.keeper_membership,
    )[0]["id"]


def _two_managers(s: Scene, order: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """The keeper and the manager of the scene as (C user, C membership, X user, X membership), C below or above X by
    membership id. Their non-expiring `access.manage` roles are the only ones left."""
    pair = sorted(
        [
            (s.m.keeper_membership, s.m.keeper_user),
            (s.m.manager_membership, s.m.manager_user),
        ]
    )
    (lo_m, lo_u), (hi_m, hi_u) = pair
    if order == "cmC_below_cmX":
        return lo_u, lo_m, hi_u, hi_m
    return hi_u, hi_m, lo_u, lo_m


@pytest.mark.parametrize("arrival", ("first_end_parked", "second_end_parked"))
def test_two_managers_ending_the_same_member_serialize_and_write_one_audit_row(
    arrival: str, s: Scene, e: Member, pool: Pool
) -> None:
    """*race*: two managers end the same member. The second finds the membership ended and answers the documented
    no-op (200, no second audit row, no second closure); no deadlock."""

    def by(user: uuid.UUID) -> Any:
        return post(pool, user, f"{s.w.base}/memberships/{e.membership}/end")

    first = lambda: by(s.m.manager_user)  # noqa: E731
    second = lambda: by(s.m.keeper_user)  # noqa: E731
    parked, other = (first, second) if arrival == "first_end_parked" else (second, first)
    o = race(s.w, pool, gate_pattern=FINAL, parked=parked, second=other)
    assert_clean(o)
    assert (o.status("parked"), o.status("second")) == ((200, None), (200, None)), o.summary()
    assert len(audit_row(s, e.membership)) == 1
    assert open_dependents(s, e.membership) == NONE_OPEN


@pytest.mark.parametrize("arrival", ("self_end_parked", "other_end_parked"))
def test_a_manager_ending_themselves_and_another_manager_ending_them_serialize(
    arrival: str, s: Scene, pool: Pool
) -> None:
    """*race*: the manager ends their own membership while the keeper ends it too. Whoever commits first wins; the
    other is the documented no-op (the keeper, still authorized) or is refused (the manager, whose authority the
    first end took); one audit row, no deadlock."""
    target = s.m.manager_membership

    def self_end() -> Any:
        return post(pool, s.m.manager_user, f"{s.w.base}/memberships/{target}/end")

    def other_end() -> Any:
        return post(pool, s.m.keeper_user, f"{s.w.base}/memberships/{target}/end")

    if arrival == "self_end_parked":
        o = race(s.w, pool, gate_pattern=FINAL, parked=self_end, second=other_end)
        expected = ((200, None), (200, None))
    else:
        o = race(s.w, pool, gate_pattern=FINAL, parked=other_end, second=self_end)
        assert code(o.results["second"]) in (403, 404), o.summary()
        expected = None
    assert_clean(o)
    if expected is not None:
        assert (o.status("parked"), o.status("second")) == expected, o.summary()
    assert len(audit_row(s, target)) == 1
    assert state(s, target).membership[0] is True


ROLE_ROUTES = ("assign", "revoke", "change")


@pytest.mark.parametrize("order", ("cmC_below_cmX", "cmC_above_cmX"))
@pytest.mark.parametrize("arrival", ("end_parked", "role_route_parked"))
@pytest.mark.parametrize("route", ROLE_ROUTES)
def test_the_end_and_the_role_routes_serialize_without_a_cycle_in_both_orders(
    route: str, arrival: str, order: str, w: World, pool: Pool
) -> None:
    """*race*: the end of a member against assign, revoke and change on that member, both orderings, both membership-id
    orders. End parked (holding every lock): the route queues, then finds the membership ended or the row revoked
    and gives its unchanged refusal (assign 404 `not_found`, BA-404; revoke the documented no-op 200; change 409).
    Route parked: the end queues behind it and closes whatever the route added (200)."""
    from tests.database.test_r01_s5e2_lock_order import membership_pair
    from tests.factories import system_role_id

    make_managers(w.engine, w.campaign_id, label="S5E3 roles")
    cast = membership_pair(w, order, "S5E3R", c_roles=("campaign_owner",), x_roles=("player",))
    with w.engine.connect() as c:
        observer = system_role_id(c, "observer")
    player_row = rows(
        w.engine,
        "SELECT membership_role_id AS id FROM security.membership_roles WHERE campaign_membership_id = :m",
        m=cast.x_m,
    )[0]["id"]

    def end_() -> Any:
        return post(pool, cast.c_user, f"{w.base}/memberships/{cast.x_m}/end")

    def role_route() -> Any:
        if route == "assign":
            return post(
                pool,
                cast.c_user,
                f"{w.base}/memberships/{cast.x_m}/roles",
                {"role_id": str(observer)},
            )
        if route == "revoke":
            return post(pool, cast.c_user, f"{w.base}/memberships/roles/{player_row}/revoke")
        return post(
            pool,
            cast.c_user,
            f"{w.base}/memberships/roles/{player_row}/change",
            {"new_role_id": str(observer)},
        )

    if arrival == "end_parked":
        o = race(w, pool, gate_pattern=FINAL, parked=end_, second=role_route)
        assert_clean(o)
        assert o.status("parked") == (200, None), o.summary()
        assert (
            o.status("second")
            == {
                "assign": (404, "not_found"),
                "revoke": (200, None),
                "change": (409, "conflict"),
            }[route]
        ), o.summary()
    else:
        o = race(w, pool, gate_pattern=FINAL, parked=role_route, second=end_)
        assert_clean(o)
        assert code(o.results["parked"]) in (200, 201), o.summary()
        assert o.status("second") == (200, None), o.summary()
    open_roles = rows(
        w.engine,
        "SELECT membership_role_id FROM security.membership_roles WHERE campaign_membership_id = :m "
        "AND revoked_at IS NULL",
        m=cast.x_m,
    )
    assert not open_roles, "no role row of the ended member stays open"
