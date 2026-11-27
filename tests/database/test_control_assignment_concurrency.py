# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""P15-C11-S02-T01: the concurrency evidence for the control-assignment writers (F22-F27, the unique-index waits).

Evidence classes, as in the S5-E2/S5-E4 route tests:

- **race**: one request parked at a named statement (its locks held, its writes uncommitted) and a competitor on the
  other side, every wait observed through `pg_blocking_pids`, never assumed.
- **index wait** (`test_a_competing_live_primary_is_a_unique_wait`, `test_a_competing_live_assignment_is_a_unique_wait`):
  the declared `UniqueWait` entries of the assignment INSERTs, shown with a real competing INSERT that queues behind the
  request on the index key and then fails on the unique index, never a second live row. These are **competing** waits
  (S01 contract 5); `test_an_assignment_insert_never_waits_on_the_legacy_index` is the "never enters" counterpart.
- **matrix** (F27): each writer against the other writers of the same rows, started together and repeated a bounded
  number of times, with the database's deadlock counter compared before and after.
"""

import re
import threading
import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from dnd_ai.queries.content_preconditions import archive_blocked_reason
from tests.database.test_control_assignment_commands import (  # noqa: F401 - fixtures used by name
    COMMANDS,
    Env,
    Factory,
    Person,
    _tidy,
    assign_body,
    assign_path,
    build_env,
    env,
    post,
    replace_body,
    replace_path,
    revoke_path,
    row_of,
    seed,
    state,
)
from tests.database.test_control_unique_wait_evidence import (
    LIVE_ASSIGNMENT,
    LIVE_PRIMARY,
    constraint_of,
    fk_checks_started,
)
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    pooled,
    pooled_factory,
)
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixtures used by name
    World,
    code,
    error_of,
    w,
)
from tests.database.test_r01_s5e2_membership_routes import (  # noqa: F401 - fixtures used by name
    Scene,
    m,
    pooled2,
    pooled2_factory,
    s,
    waiting_statement,
)
from tests.factories import (
    make_character,
    make_control_assignment,
    make_membership_character_relationship,
    make_system_role_assignment,
    make_user,
    relationship_type_id,
)
from tests.http_race_support import (
    StatementGate,
    deadlock_count,
    run_in_thread,
    wait_for_deadlock_count,
    wait_until_blocked,
    wait_until_pid_blocks,
)
from tests.lock_race_support import LockRace
from tests.r01_s5d_support import wait_lapsed

pytestmark = pytest.mark.database

AUDIT_INSERT = r"^INSERT INTO audit\.change_log"
CAMPAIGN_U = r"campaign\.campaigns"


# --- the unique-index waits (S01 contract 5) ---------------------------------------------------------------------


def _compete(s: Scene, env: Env, route: str) -> tuple[Any, Any]:
    """The path and body of the writer under test: assign a primary, or replace the primary."""
    if route == "assign":
        return assign_path(s, env.character), assign_body(env.p1, "primary_controller")
    seed(s, env.p3, env.character, "primary_controller", "ongoing")
    return replace_path(s, env.character), replace_body(env.p1)


@pytest.mark.parametrize("route", ["assign", "replace"])
def test_a_competing_live_primary_is_a_unique_wait(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory, route: str
) -> None:
    """*race*, `ux_membership_character_relationships_live_primary` on the INSERT: a competitor inserting a primary of
    another membership on the same character while the request is parked at its audit insert (its row inserted,
    uncommitted) is blocked by *the request*; when the request commits it fails on the unique index naming
    `..._live_primary`, never a second live primary.

    S02-R3 correction: "blocked by the request" alone does not name the wait (a same-parents competitor outside the
    index is blocked too, at its foreign key: `test_control_unique_wait_evidence.py`). The competitor here has started
    no foreign-key check while it waits (`fk_checks_started`), so it waits at the index insertion, and the violation
    names the index. The declared wait of the step's own statement is shown in isolation by
    `test_control_unique_wait_evidence.py::test_r3_each_insert_statement_waits_on_the_named_index_alone`."""
    path, body = _compete(s, env, route)

    def competitor(c: Any) -> Any:
        return make_control_assignment(
            c,
            env.p2.membership,
            env.character,
            "primary_controller",
            "ongoing",
            campaign_id=s.w.campaign_id,
        )

    with StatementGate(pooled, AUDIT_INSERT) as gate:
        request = run_in_thread("assign", lambda: post(pooled_factory, env.owner.user, path, body))
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            queued = race.start("insert", competitor)
            race.wait_blocked_by(gate, expected=1)
            assert re.search(r"INSERT INTO security\.", waiting_statement(s.w.engine, gate.pid))
            assert queued.pid is not None
            assert fk_checks_started(s.w.engine, queued.pid) is False
            gate.release()
            response = request.wait("the writer finishes")
            race.join_all()
    assert code(response) == 201, response.text
    assert isinstance(queued.error, IntegrityError), queued.error
    assert constraint_of(queued.error) == LIVE_PRIMARY
    live = [r for r in state(s).rows if r[1] == "primary_controller" and not r[7]]
    assert len(live) == 1


@pytest.mark.parametrize("route", ["assign", "replace"])
def test_a_competing_live_assignment_is_a_unique_wait(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory, route: str
) -> None:
    """*race*, `ux_membership_character_relationships_live_assignment` on the INSERT: a competitor inserting a second
    assignment of the same membership on the same character is blocked by the request and then fails on the unique
    index naming `..._live_assignment`.

    S02-R3 correction: as for the live primary, the competitor has started no foreign-key check while it waits, and the
    violation names the index; the step's own wait is shown in isolation in `test_control_unique_wait_evidence.py`."""
    if route == "assign":
        path, body = assign_path(s, env.character), assign_body(env.p1, "co_controller")
    else:
        seed(s, env.p3, env.character, "primary_controller", "ongoing")
        path, body = replace_path(s, env.character), replace_body(env.p1)

    def competitor(c: Any) -> Any:
        return make_control_assignment(
            c,
            env.p1.membership,
            env.character,
            "co_controller",
            "ongoing",
            campaign_id=s.w.campaign_id,
        )

    with StatementGate(pooled, AUDIT_INSERT) as gate:
        request = run_in_thread("assign", lambda: post(pooled_factory, env.owner.user, path, body))
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            queued = race.start("insert", competitor)
            race.wait_blocked_by(gate, expected=1)
            assert re.search(r"INSERT INTO security\.", waiting_statement(s.w.engine, gate.pid))
            assert queued.pid is not None
            assert fk_checks_started(s.w.engine, queued.pid) is False
            gate.release()
            response = request.wait("the writer finishes")
            race.join_all()
    assert code(response) == 201, response.text
    assert isinstance(queued.error, IntegrityError), queued.error
    assert constraint_of(queued.error) == LIVE_ASSIGNMENT
    mine = [r for r in state(s).rows if r[2] == env.p1.membership and not r[7]]
    assert len(mine) == 1


