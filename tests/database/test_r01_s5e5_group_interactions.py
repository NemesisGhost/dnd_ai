# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E5: the six access-group routes against the writers their lock sets touch, both transaction orderings.

* **T-5** (correction design section 5): the three-party schedule of the NF-1 cycle with each of **update, deactivate,
  reactivate and add** as the group locker (the S5-E4 grant is T-2 in `test_r01_s5e5_group_races.py`), both role-id orders. X
  (the group route) is parked right after its group lock (it holds its role rows `FOR SHARE` and the group `FOR UPDATE`); C
  (revelation creation) is *observed* waiting at the group on X's backend; V (C's revoke of X's role) is *observed* waiting at its
  ordered role statement holding no row. Released: no driver exception, the deadlock counter unmoved, X then C then V.
* **T-7** (owner-approved amendment): create / reactivate introduce no cycle (T-7a, CA-1); the *independent* keyed-authoring /
  role-revoke DEF-019 cycle was precisely characterized (T-7 with a group route in the schedule, T-7b without one): one 40P01 on a
  cycle-edge statement, either request the victim. R01 O-2 (the keyed authoring opt-in) removed the cycle: both are now regressions
  (`assert_authoring_revoke_serialized`): no driver exception, the deadlock counter unmoved, the revoke committed, the author
  refused at its scope with nothing left, the key reusable. At the parent (`369bd8a`) the cycle cases fail with one 40P01.
* **Pairs** (design section 10.7, items 1-9): a group route and one other writer, each *parked at its final authority statement*
  (every lock held) in turn; the other is observed queued or finished; no driver exception, no moved deadlock counter, the
  statuses the pair allows, and the invariant the pair must keep.

