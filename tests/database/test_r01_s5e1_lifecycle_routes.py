# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E1: campaign update, archive and reactivate as keyed-optional pre-write plans, over real HTTP.

`POST /campaigns/{id}/update`, `/archive` and `/reactivate` (`dnd_ai.commands.campaign_lifecycle_plans`)
take the actor's role rows, membership and account `FOR SHARE`, then the campaign `FOR UPDATE` (the world
and the timeline `FOR SHARE` first, for reactivate), judge authority at `plan.finalize` against the state
**before** the command, and only then write through declared steps. Archive changes the lifecycle that the
route requirement reads, which is why `finalize` runs before its `UPDATE`.

Evidence classes (labelled in each docstring):

- **route**: a real HTTP request through the guard on a one-connection pool.
- **sql**: the recorded statement stream of such a request (`Recorder`).
- **race**: a route request on one side and a competitor on the other, each parked on a named statement;
  every wait is observed through `pg_blocking_pids` (and its blocking pid and waiting statement checked),
  never assumed.
- **mutation (test-side)**: `AuthorizationPlan.execute` or a handler step is wrapped to omit, repeat or add
  a write, to show that the declared obligations refuse it. Nothing production-side is changed.
"""

import dataclasses
import re
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.domain.authorization import AuthorizationPlan, StepOutcome
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    FINAL,
    FINAL_RE,
    Recorder,
    idle_in_transaction,
    pooled,
    pooled_factory,
)
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixtures used by name
    World,
    code,
    error_of,
    w,
)
from tests.http_race_support import (
    StatementGate,
    deadlock_count,
    new_key,
    run_in_thread,
    wait_for_deadlock_count,
)
from tests.lock_race_support import LockRace
from tests.r01_s5d_support import (
    Managers,
    make_managers,
    revoke_role,
    run_with_role_lapsing_before_final,
)

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]
ROUTES = ("update", "archive", "reactivate")
ALL_ROUTES = pytest.mark.parametrize("route", ROUTES)
KEYED = pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))

KEY_LOCK = r"pg_advisory_xact_lock"
ROLES_S = r"FROM security\.membership_roles WHERE .* FOR SHARE$"
MEMBERSHIP_S = r"FROM security\.campaign_memberships WHERE .* FOR SHARE$"
ACCOUNT_S = r"FROM security\.users WHERE .* FOR SHARE$"
WORLD_S = r"FROM core\.worlds WHERE .* FOR SHARE$"
TIMELINE_S = r"FROM campaign\.timelines WHERE .* FOR SHARE$"
CAMPAIGN_U = r"FROM campaign\.campaigns WHERE campaign\.campaigns\.campaign_id = %\(campaign\)s::UUID FOR UPDATE$"
CHANGED_U = r"FROM campaign\.campaigns WHERE .* IS DISTINCT FROM .* FOR UPDATE$"
RECEIPT_U = r"FROM security\.idempotent_requests WHERE .*idempotent_request_id = %\(receipt\)s::UUID FOR UPDATE"
UPDATE_CAMPAIGN = r"^UPDATE campaign\.campaigns SET"
AUDIT_INSERT = r"^INSERT INTO audit\.change_log"
RECEIPT_UPDATE = r"^UPDATE security\.idempotent_requests"
FIRST_LOCK = {"update": ROLES_S, "archive": ROLES_S, "reactivate": WORLD_S}
STEP = {
    "update": "update_campaign",
    "archive": "archive_campaign",
    "reactivate": "reactivate_campaign",
}
AUDIT_STEP = {
    "update": "audit_updated",
    "archive": "audit_archived",
    "reactivate": "audit_restored",
}
COMMAND = {
    "update": "update_campaign",
    "archive": "archive_campaign",
    "reactivate": "reactivate_campaign",
}


@pytest.fixture
def m(w: World) -> Managers:
    return make_managers(w.engine, w.campaign_id, label="S5E1 Lifecycle")


@pytest.fixture(autouse=True)
def _tidy(w: World) -> Any:
    yield
    with w.engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM audit.change_log WHERE world_id = :w AND table_name = 'campaigns'"),
            {"w": w.world_id},
        )


# --- helpers ------------------------------------------------------------------------------------------------------


def state(w: World) -> tuple[Any, ...]:
    """(name, description, lifecycle code, row_version) of the campaign."""
    with w.engine.connect() as c:
        row = c.execute(
            text(
                "SELECT c.name, c.description, ls.code, c.row_version FROM campaign.campaigns c "
                "JOIN core.lifecycle_statuses ls USING (lifecycle_status_id) WHERE c.campaign_id = :c"
            ),
            {"c": w.campaign_id},
        ).one()
    return tuple(row)


def set_campaign_status(w: World, code_: str) -> None:
    with w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE campaign.campaigns SET lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = :s) "
                "WHERE campaign_id = :c"
            ),
            {"s": code_, "c": w.campaign_id},
        )


def audit_rows(w: World, command: str | None = None) -> list[tuple[Any, ...]]:
    with w.engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT command_name, previous_status, new_status, reason, changed_fields, actor_user_id, "
                "record_id, world_id FROM audit.change_log WHERE world_id = :w AND table_name = 'campaigns' "
                "AND (CAST(:k AS text) IS NULL OR command_name = :k) ORDER BY change_log_id"
            ),
            {"w": w.world_id, "k": command},
        ).all()
    return [tuple(r) for r in rows]


def receipt(w: World, key: str) -> tuple[Any, ...]:
    with w.engine.connect() as c:
        row = c.execute(
            text(
                "SELECT response_status_code, response_body, completed_at IS NOT NULL "
                "FROM security.idempotent_requests WHERE campaign_id = :c AND idempotency_key = :k"
            ),
            {"c": w.campaign_id, "k": key},
        ).one_or_none()
    return tuple(row) if row is not None else ()


def snapshot(w: World, key: str | None = None) -> tuple[Any, ...]:
    """Everything any of the routes can persist: the campaign row, the audit rows, the key's receipt."""
    return (state(w), audit_rows(w), receipt(w, key) if key else ())


