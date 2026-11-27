# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""P15-C11-S02-T02: the concurrency evidence for the assign-control delegation routes (H17, H18, H19).

- **race** (H17, H18): one request parked at a named statement (its locks held, its writes uncommitted) and a competitor
  on the other side, every wait observed through `pg_blocking_pids`, never assumed. Both orders are shown.
- **matrix** (H19): each delegation writer against the T01 writers, membership end, role revoke and change,
  administrative recovery and the reveal-delegation writers, started together and repeated a bounded number of
  times, with the database's deadlock counter compared before and after.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from tests.database.test_assign_control_delegation import (  # noqa: F401 - fixtures used by name
    GRANT_COMMAND,
    Env,
    Factory,
    World,
    _tidy,
    _tidy_delegation_audit,
    assign_body,
    assign_path,
    assistant_row,
    audits,
    build_env,
    code,
    delegations,
    env,
    error_of,
    grant,
    live_assignments,
    pooled,
    pooled2,
    pooled2_factory,
    pooled_factory,
    revoke,
    s,
    seed_delegation,
    w,
)
from tests.database.test_assign_control_delegation import m as m  # noqa: F401
from tests.database.test_control_assignment_concurrency import (  # noqa: F401 - helpers used by name
    AUDIT_INSERT,
    REPETITIONS,
    _end,
    _revoke_role,
    _together,
)
from tests.database.test_r01_s5e2_membership_routes import Scene, waiting_statement
from tests.factories import make_system_role_assignment, make_user
from tests.http_race_support import (
    StatementGate,
    deadlock_count,
    run_in_thread,
    wait_for_deadlock_count,
    wait_until_blocked,
)
from tests.lock_race_support import LockRace

pytestmark = pytest.mark.database

REFUSAL = "character_assign_control_required"


def _delegated_assign(factory: Factory, sc: Scene, e: Env) -> Any:
    from tests.database.test_control_assignment_commands import post

    return post(factory, e.assistant.user, assign_path(sc, e.character), assign_body(e.p1))


# --- H17: a revoke against an in-flight delegated assign ------------------------------------------------------------


def test_h17_an_assign_in_flight_completes_and_a_revoke_waits_for_it(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory, pooled2_factory: Factory
) -> None:
    """*race*: the delegated assign holds the delegation row `FOR SHARE` (parked at its audit insert); the revoke queues
    on that row behind it. The assign completes and stays in history; the revoke then closes the delegation."""
    seed_delegation(s, env.assistant)
    with StatementGate(pooled, AUDIT_INSERT) as gate:
        assign = run_in_thread("assign", lambda: _delegated_assign(pooled_factory, s, env))
        gate.wait_reached()
        closing = run_in_thread(
            "revoke", lambda: revoke(pooled2_factory, s, env.owner.user, env.assistant)
        )
        wait_until_blocked(s.w.engine, gate, expected=1)
        gate.release()
        assigned, revoked = assign.wait("assign"), closing.wait("revoke")
    assert code(assigned) == 201, assigned.text
    assert code(revoked) == 200 and revoked.json()["revoked"] is True, revoked.text
    assert live_assignments(s) == 1  # what the holder made stays in force
    assert delegations(s)[0]["live"] is False


def test_h17_a_revoke_that_commits_first_makes_the_assign_a_403_after_its_wait(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory, pooled2_factory: Factory
) -> None:
    """*race*: the revoke holds the delegation row `FOR UPDATE` (parked at its audit insert); the assign queues on the
    delegation row, and after the revoke commits it is refused."""
    seed_delegation(s, env.assistant)
    with StatementGate(pooled, AUDIT_INSERT) as gate:
        closing = run_in_thread(
            "revoke", lambda: revoke(pooled_factory, s, env.owner.user, env.assistant)
        )
        gate.wait_reached()
        assign = run_in_thread("assign", lambda: _delegated_assign(pooled2_factory, s, env))
        wait_until_blocked(s.w.engine, gate, expected=1)
        gate.release()
        revoked, assigned = closing.wait("revoke"), assign.wait("assign")
    assert code(revoked) == 200, revoked.text
    assert code(assigned) == 403 and error_of(assigned) == REFUSAL, assigned.text
    assert live_assignments(s) == 0