Every wait is observed (`pg_blocking_pids`), never assumed; a gate that cannot be reached is a SETUP failure.
"""

import re
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
    error_of,
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
# T-7: CA-1 (group create / reactivate) and the independent keyed-authoring / role-revoke cycle (DEF-019)
# =====================================================================================================
#
# Owner-approved amendment (recorded in the uncommitted design and plan): the original "the whole three-party schedule is
# clean" expectation is replaced by (1) group create / reactivate introduce no cycle (T-7a) and (2) the independent DEF-019
# authoring/revoke cycle stays *precisely characterized* (T-7, T-7b), not fixed. This does not approve a new cycle, close
# DEF-019 or lift its before-A6 / R01-closure requirement. (R01 O-2 has since removed that cycle: T-7 and T-7b are
# serialization regressions now; DEF-019 is not closed by that.)
#
# Every snapshot below is scoped to this test's own actor, idempotency key, role row, entity name and group; none counts a table
# or the audit log globally.

OK_REVOKE = (200, None)
OK_AUTHORING_RESPONSE = (201, None)
INTERNAL_ERROR = (500, "internal_error")
#: The current-authority refusal of the author's retry once the revoke committed (its `gm` role is gone; 403 `forbidden`).
AUTHOR_REFUSED = (403, "forbidden")
#: The refusal of a keyed authoring request whose role was revoked while it waited: the scope's existing early check
#: (404 `not_found`), as opposed to the route capability check (`AUTHOR_REFUSED`) a retry meets.
AUTHOR_REFUSED_IN_FLIGHT = (404, "not_found")
#: The audit rows a successful keyed `create_dungeon` writes: one, created, naming the entity, `name` the only initial field
#: (summary, danger level and parent are null and so omitted; the name is a redacted content field).
CREATE_COMMAND = "create_dungeon"
REVOKE_COMMAND = "revoke_membership_role"
GROUP_COMMANDS = {
    "create": "create_access_group",
    "reactivate": "reactivate_access_group",
}
ALL_GROUP_COMMANDS = (
    "create_access_group",
    "update_access_group",
    "deactivate_access_group",
    "reactivate_access_group",
    "add_access_group_member",
    "remove_access_group_member",
)

_AUDIT_COLUMNS = (
    "SELECT cl.command_name, ca.code AS action, cl.schema_name, cl.table_name, cl.record_id, cl.entity_id, "
    "cl.world_id, cl.actor_user_id, cl.source_id, cl.reason, cl.changed_fields "
    "FROM audit.change_log cl JOIN audit.change_actions ca ON ca.change_action_id = cl.change_action_id "
)


def outcome(response: Any) -> tuple[int, str | None]:
    return (code(response), error_of(response))


def keyed_author(pool: Pool, w: World, name: str, key: str) -> Any:
    """The keyed authoring request of the cycle (the author is `w.gm_user`); `name` and `key` are fixed so a retry reuses them."""
    return post(
        pool,
        w.gm_user,
        f"{w.base}/authoring/dungeons",
        {"name": name, "summary": None},
        **{"Idempotency-Key": key},
    )


def author_rows(w: World, *, name: str, key: str) -> dict[str, Any]:
    """Every row the keyed `create_dungeon` request owns, scoped to this author (`w.gm_user`), this key and this name: the entity
    and its dungeon-specific rows, its provenance source, its revision, its audit rows and its reservation/receipt."""
    e = w.engine
    entities = rows(
        e,
        "SELECT e.entity_id, et.code AS entity_type, cs.code AS canon_status, ls.code AS lifecycle_status, "
        "e.created_by_user_id, e.source_id, e.row_version, e.summary, e.canonical_name FROM core.entities e "
        "JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id "
        "JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id "
        "JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id "
        "WHERE e.world_id = :w AND e.canonical_name = :n ORDER BY e.entity_id",
        w=w.world_id,
        n=name,
    )
    ids = [r["entity_id"] for r in entities]
    return {
        "entities": entities,
        "locations": rows(
            e,
            "SELECT location_id, parent_location_id FROM world.locations WHERE location_id = ANY(:i) ORDER BY 1",
            i=ids,
        ),
        "dungeons": rows(
            e,
            "SELECT dungeon_id, danger_level FROM world.dungeons WHERE dungeon_id = ANY(:i) ORDER BY 1",
            i=ids,
        ),
        "revisions": rows(
            e,
            "SELECT entity_id, world_id, row_version, revision_kind, created_by_user_id FROM core.entity_revisions "
            "WHERE entity_id = ANY(:i) ORDER BY entity_id, row_version",
            i=ids,
        ),
        "sources": rows(
            e,
            "SELECT s.source_id, st.code AS source_type, s.title, s.world_id FROM core.sources s "
            "JOIN core.source_types st ON st.source_type_id = s.source_type_id "
            "WHERE s.world_id = :w AND s.created_by_user_id = :u ORDER BY s.source_id",
            w=w.world_id,
            u=w.gm_user,
        ),
        "audits": rows(
            e,
            _AUDIT_COLUMNS
            + "WHERE cl.world_id = :w AND cl.actor_user_id = :u AND cl.command_name = :c "
            "ORDER BY cl.change_log_id",
            w=w.world_id,
            u=w.gm_user,
            c=CREATE_COMMAND,
        ),
        "receipts": rows(
            e,
            "SELECT idempotency_key, response_status_code, response_body, completed_at IS NOT NULL AS completed, "
            "request_fingerprint IS NOT NULL AS fingerprinted FROM security.idempotent_requests "
            "WHERE actor_user_id = :u AND campaign_id = :c AND idempotency_key = :k",
            u=w.gm_user,
            c=w.campaign_id,
            k=key,
        ),
    }


def revoke_rows(w: World, *, revoker: uuid.UUID) -> dict[str, Any]:
    """Every row the revoke of `w.gm_role` owns: the whole role row, the delegations that role anchors, and the revoke audit rows
    naming it."""
    e = w.engine
    return {
        "role_row": rows(
            e,
            "SELECT to_jsonb(mr) AS r FROM security.membership_roles mr WHERE mr.membership_role_id = :r",
            r=w.gm_role,
        )[0]["r"],
        "delegations": rows(
            e,
            "SELECT to_jsonb(d) AS r FROM security.character_reveal_delegations d "
            "WHERE d.gm_membership_role_id = :r ORDER BY d.character_reveal_delegation_id",
            r=w.gm_role,
        ),
        "audits": rows(
            e,
            _AUDIT_COLUMNS
            + "WHERE cl.world_id = :w AND cl.record_id = :r AND cl.command_name = :c "
            "ORDER BY cl.change_log_id",
            w=w.world_id,
            r=w.gm_role,
            c=REVOKE_COMMAND,
        ),
        "revoker": revoker,
    }


def group_rows(
    w: World, *, actor: uuid.UUID, name: str | None, archived: uuid.UUID | None
) -> dict[str, Any]:
    """The group operation's own rows, scoped to the actor and the group (by `name` for a create, by id for a reactivate) and
    every access-group audit row of that actor in the world. With neither a name nor an id (the no-group control) the groups are
    every group of this test's campaign."""
    e = w.engine
    groups = rows(
        e,
        "SELECT ag.access_group_id, ag.name, ls.code AS lifecycle_status FROM security.access_groups ag "
        "JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = ag.lifecycle_status_id "
        "WHERE ag.campaign_id = :c AND (CAST(:n AS text) IS NULL AND CAST(:g AS uuid) IS NULL "
        "OR ag.name = :n OR ag.access_group_id = :g) ORDER BY ag.access_group_id",
        c=w.campaign_id,
        n=name,
        g=archived,
    )
    return {
        "groups": groups,
        "audits": rows(
            e,
            _AUDIT_COLUMNS
            + "WHERE cl.world_id = :w AND cl.actor_user_id = :u AND cl.command_name = ANY(:c) "
            "ORDER BY cl.change_log_id",
            w=w.world_id,
            u=actor,
            c=list(ALL_GROUP_COMMANDS),
        ),
    }