@pytest.mark.parametrize("route", ["revoke", "replace"])
def test_a_revoke_leaving_the_assignment_indexes_never_waits_for_a_competing_insert(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory, route: str
) -> None:
    """*race*, the closing UPDATE of a revoke (and of a replace's old primary) leaves both assignment indexes: it
    inserts no index entry, so it takes no unique wait. A competitor inserting the freed key while the request is parked
    at its audit insert (every update done, uncommitted) queues behind *the request* (blocked by its pid); the request
    finishes while the competitor is still queued, then the competitor completes (the key is free)."""
    if route == "revoke":
        row = seed(s, env.p1, env.character, "co_controller", "ongoing")
        path, body, freed = revoke_path(s, row), {}, env.p1.membership
    else:
        seed(s, env.p3, env.character, "primary_controller", "ongoing")
        path, body, freed = replace_path(s, env.character), replace_body(env.p1), env.p3.membership

    def competitor(c: Any) -> Any:
        return make_control_assignment(
            c, freed, env.character, "co_controller", "ongoing", campaign_id=s.w.campaign_id
        )

    with StatementGate(pooled, AUDIT_INSERT) as gate:
        request = run_in_thread("writer", lambda: post(pooled_factory, env.owner.user, path, body))
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            queued = race.start("insert", competitor)
            race.wait_blocked_by(gate, expected=1)
            assert re.search(r"INSERT INTO security\.", waiting_statement(s.w.engine, gate.pid))
            gate.release()
            response = request.wait("the writer finishes while the competitor is queued")
            race.join_all()
    assert code(response) in (200, 201), response.text
    assert queued.error is None