# --- H18: a grant against the grantee's role revoke and membership end ---------------------------------------------


def _bound_row_was_live_at_insert(sc: Scene) -> bool:
    with sc.w.engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT d.granted_at, mr.revoked_at FROM security.character_assign_control_delegations d "
                "JOIN security.membership_roles mr "
                "ON mr.membership_role_id = d.assistant_gm_membership_role_id "
                "WHERE d.campaign_id = :c"
            ),
            {"c": sc.w.campaign_id},
        ).all()
    return all(revoked_at is None or granted_at <= revoked_at for granted_at, revoked_at in rows)


@pytest.mark.parametrize("competitor", ["revoke_role", "end_membership"])
def test_h18_a_grant_that_commits_first_binds_a_row_that_was_live(
    s: Scene,
    env: Env,
    pooled: Engine,
    pooled_factory: Factory,
    pooled2_factory: Factory,
    competitor: str,
) -> None:
    role = assistant_row(s, env.assistant)
    with StatementGate(pooled, AUDIT_INSERT) as gate:
        granting = run_in_thread(
            "grant", lambda: grant(pooled_factory, s, env.owner.user, env.assistant)
        )
        gate.wait_reached()
        other = run_in_thread(
            "competitor",
            lambda: (
                _revoke_role(pooled2_factory, s, role)
                if competitor == "revoke_role"
                else _end(pooled2_factory, s, env.assistant.membership)
            ),
        )
        wait_until_blocked(s.w.engine, gate, expected=1)
        gate.release()
        granted, finished = granting.wait("grant"), other.wait("competitor")
    assert code(granted) == 201, granted.text
    assert code(finished) == 200, finished.text
    assert len(delegations(s)) == 1 and _bound_row_was_live_at_insert(s)


@pytest.mark.parametrize("competitor", ["revoke_role", "end_membership"])
def test_h18_a_role_revoke_or_end_that_commits_first_leaves_no_delegation(
    s: Scene,
    env: Env,
    pooled: Engine,
    pooled_factory: Factory,
    pooled2_factory: Factory,
    competitor: str,
) -> None:
    role = assistant_row(s, env.assistant)
    with StatementGate(pooled, AUDIT_INSERT) as gate:
        other = run_in_thread(
            "competitor",
            lambda: (
                _revoke_role(pooled_factory, s, role)
                if competitor == "revoke_role"
                else _end(pooled_factory, s, env.assistant.membership)
            ),
        )
        gate.wait_reached()
        granting = run_in_thread(
            "grant", lambda: grant(pooled2_factory, s, env.owner.user, env.assistant)
        )
        wait_until_blocked(s.w.engine, gate, expected=1)
        gate.release()
        finished, granted = other.wait("competitor"), granting.wait("grant")
    assert code(finished) == 200, finished.text
    assert code(granted) == 409, granted.text
    assert error_of(granted) == "assign_control_recipient_not_assistant_gm"
    assert delegations(s) == [] and audits(s) == {}


# --- H19: the deadlock matrix ----------------------------------------------------------------------------------------

WRITERS = ("grant", "revoke")
COMPETITORS = (
    "t01_assign_owner",
    "t01_assign_delegated",
    "end_grantee",
    "revoke_assistant_role",
    "change_assistant_role",
    "recovery",
    "reveal_grant",
    "reveal_revoke",
)


def _writer_call(s: Scene, e: Env, writer: str, factory: Factory) -> Any:
    if writer == "grant":
        return grant(factory, s, e.owner.user, e.assistant)
    return revoke(factory, s, e.owner.user, e.assistant)