def body_for(
    w: World,
    route: str,
    *,
    name: str = "Renamed",
    description: str | None = "d",
    reason: str | None = None,
) -> dict[str, Any]:
    version = state(w)[3]
    if route == "update":
        return {"expected_row_version": version, "name": name, "description": description}
    if route == "archive":
        return {"expected_row_version": version, "reason": reason}
    return {"expected_row_version": version}


def call(
    factory: Factory,
    w: World,
    user: uuid.UUID,
    route: str,
    body: dict[str, Any],
    *,
    key: str | None,
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    with factory(user) as client:
        return client.post(f"{w.base}/{route}", json=body, headers=headers)


def prepare_state(w: World, route: str) -> None:
    if route == "reactivate":
        set_campaign_status(w, "archived")


def index(events: list[str], pattern: str, start: int = 0) -> int:
    matches = [i for i, s in enumerate(events) if i >= start and re.search(pattern, s)]
    assert matches, f"no statement matches {pattern!r}: {events}"
    return matches[0]


def waiting_statement(engine: Engine, holder_pid: int) -> str:
    import time

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        r"SELECT regexp_replace(query, '\s+', ' ', 'g') FROM pg_stat_activity "
                        "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                        "AND :p = ANY(pg_blocking_pids(pid))"
                    ),
                    {"p": holder_pid},
                )
                .scalars()
                .all()
            )
        if rows:
            return str(rows[0])
        time.sleep(0.02)
    raise AssertionError(f"nothing waits on pid {holder_pid}")


# --- success and legitimate no-op ---------------------------------------------------------------------------------