@pytest.mark.parametrize("step_name", ["ASSIGN_INSERT", "REPLACE_INSERT"])
def test_an_assignment_insert_never_waits_on_the_legacy_index(
    s: Scene, env: Env, step_name: str
) -> None:
    """*index wait* (the counterpart, `_OUTSIDE`): connection B holds an uncommitted legacy relationship with the very
    key (membership, character, type) the assignment would have under the old rule; connection A runs the step's own
    statement under a lock timeout. A completes: an assignment row is outside the legacy partial index's predicate."""
    from dnd_ai.commands import control_assignment_plans as plans

    step = getattr(plans, step_name)
    with s.w.engine.connect() as b_conn, s.w.engine.connect() as a_conn:
        b_tx = b_conn.begin()
        make_membership_character_relationship(
            b_conn, env.p1.membership, env.character, relationship_type_id(b_conn, "co_controller")
        )
        a_tx = a_conn.begin()
        a_conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        binds = {
            "campaign": s.w.campaign_id,
            "membership": env.p1.membership,
            "character": env.character,
            "type": relationship_type_id(a_conn, "co_controller"),
            "kind": "ongoing",
            "time_from": None,
            "time_to": None,
            "granted_by": env.owner.membership,
            "notes": None,
        }
        names = set(step.statement.compile().params)
        error: BaseException | None = None
        try:
            a_conn.execute(step.statement, {k: v for k, v in binds.items() if k in names}).all()
        except DBAPIError as caught:
            error = caught
        a_tx.rollback()
        b_tx.rollback()
    assert error is None, f"the assignment insert waited on the legacy index: {error}"


def test_f8_a_campaign_archived_while_the_request_waits_is_the_409(
    s: Scene, env: Env, pooled2_factory: Factory
) -> None:
    """*race*: the campaign is active when the route admits the request and archived by the time the request has the
    campaign row; the refusal is the plan's 409, and nothing is written."""
    holder = s.w.engine.connect()
    tx = holder.begin()
    try:
        holder.execute(
            text(
                "UPDATE campaign.campaigns SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                "core.lifecycle_statuses WHERE code = 'archived') WHERE campaign_id = :c"
            ),
            {"c": s.w.campaign_id},
        )
        holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
        request = run_in_thread(
            "assign",
            lambda: post(
                pooled2_factory, env.owner.user, assign_path(s, env.character), assign_body(env.p1)
            ),
        )
        wait_until_pid_blocks(s.w.engine, holder_pid)
        tx.commit()
    finally:
        holder.close()
    response = request.wait("the assign finishes")
    assert code(response) == 409, response.text
    assert state(s).rows == ()


# --- F22: two primaries at once -----------------------------------------------------------------------------------