def _competitor_call(s: Scene, e: Env, name: str, factory: Factory, extra: dict[str, Any]) -> Any:
    from tests.database.test_control_assignment_commands import post

    if name == "t01_assign_owner":
        return post(factory, e.owner.user, assign_path(s, e.character), assign_body(e.p1))
    if name == "t01_assign_delegated":
        return _delegated_assign(factory, s, e)
    if name == "end_grantee":
        return _end(factory, s, e.assistant.membership)
    if name == "revoke_assistant_role":
        return _revoke_role(factory, s, extra["assistant_role"])
    if name == "change_assistant_role":
        with factory(s.m.manager_user) as client:
            return client.post(
                f"{s.w.base}/memberships/roles/{extra['assistant_role']}/change",
                json={"new_role_id": str(s.observer)},
            )
    if name == "reveal_grant":
        with factory(e.owner.user) as client:
            return client.post(
                f"{s.w.base}/reveal-delegations",
                json={
                    "grantee_campaign_membership_id": str(s.w.gm_membership),
                    "reason": "matrix",
                },
            )
    if name == "reveal_revoke":
        with factory(e.owner.user) as client:
            return client.post(
                f"{s.w.base}/reveal-delegations/{s.w.gm_membership}/revoke",
                json={"reason": "matrix"},
            )
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


def _reset(s: Scene, e: Env, original_role: uuid.UUID) -> None:
    """What a winning competitor changed is put back, so the next repetition starts from the same shape."""
    with s.w.engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        c.execute(
            text(
                "UPDATE security.campaign_memberships SET ended_at = NULL WHERE campaign_membership_id = :m"
            ),
            {"m": e.assistant.membership},
        )
        c.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = NULL WHERE membership_role_id = :r"
            ),
            {"r": original_role},
        )
        c.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() "
                "WHERE campaign_membership_id = :m AND membership_role_id <> :r AND revoked_at IS NULL"
            ),
            {"m": e.assistant.membership, "r": original_role},
        )
        c.execute(
            text(
                "UPDATE security.character_assign_control_delegations SET revoked_at = now(), "
                "end_reason = 'assistant_gm_assignment_lapsed' WHERE campaign_id = :c AND revoked_at IS NULL"
            ),
            {"c": s.w.campaign_id},
        )
        c.execute(
            text(
                "UPDATE security.character_reveal_delegations SET revoked_at = now(), "
                "end_reason = 'gm_assignment_lapsed' WHERE campaign_id = :c AND revoked_at IS NULL"
            ),
            {"c": s.w.campaign_id},
        )
        c.execute(
            text(
                "UPDATE security.membership_character_relationships SET revoked_at = now() "
                "WHERE campaign_id = :c AND revoked_at IS NULL"
            ),
            {"c": s.w.campaign_id},
        )


@pytest.mark.parametrize("competitor", COMPETITORS)
@pytest.mark.parametrize("writer", WRITERS)
def test_h19_no_delegation_writer_deadlocks_against_the_writers_of_its_rows(
    s: Scene,
    env: Env,
    pooled_factory: Factory,
    pooled2_factory: Factory,
    writer: str,
    competitor: str,
) -> None:
    """*matrix*: the delegation writer and one competitor on the shared rows (the caller's and the grantee's role rows,
    the delegation rows, the memberships, the campaign), started together, repeated; no 40P01, no 5xx. A refusal or a
    no-op of either side is fine: the claim is the absence of a cycle."""
    original_role = assistant_row(s, env.assistant)
    extra: dict[str, Any] = {"assistant_role": original_role, "admin": None}
    if competitor == "recovery":
        with s.w.engine.begin() as c:
            extra["admin"] = make_user(c, "H19 Admin")
            make_system_role_assignment(c, extra["admin"], "admin")
    before = wait_for_deadlock_count(s.w.engine, deadlock_count(s.w.engine))
    for repetition in range(REPETITIONS + 1):
        if writer == "revoke" or competitor == "t01_assign_delegated":
            seed_delegation(s, env.assistant)
        if repetition == 0:
            # the positive control: the writer alone, uncontended, succeeds (an absent route also answers 404)
            alone = _writer_call(s, env, writer, pooled_factory)
            assert alone.status_code in (200, 201), alone.text
            _reset(s, env, original_role)
            continue
        results = _together(
            lambda: _writer_call(s, env, writer, pooled_factory),
            lambda: _competitor_call(s, env, competitor, pooled2_factory, extra),
        )
        for outcome in results.values():
            assert not isinstance(outcome, BaseException), outcome
            if hasattr(outcome, "status_code"):
                assert outcome.status_code < 500, outcome.text
        _reset(s, env, original_role)
    assert wait_for_deadlock_count(s.w.engine, before) == before, "a deadlock was detected"
    assert GRANT_COMMAND  # the audit vocabulary this matrix exercises