def assert_author_won(
    w: World, *, name: str, key: str, state: dict[str, Any], summary: str
) -> uuid.UUID:
    """The complete committed result of one successful `create_dungeon`: entity, dungeon rows, source, revision, the single
    `create_dungeon` audit row and the completed reservation. Returns the entity id."""
    assert len(state["entities"]) == 1, f"one entity: {summary}"
    ent = state["entities"][0]
    eid = ent["entity_id"]
    assert {k: ent[k] for k in ent if k != "entity_id"} == {
        "entity_type": "dungeon",
        "canon_status": "draft",
        "lifecycle_status": "active",
        "created_by_user_id": w.gm_user,
        "source_id": ent["source_id"],
        "row_version": ent["row_version"],
        "summary": None,
        "canonical_name": name,
    }, f"entity: {summary}"
    assert state["locations"] == [{"location_id": eid, "parent_location_id": None}], summary
    assert state["dungeons"] == [{"dungeon_id": eid, "danger_level": None}], summary
    assert state["revisions"] == [
        {
            "entity_id": eid,
            "world_id": w.world_id,
            "row_version": ent["row_version"],
            "revision_kind": "created",
            "created_by_user_id": w.gm_user,
        }
    ], f"revision: {summary}"
    assert [
        (s["source_id"], s["source_type"], s["title"], s["world_id"]) for s in state["sources"]
    ] == [(ent["source_id"], "gm_entry", "GM entry", w.world_id)], f"source: {summary}"
    assert len(state["audits"]) == 1, f"exactly one create_dungeon audit row: {summary}"
    audit = state["audits"][0]
    assert {k: audit[k] for k in audit if k != "changed_fields"} == {
        "command_name": CREATE_COMMAND,
        "action": "created",
        "schema_name": "core",
        "table_name": "entities",
        "record_id": eid,
        "entity_id": eid,
        "world_id": w.world_id,
        "actor_user_id": w.gm_user,
        "source_id": ent["source_id"],
        "reason": None,
    }, f"audit: {summary}"
    assert set(audit["changed_fields"]) == {"name"}, f"audit payload fields: {summary}"
    assert len(state["receipts"]) == 1, f"one reservation: {summary}"
    receipt = state["receipts"][0]
    assert (
        receipt["idempotency_key"],
        receipt["response_status_code"],
        receipt["completed"],
        receipt["fingerprinted"],
    ) == (key, 201, True, True), f"receipt: {summary}"
    assert str(eid) in {str(v) for v in receipt["response_body"].values()}, (
        f"receipt body: {summary}"
    )
    return eid  # type: ignore[no-any-return]


def assert_author_absent(state: dict[str, Any], before: dict[str, Any], summary: str) -> None:
    """The author's transaction left nothing: no entity or dungeon-specific row, no revision, no source beyond the pre-existing
    ones, no `create_dungeon` audit row, no reservation or receipt."""
    for table in ("entities", "locations", "dungeons", "revisions", "audits", "receipts"):
        assert state[table] == [], f"author {table} should be absent: {summary}"
    assert state["sources"] == before["sources"], f"author source rows changed: {summary}"