def test_f22_two_concurrent_primary_assigns_one_wins_and_the_other_is_the_classified_409(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory, pooled2_factory: Factory
) -> None:
    """*race*: request A is parked at its audit insert (campaign and the character's rows held); request B, for a
    different member, queues behind A. When A commits B re-reads the live set under its locks and is refused with
    `primary_controller_exists`: never a 500 and never a raw unique violation."""
    with StatementGate(pooled, AUDIT_INSERT) as gate:
        a = run_in_thread(
            "a",
            lambda: post(
                pooled_factory,
                env.owner.user,
                assign_path(s, env.character),
                assign_body(env.p1, "primary_controller"),
            ),
        )
        gate.wait_reached()
        b = run_in_thread(
            "b",
            lambda: post(
                pooled2_factory,
                s.w.gm_user,
                assign_path(s, env.character),
                assign_body(env.p2, "primary_controller"),
            ),
        )
        wait_until_blocked(s.w.engine, gate, expected=1)
        gate.release()
        first, second = a.wait("A finishes"), b.wait("B finishes")
    assert code(first) == 201, first.text
    assert code(second) == 409 and error_of(second) == "primary_controller_exists", second.text
    assert len([r for r in state(s).rows if r[1] == "primary_controller" and not r[7]]) == 1


# --- F23: revoke against assign -----------------------------------------------------------------------------------


def test_f23_a_revoke_and_an_assign_on_one_character_serialize_without_a_deadlock(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory, pooled2_factory: Factory
) -> None:
    row = seed(s, env.p1, env.character, "co_controller", "ongoing")
    before = deadlock_count(s.w.engine)
    with StatementGate(pooled, AUDIT_INSERT) as gate:
        a = run_in_thread(
            "revoke", lambda: post(pooled_factory, env.owner.user, revoke_path(s, row))
        )
        gate.wait_reached()
        b = run_in_thread(
            "assign",
            lambda: post(
                pooled2_factory, s.w.gm_user, assign_path(s, env.character), assign_body(env.p2)
            ),
        )
        wait_until_blocked(s.w.engine, gate, expected=1)
        gate.release()
        revoked, assigned = a.wait("revoke"), b.wait("assign")
    assert code(revoked) == 200 and revoked.json()["revoked"] is True
    assert code(assigned) == 201, assigned.text
    assert row_of(s, row)["revoked_at"] is not None
    assert len([r for r in state(s).rows if not r[7]]) == 1
    assert wait_for_deadlock_count(s.w.engine, before) == before


# --- F24: against the assignee's membership end ------------------------------------------------------------------


def test_f24_an_assign_after_the_end_of_its_assignee_is_the_409(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory, pooled2_factory: Factory
) -> None:
    with StatementGate(pooled, AUDIT_INSERT) as gate:
        end = run_in_thread(
            "end",
            lambda: _end(pooled_factory, s, env.p1.membership),
        )
        gate.wait_reached()
        assign = run_in_thread(
            "assign",
            lambda: post(
                pooled2_factory, env.owner.user, assign_path(s, env.character), assign_body(env.p1)
            ),
        )
        wait_until_blocked(s.w.engine, gate, expected=1)
        gate.release()
        ended, assigned = end.wait("end"), assign.wait("assign")
    assert code(ended) == 200, ended.text
    assert code(assigned) in (404, 409), assigned.text
    assert state(s).rows == ()


def test_f24_an_end_after_an_assign_revokes_the_assignment(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory, pooled2_factory: Factory
) -> None:
    with StatementGate(pooled, AUDIT_INSERT) as gate:
        assign = run_in_thread(
            "assign",
            lambda: post(
                pooled_factory, env.owner.user, assign_path(s, env.character), assign_body(env.p1)
            ),
        )
        gate.wait_reached()
        end = run_in_thread("end", lambda: _end(pooled2_factory, s, env.p1.membership))
        wait_until_blocked(s.w.engine, gate, expected=1)
        gate.release()
        assigned, ended = assign.wait("assign"), end.wait("end")
    assert code(assigned) == 201 and code(ended) == 200, (assigned.text, ended.text)
    # never a live assignment on an ended membership
    assert [r for r in state(s).rows if not r[7]] == []
    assert len(state(s).rows) == 1


def _end(factory: Factory, sc: Scene, membership: uuid.UUID) -> Any:
    with factory(sc.m.manager_user) as client:
        return client.post(f"{sc.w.base}/memberships/{membership}/end")


# --- F25: against the revocation of the caller's gm role, and the post-wait re-judge -----------------------------