@ALL_ROUTES
@KEYED
def test_a_manager_runs_each_route_with_its_audit_row_and_receipt(
    route: str, keyed: bool, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: 200 with the new version (and the status for archive and reactivate); one campaign update,
    one audit row naming the command and the transition; a receipt only for a keyed request, whose stored
    body is the response and carries neither the archive reason nor the description."""
    prepare_state(w, route)
    before = state(w)
    key = new_key() if keyed else None
    body = body_for(w, route, reason="  a private reason  ", description="a private description")
    response = call(pooled_factory, w, m.manager_user, route, body, key=key)
    assert code(response) == 200, response.text
    after = state(w)
    assert after[3] == before[3] + 1 and response.json()["row_version"] == after[3]
    assert response.json()["campaign_id"] == str(w.campaign_id)
    if route == "update":
        assert (
            after[:2] == ("Renamed", "a private description")
            and "lifecycle_status" not in response.json()
        )
    else:
        assert after[2] == ("archived" if route == "archive" else "active")
        assert response.json()["lifecycle_status"] == after[2]
    rows = audit_rows(w)
    assert len(rows) == 1 and rows[0][0] == COMMAND[route] and rows[0][5] == m.manager_user
    assert rows[0][6] == w.campaign_id and rows[0][7] == w.world_id
    if route == "archive":
        assert rows[0][1:4] == ("active", "archived", "a private reason")
    elif route == "reactivate":
        assert rows[0][1:4] == ("archived", "active", None)
    else:
        assert rows[0][1:3] == (None, None) and rows[0][4]["name"] == {
            "from": before[0],
            "to": "Renamed",
        }
    if keyed:
        stored = receipt(w, key or "")
        assert stored == (200, response.json(), True)
        assert "private" not in str(stored[1])
    assert idle_in_transaction(w.engine) == 0


@KEYED
def test_an_update_that_changes_nothing_writes_nothing_and_a_keyed_one_completes_its_receipt(
    keyed: bool, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: the legitimate no-op. No campaign update, no version bump, no audit row, and a
    fresh keyed no-op still completes its receipt (`Exactly(1)`); the same key then replays it."""
    before = state(w)
    key = new_key() if keyed else None
    body = {"expected_row_version": before[3], "name": before[0], "description": before[1]}
    with Recorder(pooled) as recorded:
        response = call(pooled_factory, w, m.manager_user, "update", body, key=key)
    assert code(response) == 200 and response.json()["row_version"] == before[3]
    assert state(w) == before and audit_rows(w) == []
    assert not [s for s in recorded.events if re.search(UPDATE_CAMPAIGN + "|" + AUDIT_INSERT, s)]
    receipts = [s for s in recorded.events if re.search(RECEIPT_UPDATE, s)]
    assert len(receipts) == (1 if keyed else 0)
    changed_lock = [s for s in recorded.events if re.search(CHANGED_U, s)]
    assert len(changed_lock) == 1, "the changed-row evidence is taken once, and returns no row"
    if keyed:
        assert receipt(w, key or "") == (200, response.json(), True)
        again = call(pooled_factory, w, m.manager_user, "update", body, key=key)
        assert code(again) == 200 and again.json() == response.json()
        assert audit_rows(w) == []


def test_a_genuine_update_runs_exactly_one_update_and_one_audit_insert(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    with Recorder(pooled) as recorded:
        response = call(
            pooled_factory, w, m.manager_user, "update", body_for(w, "update"), key=new_key()
        )
    assert code(response) == 200
    assert len([s for s in recorded.events if re.search(UPDATE_CAMPAIGN, s)]) == 1
    assert len([s for s in recorded.events if re.search(AUDIT_INSERT, s)]) == 1


@KEYED
def test_the_archive_and_reactivate_transitions_round_trip_with_versions_and_two_audit_rows(
    keyed: bool, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: archive then reactivate over HTTP. The archived campaign stops authorizing the ordinary
    routes (404, the route requirement) but not reactivation; versions step by one each time."""
    start = state(w)
    keys = [new_key() if keyed else None for _ in range(3)]
    archived = call(
        pooled_factory, w, m.manager_user, "archive", body_for(w, "archive"), key=keys[0]
    )
    assert code(archived) == 200 and archived.json()["lifecycle_status"] == "archived"
    blocked = call(pooled_factory, w, m.manager_user, "update", body_for(w, "update"), key=keys[1])
    assert code(blocked) == 404
    restored = call(
        pooled_factory, w, m.manager_user, "reactivate", body_for(w, "reactivate"), key=keys[2]
    )
    assert code(restored) == 200 and restored.json()["lifecycle_status"] == "active"
    assert state(w)[2:] == ("active", start[3] + 2)
    assert [r[0] for r in audit_rows(w)] == ["archive_campaign", "reactivate_campaign"]


# --- refusals keep their errors and write nothing -------------------------------------------------------------------


@KEYED
def test_refusals_keep_their_errors_and_persist_nothing_and_the_key_is_reusable(
    keyed: bool, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: a stale version (409 `stale_write`), reactivating an active campaign (409
    `lifecycle_transition_not_allowed`), a reactivation under an archived world or timeline (409), archiving
    an archived campaign (404: the route requires an active one), an invalid name (422). None persists a
    row, consumes a key or leaves a connection in a transaction."""
    version = state(w)[3]
    key = new_key() if keyed else None
    cases: list[tuple[str, dict[str, Any], int, str | None]] = [
        ("archive", {"expected_row_version": version + 9, "reason": None}, 409, "stale_write"),
        ("reactivate", {"expected_row_version": version}, 409, "lifecycle_transition_not_allowed"),
        ("update", {"expected_row_version": version, "name": "  ", "description": None}, 422, None),
    ]
    before = snapshot(w, key)
    for route, body, status, error in cases:
        response = call(pooled_factory, w, m.manager_user, route, body, key=key)
        assert code(response) == status, (route, response.text)
        if error:
            assert error_of(response) == error
        assert snapshot(w, key) == before
    # an archived campaign: the ordinary routes are a 404 (the route requirement), reactivation is judged
    # against the world and the timeline, whose lifecycle is read under their share locks
    set_campaign_status(w, "archived")
    version = state(w)[3]
    assert (
        code(
            call(
                pooled_factory,
                w,
                m.manager_user,
                "archive",
                {"expected_row_version": version},
                key=key,
            )
        )
        == 404
    )
    for table, column, label in (("core.worlds", "world_id", "world_archived"),):
        with w.engine.begin() as c:
            c.execute(
                text(
                    f"UPDATE {table} SET lifecycle_status_id = "
                    "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
                    f"WHERE {column} = :id"
                ),
                {"id": w.world_id},
            )
        blocked = call(
            pooled_factory,
            w,
            m.manager_user,
            "reactivate",
            {"expected_row_version": version},
            key=key,
        )
        assert code(blocked) == 409 and error_of(blocked) == label
        assert state(w)[2] == "archived" and audit_rows(w) == []
        if key:
            assert receipt(w, key) == ()
    assert idle_in_transaction(w.engine) == 0


def test_a_reactivation_blocked_by_an_archived_timeline_and_the_unchanged_world_policy(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: world and timeline lifecycle checks keep their approved policy. An archived timeline blocks
    reactivation (409 `timeline_archived`), but update and archive of an *active* campaign do not consult
    the world or the timeline at all (they never did); nothing is broadened."""
    with w.engine.begin() as c:
        timeline = c.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": w.campaign_id},
        ).scalar_one()
        c.execute(
            text(
                "UPDATE campaign.timelines SET lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
                "WHERE timeline_id = :t"
            ),
            {"t": timeline},
        )
    updated = call(
        pooled_factory, w, m.manager_user, "update", body_for(w, "update"), key=new_key()
    )
    assert code(updated) == 200
    archived = call(
        pooled_factory, w, m.manager_user, "archive", body_for(w, "archive"), key=new_key()
    )
    assert code(archived) == 200
    blocked = call(
        pooled_factory, w, m.manager_user, "reactivate", body_for(w, "reactivate"), key=None
    )
    assert code(blocked) == 409 and error_of(blocked) == "timeline_archived"
    assert state(w)[2] == "archived"


def test_a_reactivation_without_a_surviving_access_manager_is_the_classified_409(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the retention pre-check runs before `finalize`, under the held campaign lock. A campaign
    whose every manager's role is expiring is refused with the classified 409, not by the COMMIT-time
    trigger, and nothing persists."""
    set_campaign_status(w, "archived")
    with w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = now() + interval '1 day' "
                "WHERE campaign_membership_id IN (SELECT campaign_membership_id FROM "
                "security.campaign_memberships WHERE campaign_id = :c)"
            ),
            {"c": w.campaign_id},
        )
    before = snapshot(w)
    response = call(
        pooled_factory, w, m.manager_user, "reactivate", body_for(w, "reactivate"), key=None
    )
    assert code(response) == 409 and error_of(response) == "campaign_access_manager_required"
    assert snapshot(w) == before


# --- replay -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("route", ("update", "reactivate"))
def test_an_authorized_replay_returns_the_stored_receipt_without_a_lock_or_a_write(
    route: str, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: the replay returns the stored body, takes no row lock, writes nothing, and its
    last statement before COMMIT is the one final authority statement (the receipt does not leave before
    the check). The replay does not re-run the command's preconditions."""
    prepare_state(w, route)
    key = new_key()
    body = body_for(w, route)
    first = call(pooled_factory, w, m.manager_user, route, body, key=key)
    assert code(first) == 200
    stored = snapshot(w, key)
    with Recorder(pooled) as recorded:
        replay = call(pooled_factory, w, m.manager_user, route, body, key=key)
    assert code(replay) == 200 and replay.json() == first.json()
    assert snapshot(w, key) == stored
    finals = [s for s in recorded.events if FINAL_RE.search(s)]
    assert len(finals) == 1 and recorded.events[-2:] == [finals[0], "COMMIT"]
    assert not [
        s for s in recorded.events if re.search(r"FOR (KEY SHARE|SHARE|UPDATE|NO KEY UPDATE)", s)
    ]
    writes = [s for s in recorded.events if s.startswith(("INSERT", "UPDATE", "DELETE"))]
    assert all("idempotent_requests" in s and "ON CONFLICT" in s for s in writes), writes


def test_replaying_an_archive_is_judged_by_the_route_requirement_not_the_command(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the archive route requires an *active* campaign, so after the archive committed the same
    key reaches the route requirement first and gets its 404, and the stored receipt is not returned. This
    is the policy the route had; it is not changed, and no command precondition is re-run."""
    key = new_key()
    body = body_for(w, "archive")
    assert code(call(pooled_factory, w, m.manager_user, "archive", body, key=key)) == 200
    stored = snapshot(w, key)
    again = call(pooled_factory, w, m.manager_user, "archive", body, key=key)
    assert code(again) == 404 and "row_version" not in again.text
    assert snapshot(w, key) == stored


@ALL_ROUTES
def test_a_replay_after_authority_loss_is_refused_and_returns_nothing_from_the_receipt(
    route: str, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    prepare_state(w, route)
    key = new_key()
    first = call(pooled_factory, w, m.manager_user, route, body_for(w, route), key=key)
    assert code(first) == 200
    stored = snapshot(w, key)
    revoke_role(w.engine, m.manager_role)
    if route == "archive":
        set_campaign_status(w, "active")  # an archived campaign would be a 404 for any caller
        stored = snapshot(w, key)
    again = call(pooled_factory, w, m.manager_user, route, body_for(w, route), key=key)
    assert code(again) in (403, 404), again.text
    assert "row_version" not in again.text and "campaign_id" not in again.text
    assert snapshot(w, key) == stored
    assert idle_in_transaction(w.engine) == 0


def test_a_replay_whose_authority_lapses_during_its_key_lock_wait_is_refused_at_the_final_statement(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    key = new_key()
    body = body_for(w, "update")
    assert code(call(pooled_factory, w, m.manager_user, "update", body, key=key)) == 200
    stored = snapshot(w, key)
    response = run_with_role_lapsing_before_final(
        w.engine,
        pooled,
        m.manager_role,
        lambda: call(pooled_factory, w, m.manager_user, "update", body, key=key),
        first_gate=KEY_LOCK,
    )
    assert code(response) in (403, 404) and "row_version" not in response.text
    assert snapshot(w, key) == stored


@ALL_ROUTES
def test_a_reused_key_with_another_payload_is_the_same_conflict_and_changes_nothing(
    route: str, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    prepare_state(w, route)
    key = new_key()
    body = body_for(w, route, name="One")
    assert code(call(pooled_factory, w, m.manager_user, route, body, key=key)) == 200
    stored = snapshot(w, key)
    other = dict(body, expected_row_version=body["expected_row_version"] + 1)
    if route == "update":
        other["name"] = "Two"
    elif route == "archive":
        other["reason"] = "a different reason"
    else:
        other["expected_row_version"] = body["expected_row_version"] + 5
    response = call(pooled_factory, w, m.manager_user, route, other, key=key)
    assert code(response) in (404, 409), response.text
    assert snapshot(w, key) == stored


# --- authority at the pre-write boundary ------------------------------------------------------------------------------


@ALL_ROUTES
@KEYED
def test_a_role_that_lapses_before_the_final_statement_refuses_the_route_and_rolls_everything_back(
    route: str, keyed: bool, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* (race): the manager's role is valid for every early check and has lapsed (a DATABASE
    condition, polled) when the final authority statement runs. Every lock is already held, so this is the
    pre-write refusal the plan promises: no campaign change, no audit row, no receipt, the connection
    returns clean and the key is reusable."""
    prepare_state(w, route)
    key = new_key() if keyed else None
    before = snapshot(w, key)
    body = body_for(w, route)
    response = run_with_role_lapsing_before_final(
        w.engine,
        pooled,
        m.manager_role,
        lambda: call(pooled_factory, w, m.manager_user, route, body, key=key),
        first_gate=KEY_LOCK if keyed else FIRST_LOCK[route],
    )
    assert code(response) in (403, 404), (route, keyed, response.text)
    assert snapshot(w, key) == before
    assert idle_in_transaction(w.engine) == 0
    with w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = NULL WHERE membership_role_id = :r"
            ),
            {"r": m.manager_role},
        )
    again = call(pooled_factory, w, m.manager_user, route, body, key=key)
    assert code(again) == 200, again.text
    assert idle_in_transaction(w.engine) == 0


@ALL_ROUTES
def test_a_role_revoked_before_the_request_is_refused_early_and_writes_nothing(
    route: str, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    prepare_state(w, route)
    revoke_role(w.engine, m.manager_role)
    key = new_key()
    before = snapshot(w, key)
    response = call(pooled_factory, w, m.manager_user, route, body_for(w, route), key=key)
    assert code(response) in (403, 404), response.text
    assert snapshot(w, key) == before
    assert idle_in_transaction(w.engine) == 0


def _revoke_manager_role(w: World, m: Managers) -> Callable[[Any], Any]:
    return lambda c: c.execute(
        text(
            "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
        ),
        {"r": m.manager_role},
    )


@ALL_ROUTES
def test_a_role_revocation_in_flight_makes_the_request_wait_then_refuses_it_without_a_deadlock(
    route: str, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, ordering 1 (the authority change holds first): a revocation has updated the manager's role
    row and has not committed. The request passes its early check, then queues at its first lock on the actor's
    role rows (`FOR SHARE`, blocked by the revoker's pid) holding nothing the revoker wants. The revoker
    commits (its retention trigger gets the campaign, which the request does not yet hold); the request's
    lock then finds no unrevoked role and `finalize` refuses it. Nothing persists; no deadlock."""
    prepare_state(w, route)
    key = new_key()
    before = snapshot(w, key)
    deadlocks = deadlock_count(w.engine)
    with LockRace(w.engine) as race:
        hold = race.hold(_revoke_manager_role(w, m))
        request = run_in_thread(
            route,
            lambda: call(pooled_factory, w, m.manager_user, route, body_for(w, route), key=key),
        )
        race.wait_blocked_by(hold, expected=1)
        assert re.search(ROLES_S, waiting_statement(w.engine, hold.pid))
        assert not request.finished()
        hold.commit()
        response = request.wait("the request finishes after the revocation commits")
        race.join_all()
    assert code(response) in (403, 404), response.text
    assert snapshot(w, key) == before
    assert wait_for_deadlock_count(w.engine, deadlocks) == deadlocks
    assert idle_in_transaction(w.engine) == 0


@ALL_ROUTES
def test_a_request_holding_the_actors_rows_makes_a_role_revocation_wait_and_both_commit(
    route: str, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, ordering 2 (the request holds first): parked at its final statement the request holds the
    actor's role rows `FOR SHARE`. A revocation of the role queues at that row (blocked by the request's pid,
    waiting on its `UPDATE`), the request commits, then the revocation commits. Authority was judged before
    the change, as the review requires for a change that is requested after the lock phase."""
    prepare_state(w, route)
    key = new_key()
    deadlocks = deadlock_count(w.engine)
    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread(
            route,
            lambda: call(pooled_factory, w, m.manager_user, route, body_for(w, route), key=key),
        )
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(w.engine) as race:
            revoker = race.start("revoke", _revoke_manager_role(w, m))
            race.wait_blocked_by(gate, expected=1)
            assert "membership_roles" in waiting_statement(w.engine, gate.pid)
            assert not revoker.done
            gate.release()
            response = request.wait("the request finishes")
            race.join_all()
    assert code(response) == 200, response.text
    assert revoker.error is None
    with w.engine.connect() as c:
        revoked = c.execute(
            text(
                "SELECT revoked_at IS NOT NULL FROM security.membership_roles WHERE membership_role_id = :r"
            ),
            {"r": m.manager_role},
        ).scalar_one()
    assert revoked and len(audit_rows(w)) == 1
    assert wait_for_deadlock_count(w.engine, deadlocks) == deadlocks


# --- ordering ------------------------------------------------------------------------------------------------------


@ALL_ROUTES
def test_the_keyed_route_runs_its_statements_in_the_documented_order(
    route: str, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*sql*: key lock, deferral, reservation, [world, timeline `FOR SHARE`,] the actor's role rows,
    membership and account `FOR SHARE`, the campaign `FOR UPDATE`, [the changed-row lock,] our reservation
    row, the one final authority statement, and only after it the campaign update, the audit insert and the
    receipt update, COMMIT last, no row lock after the final statement."""
    prepare_state(w, route)
    with Recorder(pooled) as recorded:
        response = call(pooled_factory, w, m.manager_user, route, body_for(w, route), key=new_key())
    assert code(response) == 200
    e = recorded.events
    chain = [
        index(e, KEY_LOCK),
        index(e, r"SET CONSTRAINTS security\.idempotent_requests_campaign_id_fkey DEFERRED"),
        index(e, r"^INSERT INTO security\.idempotent_requests"),
    ]
    if route == "reactivate":
        chain += [index(e, WORLD_S), index(e, TIMELINE_S)]
    chain += [index(e, ROLES_S), index(e, MEMBERSHIP_S), index(e, ACCOUNT_S), index(e, CAMPAIGN_U)]
    if route == "update":
        chain.append(index(e, CHANGED_U))
    chain += [
        index(e, RECEIPT_U),
        index(e, FINAL),
        index(e, UPDATE_CAMPAIGN),
        index(e, AUDIT_INSERT),
        index(e, RECEIPT_UPDATE),
    ]
    first_lock = min(
        i for i, s in enumerate(e) if re.search(r"FOR (KEY SHARE|SHARE|UPDATE)|pg_advisory", s)
    )
    # the deferral is a plain SET issued before the key lock: the key lock is the first *lock*
    assert first_lock == chain[0] and chain[1:] == sorted(chain[1:]) and chain[0] < chain[2], (
        route,
        e,
    )
    assert e[-1] == "COMMIT"
    final = index(e, FINAL)
    assert not [
        s for s in e[final:] if re.search(r"\bFOR (KEY SHARE|SHARE|UPDATE|NO KEY UPDATE)\b", s)
    ]


@ALL_ROUTES
def test_an_unkeyed_route_takes_the_same_locks_without_a_key_lock_or_receipt(
    route: str, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    prepare_state(w, route)
    with Recorder(pooled) as recorded:
        response = call(pooled_factory, w, m.manager_user, route, body_for(w, route), key=None)
    assert code(response) == 200
    e = recorded.events
    assert not [s for s in e if re.search(r"pg_advisory|idempotent_requests|SET CONSTRAINTS", s)]
    assert (
        index(e, ROLES_S)
        < index(e, MEMBERSHIP_S)
        < index(e, ACCOUNT_S)
        < index(e, CAMPAIGN_U)
        < index(e, FINAL)
    )
    assert index(e, FINAL) < index(e, UPDATE_CAMPAIGN) < index(e, AUDIT_INSERT)
    assert e[-1] == "COMMIT"


# --- the plan's obligations ------------------------------------------------------------------------------------------


@ALL_ROUTES
@KEYED
def test_a_handler_that_forgets_to_finalize_is_a_sanitized_500_that_persists_nothing(
    route: str,
    keyed: bool,
    w: World,
    m: Managers,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_state(w, route)
    key = new_key() if keyed else None
    before = snapshot(w, key)
    monkeypatch.setattr(AuthorizationPlan, "finalize", lambda self, connection: None)
    response = call(pooled_factory, w, m.manager_user, route, body_for(w, route), key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error"
    assert snapshot(w, key) == before
    assert idle_in_transaction(w.engine) == 0


def _wrap_execute(
    monkeypatch: pytest.MonkeyPatch, *, skip: tuple[str, ...] = (), repeat: tuple[str, ...] = ()
) -> None:
    original = AuthorizationPlan.execute

    def wrapper(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> StepOutcome:
        if step.name in skip:
            return StepOutcome(step=step.name, keys=())
        outcome = original(self, connection, step, params)
        if step.name in repeat:
            original(self, connection, step, params)
        return outcome

    monkeypatch.setattr(AuthorizationPlan, "execute", wrapper)


@ALL_ROUTES
@pytest.mark.parametrize(
    ("keyed", "omit"),
    (
        (True, "business"),
        (True, "audit"),
        (True, "receipt"),
        (False, "business"),
        (False, "audit"),
    ),
    ids=("keyed-business", "keyed-audit", "keyed-receipt", "unkeyed-business", "unkeyed-audit"),
)
def test_an_omitted_required_write_is_refused_at_commit_and_rolls_everything_back(
    route: str,
    keyed: bool,
    omit: str,
    w: World,
    m: Managers,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: each business, audit and (keyed) receipt write is owed by the locked state
    (a genuine edit, an archive, a reactivation). A request that never runs one cannot commit: the guard
    refuses the incomplete plan (sanitized 500), the campaign, audit row and receipt all roll back, the key is
    reusable, the connection is clean. An unkeyed request declares no receipt step, so there is no
    unkeyed receipt case."""
    prepare_state(w, route)
    key = new_key() if keyed else None
    before = snapshot(w, key)
    step = {"business": STEP[route], "audit": AUDIT_STEP[route], "receipt": "receipt"}[omit]
    _wrap_execute(monkeypatch, skip=(step,))
    response = call(pooled_factory, w, m.manager_user, route, body_for(w, route), key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error", response.text
    assert snapshot(w, key) == before
    assert idle_in_transaction(w.engine) == 0
    again = call(pooled_factory, w, m.manager_user, route, body_for(w, route), key=key)
    assert code(again) == 200, again.text


@ALL_ROUTES
@KEYED
@pytest.mark.parametrize("extra", ("business", "audit"))
def test_a_repeated_write_is_refused_and_the_whole_request_rolls_back(
    route: str,
    keyed: bool,
    extra: str,
    w: World,
    m: Managers,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: a second campaign update or a second audit insert is a forbidden extra write.
    The second attempt is refused before the driver, and nothing persists."""
    prepare_state(w, route)
    key = new_key() if keyed else None
    before = snapshot(w, key)
    step = STEP[route] if extra == "business" else AUDIT_STEP[route]
    _wrap_execute(monkeypatch, repeat=(step,))
    with Recorder(pooled) as recorded:
        response = call(pooled_factory, w, m.manager_user, route, body_for(w, route), key=key)
    monkeypatch.undo()
    assert code(response) == 500, response.text
    pattern = UPDATE_CAMPAIGN if extra == "business" else AUDIT_INSERT
    assert len([s for s in recorded.events if re.search(pattern, s)]) == 1, (
        "the second never reached the driver"
    )
    assert snapshot(w, key) == before
    assert idle_in_transaction(w.engine) == 0


@KEYED
def test_a_write_attempted_for_a_no_op_update_is_refused_before_the_driver(
    keyed: bool,
    w: World,
    m: Managers,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: the update changes nothing, so the changed-row lock returned no row. A handler
    that claims a change anyway is refused for both writes (`TARGET_NOT_LOCKED`, and the audit insert on empty
    evidence) before the driver; nothing persists."""
    before = state(w)
    key = new_key() if keyed else None
    original = __import__("dnd_ai.api.campaigns", fromlist=["x"]).prepare_update_campaign

    def claim_change(*args: Any, **kwargs: Any) -> Any:
        prepared = original(*args, **kwargs)
        return dataclasses.replace(
            prepared, changed=True, changed_fields={"name": {"from": "a", "to": "b"}}
        )

    monkeypatch.setattr("dnd_ai.api.campaigns.prepare_update_campaign", claim_change)
    body = {"expected_row_version": before[3], "name": before[0], "description": before[1]}
    with Recorder(pooled) as recorded:
        response = call(pooled_factory, w, m.manager_user, "update", body, key=key)
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert not [s for s in recorded.events if re.search(UPDATE_CAMPAIGN + "|" + AUDIT_INSERT, s)]
    assert state(w) == before and audit_rows(w) == [] and (receipt(w, key or "") == ())


# --- competitors for the declared writes, the foreign keys, the triggers --------------------------------------------


@ALL_ROUTES
def test_the_locks_held_at_the_final_statement_exclude_every_conflicting_competitor(
    route: str, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*: at its final statement the request holds the actor's role rows, membership and account
    (`FOR SHARE`), the campaign `FOR UPDATE` (and the world and timeline `FOR SHARE` for reactivate). A
    competitor taking any of them `FOR UPDATE` queues behind it, blocked by the request's pid; the
    request still commits with all of them queued, so no post-finalization write, foreign-key re-check or
    COMMIT-time trigger can ever wait for one of these rows."""
    prepare_state(w, route)
    targets = [
        (
            "roles",
            "SELECT 1 FROM security.membership_roles WHERE membership_role_id = :id FOR UPDATE",
            m.manager_role,
        ),
        (
            "membership",
            "SELECT 1 FROM security.campaign_memberships WHERE campaign_membership_id = :id FOR UPDATE",
            m.manager_membership,
        ),
        ("account", "SELECT 1 FROM security.users WHERE user_id = :id FOR UPDATE", m.manager_user),
        (
            "campaign",
            "SELECT 1 FROM campaign.campaigns WHERE campaign_id = :id FOR UPDATE",
            w.campaign_id,
        ),
    ]
    if route == "reactivate":
        with w.engine.connect() as c:
            timeline = c.execute(
                text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
                {"c": w.campaign_id},
            ).scalar_one()
        targets += [
            ("world", "SELECT 1 FROM core.worlds WHERE world_id = :id FOR UPDATE", w.world_id),
            (
                "timeline",
                "SELECT 1 FROM campaign.timelines WHERE timeline_id = :id FOR UPDATE",
                timeline,
            ),
        ]
    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread(
            route,
            lambda: call(
                pooled_factory, w, m.manager_user, route, body_for(w, route), key=new_key()
            ),
        )
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(w.engine) as race:
            competitors = [
                race.start(
                    name, lambda c, sql=sql, ident=ident: c.execute(text(sql), {"id": ident}).all()
                )
                for name, sql, ident in targets
            ]
            race.wait_blocked_by(gate, expected=len(targets))
            assert all(not c.done for c in competitors)
            gate.release()
            response = request.wait("the request commits with its competitors queued")
            race.join_all()
    assert code(response) == 200, response.text
    assert all(c.error is None for c in competitors)


def _hold_and_expect_wait(
    w: World,
    pooled: Engine,
    pooled_factory: Factory,
    m: Managers,
    route: str,
    hold_sql: str,
    params: dict[str, Any],
    waits_in: str,
) -> Any:
    """A competitor holds a row the request's declared write touches only through a foreign key or a
    trigger; the request must wait (blocked by that holder, in the named statement) and then commit."""
    prepare_state(w, route)
    with LockRace(w.engine) as race:
        hold = race.hold(lambda c: c.execute(text(hold_sql), params).all())
        request = run_in_thread(
            route,
            lambda: call(
                pooled_factory, w, m.manager_user, route, body_for(w, route), key=new_key()
            ),
        )
        race.wait_blocked_by(hold, expected=1)
        statement = waiting_statement(w.engine, hold.pid)
        assert waits_in in statement, statement
        assert not request.finished()
        hold.commit()
        response = request.wait("the request finishes once the holder commits")
        race.join_all()
    return response


@pytest.mark.parametrize(
    ("route", "action"),
    (("update", "updated"), ("archive", "archived"), ("reactivate", "restored")),
)
def test_the_audit_insert_waits_for_a_competitor_holding_its_action_row_and_then_commits(
    route: str, action: str, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, a reviewed *unlocked* foreign-key target (permitted residual wait): `audit.change_actions` is
    seed data nobody in the application locks. A holder of the action's row `FOR UPDATE` makes the
    post-finalization audit insert wait (bounded by the holder); the request then commits."""
    response = _hold_and_expect_wait(
        w,
        pooled,
        pooled_factory,
        m,
        route,
        "SELECT 1 FROM audit.change_actions WHERE code = :code FOR UPDATE",
        {"code": action},
        "audit.change_log",
    )
    assert code(response) == 200, response.text


@pytest.mark.parametrize("route", ("archive", "reactivate"))
def test_the_lifecycle_update_waits_for_a_competitor_holding_its_status_row_and_then_commits(
    route: str, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, a reviewed *unlocked* foreign-key target (permitted residual wait): the campaign's lifecycle
    FK takes `FOR KEY SHARE` on `core.lifecycle_statuses`, seed data nobody updates."""
    status = "archived" if route == "archive" else "active"
    response = _hold_and_expect_wait(
        w,
        pooled,
        pooled_factory,
        m,
        route,
        "SELECT 1 FROM core.lifecycle_statuses WHERE code = :code FOR UPDATE",
        {"code": status},
        "campaign.campaigns",
    )
    assert code(response) == 200, response.text


@ALL_ROUTES
def test_the_ruleset_trigger_takes_the_worlds_ruleset_row_for_share_a_permitted_residual_wait(
    route: str, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, a trigger effect that is **not** a re-acquisition: `enforce_campaign_ruleset_allowed` runs on
    every campaign `UPDATE` and takes `rules.world_rulesets` `FOR SHARE`. A holder of that row `FOR UPDATE`
    (the application never issues one: the row is inserted once, at world creation) makes the campaign
    update wait; recorded as a residual, bounded by the holder, and released when it commits."""
    response = _hold_and_expect_wait(
        w,
        pooled,
        pooled_factory,
        m,
        route,
        "SELECT 1 FROM rules.world_rulesets WHERE world_id = :w FOR UPDATE",
        {"w": w.world_id},
        "campaign.campaigns",
    )
    assert code(response) == 200, response.text


def test_the_reactivation_retention_trigger_reacquires_the_held_campaign_and_reads_without_locks(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, the COMMIT-time retention trigger of reactivation. (1) Its `FOR UPDATE` on the campaign is a
    re-acquisition of the lock the request holds: with a competitor already queued for the campaign the
    request still commits (the trigger never waits behind it). (2) Its access-manager read takes no lock: a
    transaction holding the surviving manager's role row `FOR UPDATE` does not delay the commit. Both are
    measured, not read from the source."""
    set_campaign_status(w, "archived")
    with w.engine.connect() as c:
        keeper_role = c.execute(
            text(
                "SELECT membership_role_id FROM security.membership_roles WHERE campaign_membership_id = :m"
            ),
            {"m": m.keeper_membership},
        ).scalar_one()
    key = new_key()
    deadlocks = deadlock_count(w.engine)
    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread(
            "reactivate",
            lambda: call(
                pooled_factory, w, m.manager_user, "reactivate", body_for(w, "reactivate"), key=key
            ),
        )
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(w.engine) as race:
            queued = race.start(
                "campaign",
                lambda c: c.execute(
                    text("SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c FOR UPDATE"),
                    {"c": w.campaign_id},
                ).all(),
            )
            race.wait_blocked_by(gate, expected=1)
            reader_hold = race.hold(
                lambda c: c.execute(
                    text(
                        "SELECT 1 FROM security.membership_roles WHERE membership_role_id = :r FOR UPDATE"
                    ),
                    {"r": keeper_role},
                ).all()
            )
            gate.release()
            response = request.wait("the reactivation commits with the campaign competitor queued")
            reader_hold.commit()
            race.join_all()
    assert code(response) == 200, response.text
    assert queued.error is None and state(w)[2] == "active"
    assert wait_for_deadlock_count(w.engine, deadlocks) == deadlocks


def test_a_commit_time_retention_failure_is_a_500_that_persists_nothing_and_leaves_the_key_reusable(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """*mutation (test-side)*: the pre-check that makes the trigger unreachable in the application is
    defeated, so the request passes it for a campaign with no surviving manager and the trigger refuses at
    COMMIT. Expected (unchanged) behavior: a server error, the campaign still archived, no audit row and no
    receipt; the key is reusable once the cause is fixed."""
    set_campaign_status(w, "archived")
    with w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = now() + interval '1 day' "
                "WHERE campaign_membership_id IN (SELECT campaign_membership_id FROM "
                "security.campaign_memberships WHERE campaign_id = :c)"
            ),
            {"c": w.campaign_id},
        )
    from dnd_ai.commands import campaigns as commands

    real = commands.campaign_blocked_reason
    monkeypatch.setattr(
        commands,
        "campaign_blocked_reason",
        lambda action, **kw: real(action, **{**kw, "has_access_manager": True}),
    )
    key = new_key()
    before = snapshot(w, key)
    response = call(
        pooled_factory, w, m.manager_user, "reactivate", body_for(w, "reactivate"), key=key
    )
    monkeypatch.undo()
    assert code(response) >= 500, response.text
    assert snapshot(w, key) == before and state(w)[2] == "archived"
    assert idle_in_transaction(w.engine) == 0
    blocked = call(
        pooled_factory, w, m.manager_user, "reactivate", body_for(w, "reactivate"), key=key
    )
    assert code(blocked) == 409 and error_of(blocked) == "campaign_access_manager_required"


# --- the declarations hold against the live catalogue ------------------------------------------------------------------


def test_the_declarations_hold_against_the_live_catalogue(w: World) -> None:
    """The S1 catalogue helper checks every assumption a declaration makes about the database (the five
    campaign triggers pinned by function-source hash, unique waits, FK match type and order, defaults,
    CHECK expressions). An empty list is the only passing answer."""
    from dnd_ai.commands.campaign_lifecycle_plans import (
        ARCHIVE_DECLARATIONS,
        REACTIVATE_DECLARATIONS,
        UPDATE_DECLARATIONS,
    )
    from tests.r01_pre_write_catalogue import check_declaration

    problems: list[str] = []
    with w.engine.connect() as connection:
        for name, declarations in (
            ("update", UPDATE_DECLARATIONS),
            ("archive", ARCHIVE_DECLARATIONS),
            ("reactivate", REACTIVATE_DECLARATIONS),
        ):
            for kind, declaration in (
                ("reserved", declarations.reserved),
                ("unkeyed", declarations.unkeyed),
            ):
                assert declaration is not None
                problems += [
                    f"{name}/{kind}: {p}" for p in check_declaration(connection, declaration)
                ]
    assert problems == []


def test_the_response_version_is_the_stored_version(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """The step returns only the primary key, so the response's `row_version` is the held version plus one
    (`core.bump_row_version`, source pinned in the declaration). Compared with the stored value."""
    for _ in range(2):
        response = call(
            pooled_factory,
            w,
            m.manager_user,
            "update",
            body_for(w, "update", name=f"N{uuid.uuid4().hex[:6]}"),
            key=None,
        )
        assert code(response) == 200 and response.json()["row_version"] == state(w)[3]