def assert_revoke_won(
    w: World, *, revoker: uuid.UUID, before: dict[str, Any], state: dict[str, Any], summary: str
) -> None:
    """The committed revoke: only the role's `revoked_at` changed (null before, set now), the delegations anchored on it are as
    before, and there is exactly one `revoke_membership_role` audit row naming it, by the revoker."""
    role, was = state["role_row"], before["role_row"]
    assert was["revoked_at"] is None and role["revoked_at"] is not None, f"revoked_at: {summary}"
    assert {k: v for k, v in role.items() if k != "revoked_at"} == {
        k: v for k, v in was.items() if k != "revoked_at"
    }, f"the revoke changed more than revoked_at: {summary}"
    assert state["delegations"] == before["delegations"], f"delegations: {summary}"
    assert len(state["audits"]) == 1, f"exactly one revoke audit row: {summary}"
    audit = state["audits"][0]
    assert {k: audit[k] for k in audit if k != "changed_fields"} == {
        "command_name": REVOKE_COMMAND,
        "action": audit["action"],
        "schema_name": "security",
        "table_name": "membership_roles",
        "record_id": w.gm_role,
        "entity_id": None,
        "world_id": w.world_id,
        "actor_user_id": revoker,
        "source_id": None,
        "reason": None,
    }, f"revoke audit: {summary}"


def assert_revoke_absent(before: dict[str, Any], state: dict[str, Any], summary: str) -> None:
    """The aborted revoke left nothing: the role row byte-for-byte as before, no delegation touched, no revoke audit row."""
    assert state["role_row"] == before["role_row"], (
        f"the aborted revoke changed the role row: {summary}"
    )
    assert state["delegations"] == before["delegations"], f"delegations: {summary}"
    assert state["audits"] == [], f"the aborted revoke left an audit row: {summary}"


def assert_group_effects(
    state: dict[str, Any], before: dict[str, Any], expect: dict[str, Any] | None, summary: str
) -> None:
    """`expect` is None for the no-group control: nothing group-shaped changed. Otherwise exactly one group row in the expected
    lifecycle status and exactly one audit row of the expected command naming it, by the actor."""
    if expect is None:
        assert state == before, f"a group effect in a schedule without a group route: {summary}"
        assert state["audits"] == [], summary
        return
    assert [g["lifecycle_status"] for g in state["groups"]] == [expect["status"]], (
        f"group: {summary}"
    )
    gid = state["groups"][0]["access_group_id"]
    assert len(state["audits"]) == 1, f"one group audit row: {summary}"
    audit = state["audits"][0]
    assert (audit["command_name"], audit["record_id"], audit["actor_user_id"]) == (
        expect["command"],
        gid,
        expect["actor"],
    ), f"group audit: {summary}"


def assert_authoring_revoke_serialized(
    w: World,
    pool: Pool,
    *,
    name: str,
    key: str,
    revoker: uuid.UUID,
    author_before: dict[str, Any],
    revoke_before: dict[str, Any],
    group_before: dict[str, Any],
    group_expect: dict[str, Any] | None,
    group_probe: Callable[[], dict[str, Any]],
    failures: list[tuple[str | None, str]],
    delta: int,
    author_response: Any,
    revoke_response: Any,
) -> None:
    """The exact contract of the formerly deferred authoring/revoke schedule after the keyed authoring opt-in (R01 O-2, DEF-019,
    CL-E10-1). The revoke of the author's role committed first and the author, which waited for the row the revoke held (or was
    released after it), is refused at its scope by the existing early check: no driver exception, the deadlock counter unmoved,
    the revoke a 200 with its complete rows (the role's `revoked_at` only, the delegations as before, one audit row), the
    author a 404 `not_found` with nothing left (no entity, no audit row, no reservation), the group operation's rows exact (or
    absent for the control), and the same key reusable: the retry is refused by the route's capability check (403 `forbidden`) and
    still creates nothing."""
    author_state = author_rows(w, name=name, key=key)
    revoke_state = revoke_rows(w, revoker=revoker)
    group_state = group_probe()
    summary = f"failures={failures} delta={delta}"
    assert failures == [], summary
    assert delta == 0, summary
    assert_group_effects(group_state, group_before, group_expect, summary)
    assert outcome(revoke_response) == OK_REVOKE, summary
    assert outcome(author_response) == AUTHOR_REFUSED_IN_FLIGHT, summary
    assert_revoke_won(w, revoker=revoker, before=revoke_before, state=revoke_state, summary=summary)
    assert_author_absent(author_state, author_before, summary)
    # the retry, on the same pool (the pooled connections carry nothing over), with the authoring key reused
    again = keyed_author(pool, w, name, key)
    assert outcome(again) == AUTHOR_REFUSED, (
        f"the retry executes (not a replay) and is refused: {again.text}"
    )
    assert pool.failures == [], f"the retry failed in the driver: {pool.failures}"
    assert_author_absent(author_rows(w, name=name, key=key), author_before, "after the retry")
    assert revoke_rows(w, revoker=revoker) == revoke_state, "the winning revoke's rows changed"
    assert_group_effects(group_probe(), group_before, group_expect, "after the retry")
    assert group_probe() == group_state, "the retry changed the group operation's rows"
    assert not _idle_in_transaction(w), "a backend was left idle in a transaction"