def test_f25_an_assign_after_the_revocation_of_the_callers_role_is_403(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory, pooled2_factory: Factory
) -> None:
    """*race*: the role revoke commits first; the assign, parked on the role row, gets the 403 after its wait."""
    with StatementGate(pooled, AUDIT_INSERT) as gate:
        revoke = run_in_thread(
            "revoke",
            lambda: _revoke_role(pooled_factory, s, s.w.gm_role),
        )
        gate.wait_reached()
        assign = run_in_thread(
            "assign",
            lambda: post(
                pooled2_factory, s.w.gm_user, assign_path(s, env.character), assign_body(env.p1)
            ),
        )
        wait_until_blocked(s.w.engine, gate, expected=1)
        gate.release()
        revoked, assigned = revoke.wait("revoke"), assign.wait("assign")
    assert code(revoked) == 200, revoked.text
    assert code(assigned) == 403 and error_of(assigned) == "character_assign_control_required", (
        assigned.text
    )
    assert state(s).rows == ()


def _revoke_role(factory: Factory, sc: Scene, role: uuid.UUID) -> Any:
    with factory(sc.m.manager_user) as client:
        return client.post(f"{sc.w.base}/memberships/roles/{role}/revoke")


def test_f25_the_authority_is_judged_again_after_the_last_wait_before_any_eligibility_refusal(
    s: Scene, env: Env, pooled2_factory: Factory
) -> None:
    """The caller's gm assignment expires while the request waits for the campaign row. The assignee is also ineligible
    (ended). The refusal is the 403, never the eligibility 409: an unauthorized caller must not learn the assignee's
    state. Without the re-judge after the waits the eligibility refusal would come first (the final check would still
    refuse, but too late for precedence)."""
    from sqlalchemy.exc import DBAPIError  # noqa: F401

    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.campaign_memberships SET ended_at = now() WHERE campaign_membership_id = :m"
            ),
            {"m": env.p1.membership},
        )
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = clock_timestamp() + interval '3 seconds' "
                "WHERE membership_role_id = :r"
            ),
            {"r": s.w.gm_role},
        )
    holder = s.w.engine.connect()
    tx = holder.begin()
    try:
        holder.execute(
            text("SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c FOR UPDATE"),
            {"c": s.w.campaign_id},
        )
        holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
        request = run_in_thread(
            "assign",
            lambda: post(
                pooled2_factory, s.w.gm_user, assign_path(s, env.character), assign_body(env.p1)
            ),
        )
        wait_until_pid_blocks(s.w.engine, holder_pid)
        wait_lapsed(s.w.engine, s.w.gm_role)
    finally:
        tx.rollback()
        holder.close()
    response = request.wait("the assign finishes")
    assert code(response) == 403, response.text
    assert error_of(response) == "character_assign_control_required"
    assert state(s).rows == ()


# --- F26: against the archive of the character --------------------------------------------------------------------


def _archive_like_the_command(c: Any, character: uuid.UUID) -> str:
    """What `archive_entity` does at the database for an NPC: the entity row `FOR UPDATE`, the precondition (an NPC or
    player character with a live relationship or assignment is not archived), the lifecycle write."""
    c.execute(
        text("SELECT 1 FROM core.entities WHERE entity_id = :e FOR UPDATE"), {"e": character}
    ).all()
    blocked = archive_blocked_reason(c, entity_id=character, entity_type_code="npc")
    if blocked is not None:
        return "blocked"
    c.execute(
        text(
            "UPDATE core.entities SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
            "core.lifecycle_statuses WHERE code = 'archived'), archived_at = now() WHERE entity_id = :e"
        ),
        {"e": character},
    )
    return "archived"