# --- the unique-index waits of the delegation steps ---------------------------------------------------------------

_INSERT_DELEGATION = (
    "INSERT INTO security.character_assign_control_delegations (campaign_id, grantee_campaign_membership_id, "
    "assistant_gm_membership_role_id, granted_by_membership_id, reason) VALUES (:c, :g, :r, :a, 'x')"
)


def test_a_competing_delegation_for_the_same_grantee_is_a_unique_wait(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, `ux_character_assign_control_delegations_live` on the INSERT: a competing delegation for the same
    grantee, inserted while the grant is parked at its audit insert (its row inserted, uncommitted), queues behind *the
    request* (observed through `pg_blocking_pids`, the waiting statement is the competitor's INSERT) and, when the
    request commits, fails on the unique index: one live delegation remains. Whether the competitor waits at its
    foreign key on the grantee's `assistant_gm` row (which the grant holds `FOR UPDATE`) or at the index key is not
    distinguishable from outside, and is not claimed: either way it can never produce a second live row."""
    role = assistant_row(s, env.assistant)
    with StatementGate(pooled, AUDIT_INSERT) as gate:
        request = run_in_thread(
            "grant", lambda: grant(pooled_factory, s, env.owner.user, env.assistant)
        )
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            queued = race.start(
                "insert",
                lambda c: c.execute(
                    text(_INSERT_DELEGATION),
                    {
                        "c": s.w.campaign_id,
                        "g": env.assistant.membership,
                        "r": role,
                        "a": env.owner.membership,
                    },
                ),
            )
            race.wait_blocked_by(gate, expected=1)
            assert "character_assign_control_delegations" in waiting_statement(s.w.engine, gate.pid)
            gate.release()
            response = request.wait("the grant finishes")
            race.join_all()
    assert code(response) == 201, response.text
    assert isinstance(queued.error, IntegrityError), queued.error
    assert [row["live"] for row in delegations(s)] == [True]


def test_a_delegation_closure_leaving_the_live_index_never_waits_for_a_competing_insert(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, `ux_character_assign_control_delegations_live`: closing the delegation leaves the partial index. A
    competitor inserting a live delegation for the same grantee queues behind the request at its audit insert (the
    closure done, uncommitted) and completes after it commits."""
    seed_delegation(s, env.assistant)
    role = assistant_row(s, env.assistant)
    with StatementGate(pooled, AUDIT_INSERT) as gate:
        request = run_in_thread(
            "revoke", lambda: revoke(pooled_factory, s, env.owner.user, env.assistant)
        )
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            competitor = race.start(
                "insert",
                lambda c: c.execute(
                    text(_INSERT_DELEGATION),
                    {
                        "c": s.w.campaign_id,
                        "g": env.assistant.membership,
                        "r": role,
                        "a": env.owner.membership,
                    },
                ),
            )
            race.wait_blocked_by(gate, expected=1)
            assert "character_assign_control_delegations" in waiting_statement(s.w.engine, gate.pid)
            gate.release()
            response = request.wait("the revoke finishes while the competitor is queued")
            race.join_all()
    assert code(response) == 200 and competitor.error is None