def _idle_in_transaction(w: World) -> int:
    return int(
        rows(
            w.engine,
            "SELECT count(*) AS n FROM pg_stat_activity WHERE datname = current_database() "
            "AND state LIKE 'idle in transaction%'",
        )[0]["n"]
    )


@pytest.mark.parametrize("order", ("m_row_first", "y_rows_first"))
@pytest.mark.parametrize("route", ("create", "reactivate"))
def test_t7_the_authoring_revoke_schedule_with_a_group_route_serializes_after_the_authoring_opt_in(
    route: str, order: str, w: World, pool: Pool
) -> None:
    """*race* (T-7, serialized by R01 O-2). The schedule T-7 specified (correction design section 5): M (`w.gm_user`) authors,
    keyed (parked right after its reservation); Y (an owner) revokes **M's role** (V) and creates or reactivates an access group
    (Y is parked at its campaign lock, holding its role rows `FOR SHARE`).

    This was the **characterized** two-party DEF-019 cycle (keyed authoring against a role writer, CL-E10-1; owner-approved T-7
    amendment): when M's role row had the lower id (`m_row_first`) the author's reservation held the campaign `FOR KEY SHARE`
    while it waited for the row the revoke held, and the revoke, after Y committed, wanted the campaign `FOR UPDATE`: one 40P01
    (the opt-in's fail-before, recorded in the O-2 evidence). The reservation no longer locks the campaign (its foreign key is
    deferred), so the author holds nothing the revoke wants: Y commits, V proceeds and commits, and the author, released behind it,
    is refused at its scope (`assert_authoring_revoke_serialized`). CA-1 is shown by `test_t7a_...` (create / reactivate never wait
    for the author). `y_rows_first` is the control (V waits at Y's rows first and holds nothing): clean as it always was, every
    row of the author, the revoke and the group committed."""
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
    group_name = f"T7 {uuid.uuid4().hex[:6]}"
    author_name, author_key = f"T7 dungeon {uuid.uuid4().hex[:8]}", str(uuid.uuid4())
    with w.engine.begin() as c:
        archived = make_access_group(
            c,
            w.campaign_id,
            name=f"T7 archived {uuid.uuid4().hex[:6]}",
            lifecycle_status_code="archived",
        )

    def y_call() -> Any:
        if route == "create":
            return post(pool, y_user, f"{w.base}/access-groups", {"name": group_name})
        return post(pool, y_user, f"{w.base}/access-groups/{archived}/reactivate", {})

    def group_probe() -> dict[str, Any]:
        return group_rows(
            w,
            actor=y_user,
            name=group_name if route == "create" else None,
            archived=archived if route == "reactivate" else None,
        )

    group_expect = {
        "status": "active",
        "command": GROUP_COMMANDS[route],
        "actor": y_user,
    }
    admin = w.engine
    author_before = author_rows(w, name=author_name, key=author_key)
    revoke_before = revoke_rows(w, revoker=y_user)
    group_before = group_probe()
    before = deadlocks_now(admin)
    results: dict[str, Any] = {}
    # both gates are registered before any request starts: a plan refuses a change of the engine's listeners while it is open
    with (
        NthGate(pool.engine, CAMPAIGN_LOCK) as ygate,
        NthGate(pool.engine, AUTHORING_WORLD) as agate,
    ):
        y = run_in_thread("y", y_call)
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
                what="the author waiting for its role row behind V",
            )
        else:
            results["a"] = finish(a, "the author finishes while Y is parked")
        ygate.release()
        results["y"] = finish(y, "y finishes")
        results["w"] = finish(wreq, "w finishes")
        if "a" not in results:
            results["a"] = finish(a, "a finishes")
    delta = settled_deadlock_delta(admin, pool, before)
    # the evidence is captured here, before any cleanup or retry
    failures = list(pool.failures)
    y_expected = (201 if route == "create" else 200, None)
    assert outcome(results["y"]) == y_expected, (results["y"].text, failures)
    if m_first:
        assert_authoring_revoke_serialized(
            w,
            pool,
            name=author_name,
            key=author_key,
            revoker=y_user,
            author_before=author_before,
            revoke_before=revoke_before,
            group_before=group_before,
            group_expect=group_expect,
            group_probe=group_probe,
            failures=failures,
            delta=delta,
            author_response=results["a"],
            revoke_response=results["w"],
        )
    else:
        summary = f"failures={failures} delta={delta}"
        assert failures == [] and delta == 0, summary
        assert outcome(results["w"]) == OK_REVOKE
        assert outcome(results["a"]) == OK_AUTHORING_RESPONSE
        assert_author_won(
            w,
            name=author_name,
            key=author_key,
            state=author_rows(w, name=author_name, key=author_key),
            summary=summary,
        )
        assert_revoke_won(
            w,
            revoker=y_user,
            before=revoke_before,
            state=revoke_rows(w, revoker=y_user),
            summary=summary,
        )
        assert_group_effects(group_probe(), group_before, group_expect, summary)


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