def test_f26_an_assign_after_the_archive_of_the_character_is_the_404(
    s: Scene, env: Env, pooled2_factory: Factory
) -> None:
    holder = s.w.engine.connect()
    tx = holder.begin()
    try:
        assert _archive_like_the_command(holder, env.character) == "archived"
        holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
        request = run_in_thread(
            "assign",
            lambda: post(
                pooled2_factory, env.owner.user, assign_path(s, env.character), assign_body(env.p1)
            ),
        )
        wait_until_pid_blocks(s.w.engine, holder_pid)
        tx.commit()
    finally:
        holder.close()
    response = request.wait("the assign finishes")
    assert code(response) == 404, response.text
    assert state(s).rows == ()


def test_f26_an_archive_after_an_assign_is_refused_by_the_precondition(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    with s.w.engine.begin() as c:
        npc = make_character(c, s.w.world_id, name="C11 NPC", entity_type_code="npc")
    with StatementGate(pooled, AUDIT_INSERT) as gate:
        request = run_in_thread(
            "assign",
            lambda: post(pooled_factory, env.owner.user, assign_path(s, npc), assign_body(env.p1)),
        )
        gate.wait_reached()
        outcome: list[str] = []

        def archive() -> None:
            with s.w.engine.begin() as c:
                outcome.append(_archive_like_the_command(c, npc))

        thread = threading.Thread(target=archive)
        thread.start()
        wait_until_blocked(s.w.engine, gate, expected=1)
        gate.release()
        response = request.wait("the assign finishes")
        thread.join(timeout=30)
    assert code(response) == 201, response.text
    # the archive waited on the entity row the writer holds, then found the live assignment and refused
    assert outcome == ["blocked"]
    assert len([r for r in state(s).rows if not r[7]]) == 1


# --- F27: the deadlock matrix ---------------------------------------------------------------------------------------

REPETITIONS = 3
WRITERS = ("assign", "replace", "revoke")
COMPETITORS = (
    "legacy_grant",
    "legacy_revoke",
    "end_assignee",
    "revoke_gm_role",
    "archive",
    "recovery",
)


def _writer_call(s: Scene, e: Env, writer: str, factory: Factory, target: dict[str, Any]) -> Any:
    if writer == "assign":
        return post(
            factory, e.owner.user, assign_path(s, e.character), assign_body(e.p1, "co_controller")
        )
    if writer == "replace":
        return post(factory, e.owner.user, replace_path(s, e.character), replace_body(e.p2))
    return post(factory, e.owner.user, revoke_path(s, target["row"]), {"reason": "matrix"})


def _competitor_call(s: Scene, e: Env, name: str, factory: Factory, extra: dict[str, Any]) -> Any:
    if name == "legacy_grant":
        with factory(s.m.manager_user) as client:
            return client.post(
                f"{s.w.base}/memberships/{e.p1.membership}/character-relationships",
                json={"character_id": str(e.character), "relationship_type_code": "viewer"},
            )
    if name == "legacy_revoke":
        with factory(s.m.manager_user) as client:
            return client.post(
                f"{s.w.base}/character-relationships/{extra['legacy']}/revoke", json={}
            )
    if name == "end_assignee":
        return _end(factory, s, e.p1.membership)
    if name == "revoke_gm_role":
        return _revoke_role(factory, s, s.w.gm_role)
    if name == "archive":
        with s.w.engine.begin() as c:
            return _archive_like_the_command(c, e.character)
    from dnd_ai.commands.recovery import RecoveryNotNeededError, recover_campaign_access_manager

    with s.w.engine.begin() as c:
        try:
            recover_campaign_access_manager(
                c,
                admin_user_id=extra["admin"],
                campaign_id=s.w.campaign_id,
                new_user_id=e.p3.user,
                reason="matrix",
            )
        except RecoveryNotNeededError:
            return "not-needed"
        return "recovered"


def _reset_matrix_rows(s: Scene, env: Env) -> None:
    """What a winning competitor changed is put back, so the next repetition starts from the same shape."""
    with s.w.engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        c.execute(
            text(
                "UPDATE security.campaign_memberships SET ended_at = NULL WHERE campaign_membership_id = :m"
            ),
            {"m": env.p1.membership},
        )
        c.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = NULL WHERE membership_role_id = :r"
            ),
            {"r": s.w.gm_role},
        )
        c.execute(
            text(
                "UPDATE core.entities SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                "core.lifecycle_statuses WHERE code = 'active'), archived_at = NULL WHERE entity_id = :e"
            ),
            {"e": env.character},
        )
        c.execute(
            text(
                "UPDATE security.membership_character_relationships SET revoked_at = now() "
                "WHERE campaign_id = :c AND revoked_at IS NULL"
            ),
            {"c": s.w.campaign_id},
        )


def _together(writer: Any, competitor: Any) -> dict[str, Any]:
    """Runs both calls on two threads released by one barrier; each outcome (or exception) is returned by name."""
    barrier = threading.Barrier(2)
    results: dict[str, Any] = {}

    def run(name: str, call: Any) -> None:
        barrier.wait(timeout=10)
        try:
            results[name] = call()
        except BaseException as error:  # noqa: BLE001 - recorded, asserted by the caller
            results[name] = error

    threads = [
        threading.Thread(target=run, args=("writer", writer)),
        threading.Thread(target=run, args=("competitor", competitor)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


@pytest.mark.parametrize("competitor", COMPETITORS)
@pytest.mark.parametrize("writer", WRITERS)
def test_f27_no_writer_deadlocks_against_the_other_writers_of_its_rows(
    s: Scene,
    env: Env,
    pooled_factory: Factory,
    pooled2_factory: Factory,
    writer: str,
    competitor: str,
) -> None:
    """*matrix*: the writer and one competitor on the shared rows (the campaign, the assignee's membership, the
    character's anchor row, the caller's role rows), started together, repeated; no 40P01, no 5xx. A refusal or a
    no-op of either side is fine: the claim is the absence of a cycle."""
    admin = None
    if competitor == "recovery":
        with s.w.engine.begin() as c:
            admin = make_user(c, "C11 Admin")
            make_system_role_assignment(c, admin, "admin")
    before = wait_for_deadlock_count(s.w.engine, deadlock_count(s.w.engine))
    for repetition in range(REPETITIONS + 1):
        extra: dict[str, Any] = {"admin": admin}
        target: dict[str, Any] = {}
        control = repetition == 0
        with s.w.engine.begin() as c:
            if writer == "replace":
                c.execute(
                    text(
                        "UPDATE security.membership_character_relationships SET revoked_at = now() "
                        "WHERE is_control_assignment AND campaign_id = :c AND revoked_at IS NULL"
                    ),
                    {"c": s.w.campaign_id},
                )
                make_control_assignment(
                    c,
                    env.p3.membership,
                    env.character,
                    "primary_controller",
                    "ongoing",
                    campaign_id=s.w.campaign_id,
                )
            if writer == "revoke":
                target["row"] = make_control_assignment(
                    c,
                    env.p1.membership,
                    env.character,
                    "co_controller",
                    "ongoing",
                    campaign_id=s.w.campaign_id,
                )
            if competitor == "legacy_revoke":
                extra["legacy"] = make_membership_character_relationship(
                    c, env.p2.membership, env.character, relationship_type_id(c, "viewer")
                )
        if control:
            # the positive control: the writer alone, uncontended, succeeds (an absent route also answers 404)
            alone = _writer_call(s, env, writer, pooled_factory, target)
            assert alone.status_code in (200, 201), alone.text
            _reset_matrix_rows(s, env)
            continue
        results = _together(
            lambda target=target: _writer_call(s, env, writer, pooled_factory, target),
            lambda extra=extra: _competitor_call(s, env, competitor, pooled2_factory, extra),
        )
        for outcome in results.values():
            assert not isinstance(outcome, BaseException), outcome
            if hasattr(outcome, "status_code"):
                assert outcome.status_code < 500, outcome.text
        _reset_matrix_rows(s, env)
    assert wait_for_deadlock_count(s.w.engine, before) == before, "a deadlock was detected"