@pytest.mark.parametrize("arrival", ("author_parked", "revoke_parked"))
def test_t7b_the_two_party_authoring_schedule_with_a_role_revoke_serializes_after_the_authoring_opt_in(
    arrival: str, w: World, pool: Pool
) -> None:
    """*race* (T-7b, serialized by R01 O-2; the no-group-route control of T-7). It was a characterized two-party cycle: keyed
    authoring parked after its reservation held the campaign `FOR KEY SHARE`, the revoke of the author's role by an owner held
    the author's row and then wanted the campaign `FOR UPDATE` behind it, and the released author wanted the row the revoke held:
    one 40P01 (the opt-in's fail-before). With the reservation no longer locking the campaign:

    * `author_parked`: the revoke does not wait for the parked author at all, commits, and the released author is refused at its
      scope;
    * `revoke_parked`: the revoke is parked at its account statement (it holds the author's role row, not yet the campaign), the
      author queues at its role rows behind that backend alone and holding nothing on the campaign, and, released, the revoke
      commits and the author is refused.

    Both: the exact contract of `assert_authoring_revoke_serialized`, and no group operation effect at all (no access-group row
    change, no access-group audit row of the actor)."""
    from tests.database.test_r01_s5e2_lock_order import ACTOR_ACCOUNT, race

    author_name, author_key = f"T7b dungeon {uuid.uuid4().hex[:8]}", str(uuid.uuid4())
    admin = w.engine

    def group_probe() -> dict[str, Any]:
        return group_rows(w, actor=w.owner, name=None, archived=None)

    def revoke() -> Any:
        return post(pool, w.owner, f"{w.base}/memberships/roles/{w.gm_role}/revoke", {})

    author_before = author_rows(w, name=author_name, key=author_key)
    revoke_before = revoke_rows(w, revoker=w.owner)
    group_before = group_probe()
    before = deadlocks_now(admin)
    if arrival == "author_parked":
        with NthGate(pool.engine, AUTHORING_WORLD) as agate:
            a = run_in_thread("a", lambda: keyed_author(pool, w, author_name, author_key))
            assert agate.reached.wait(WAIT_SECONDS), (
                "SETUP: the author never reached its world lock"
            )
            assert agate.pid is not None
            # the revoke needs nothing the parked author holds: it finishes while the author is parked
            revoke_response = finish(
                run_in_thread("w", revoke), "the revoke finishes while the author is parked"
            )
            agate.release()
            author_response = finish(a, "a finishes")
    else:
        o = race(
            w,
            pool,
            gate_pattern=ACTOR_ACCOUNT,
            parked=revoke,
            second=lambda: keyed_author(pool, w, author_name, author_key),
        )
        assert o.blocked, f"the author never queued behind the parked revoke: {o.summary()}"
        for row in o.blocked:
            assert len(row["blockers"]) == 1, f"more than one blocker: {o.summary()}"
            assert re.search(AUTHOR_ROLES, row["query"]), row["query"]
        revoke_response, author_response = o.results["parked"], o.results["second"]
    delta = settled_deadlock_delta(admin, pool, before)
    failures = list(pool.failures)
    assert_authoring_revoke_serialized(
        w,
        pool,
        name=author_name,
        key=author_key,
        revoker=w.owner,
        author_before=author_before,
        revoke_before=revoke_before,
        group_before=group_before,
        group_expect=None,
        group_probe=group_probe,
        failures=failures,
        delta=delta,
        author_response=author_response,
        revoke_response=revoke_response,
    )


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
