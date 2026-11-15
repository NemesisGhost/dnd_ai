# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E2: add member and assign, change and revoke role as keyed pre-write plans, over real HTTP.

The four routes (`dnd_ai.commands.membership_role_plans`) take the actor's rows (together with the target's, in
one ordered statement per class that has a target), then the campaign, then the catalogue role rows, judge
authority at `plan.finalize`, and only then write through declared steps. Ownership transfer is **not** one of
them (plan 6.27, "The gap"): the legacy end command is exercised only where a race needs it.

Evidence classes (labelled in each docstring):

- **route**: a real HTTP request through the guard on a one-connection pool.
- **sql**: the recorded statement stream of such a request (`Recorder`).
- **race**: a route request on one side and a competitor on the other, each parked on a named statement; every
  wait is observed through `pg_blocking_pids` (blocker pid and waiting statement checked), never assumed.
- **mutation (test-side)**: `AuthorizationPlan.execute` is wrapped to omit or repeat a write, to show that the
  declared obligations refuse it. Nothing production-side is changed.

The shared authoring harness cannot establish transaction, deferral, lock or COMMIT guarantees (it shares one
transaction and never commits); none of this module uses it.
"""

import dataclasses
import re
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.commands.memberships import end_campaign_membership
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER
from dnd_ai.domain.authorization import AuthorizationPlan, StepOutcome, install_authorization_guard
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
from tests.factories import (
    make_campaign_membership,
    make_external_identity,
    make_membership_role,
    make_role,
    make_role_capability,
    make_user,
    oidc_principal,
    system_role_id,
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
ROUTES = ("add", "assign", "change", "revoke")
ALL_ROUTES = pytest.mark.parametrize("route", ROUTES)
KEYED = pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))

KEY_LOCK = r"pg_advisory_xact_lock"
ROLES_S = r"FROM security\.membership_roles WHERE .* FOR SHARE$"
ROLE_ROWS_U = r"FROM security\.membership_roles WHERE .* ORDER BY .* FOR UPDATE$"
MEMBERSHIP_S = r"FROM security\.campaign_memberships WHERE .* FOR SHARE$"
MEMBERSHIPS_U = r"FROM security\.campaign_memberships WHERE .* ORDER BY .* FOR UPDATE$"
ACCOUNT_S = r"FROM security\.users WHERE .* FOR SHARE$"
CAMPAIGN_U = r"FROM campaign\.campaigns WHERE campaign\.campaigns\.campaign_id = %\(campaign\)s::UUID FOR UPDATE$"
CAMPAIGN_KS = r"FROM campaign\.campaigns WHERE .* FOR KEY SHARE$"
ROLE_CATALOGUE_U = r"FROM security\.roles WHERE .* ORDER BY .* FOR UPDATE$"
RECEIPT_U = r"FROM security\.idempotent_requests WHERE .*idempotent_request_id = %\(receipt\)s::UUID FOR UPDATE"
AUDIT_INSERT = r"^INSERT INTO audit\.change_log"
RECEIPT_UPDATE = r"^UPDATE security\.idempotent_requests"
INSERT_MEMBERSHIP = r"^INSERT INTO security\.campaign_memberships"
INSERT_ROLE = r"^INSERT INTO security\.membership_roles"
UPDATE_ROLE = r"^UPDATE security\.membership_roles SET revoked_at"
FIRST_LOCK = {"add": ROLES_S, "assign": ROLES_S, "change": ROLE_ROWS_U, "revoke": ROLE_ROWS_U}
COMMAND = {
    "add": "add_campaign_member",
    "assign": "assign_membership_role",
    "change": "change_membership_role",
    "revoke": "revoke_membership_role",
}
BUSINESS_STEPS = {
    "add": ("insert_membership", "insert_initial_role"),
    "assign": ("insert_role",),
    "change": ("revoke_old_role", "insert_new_role"),
    "revoke": ("revoke_role",),
}
AUDIT_STEPS = {
    "add": ("audit_membership_created", "audit_role_created"),
    "assign": ("audit_assigned",),
    "change": ("audit_changed",),
    "revoke": ("audit_revoked",),
}
STATUS = {"add": 201, "assign": 201, "change": 201, "revoke": 200}


@dataclasses.dataclass
class Scene:
    w: World
    m: Managers
    player: uuid.UUID
    observer: uuid.UUID
    gm: uuid.UUID
    owner: uuid.UUID
    target_user: uuid.UUID
    target_membership: uuid.UUID
    target_role: uuid.UUID  # the target's player assignment
    new_user: uuid.UUID  # an eligible account with no membership
    manage_role: uuid.UUID  # a campaign role that grants access.manage


@pytest.fixture
def m(w: World) -> Managers:
    return make_managers(w.engine, w.campaign_id, label="S5E2 Role")


@pytest.fixture
def s(w: World, m: Managers) -> Scene:
    with w.engine.begin() as c:
        player = system_role_id(c, "player")
        observer = system_role_id(c, "observer")
        gm = system_role_id(c, "gm")
        owner = system_role_id(c, "campaign_owner")
        target_user = make_user(c, "S5E2 Target")
        make_external_identity(c, target_user, issuer=LOCAL_AUTH_ISSUER)
        target_membership = make_campaign_membership(c, w.campaign_id, target_user)
        target_role = make_membership_role(c, target_membership, player)
        new_user = make_user(c, "S5E2 New")
        make_external_identity(c, new_user, issuer=LOCAL_AUTH_ISSUER)
        capability = c.execute(
            text("SELECT capability_id FROM security.capabilities WHERE code = 'access.manage'")
        ).scalar_one()
        manage_role = make_role(c, campaign_id=w.campaign_id)
        make_role_capability(c, manage_role, capability)
    return Scene(
        w,
        m,
        player,
        observer,
        gm,
        owner,
        target_user,
        target_membership,
        target_role,
        new_user,
        manage_role,
    )


@pytest.fixture
def pooled2(postgres_engine: Engine) -> Any:
    """Like `pooled` with two connections: two simultaneous requests (the shared `pooled` has one, so a second
    request would wait for the pool, not at the database)."""
    engine = create_engine(
        postgres_engine.url, pool_size=2, max_overflow=0, isolation_level="READ COMMITTED"
    )
    install_authorization_guard(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def pooled2_factory(pooled2: Engine) -> Factory:
    def make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: pooled2
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return make


@pytest.fixture(autouse=True)
def _tidy(w: World) -> Any:
    yield
    with w.engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text(
                "DELETE FROM audit.change_log WHERE world_id = :w AND table_name IN "
                "('campaign_memberships', 'membership_roles')"
            ),
            {"w": w.world_id},
        )


# --- helpers ------------------------------------------------------------------------------------------------------


def request_for(sc: Scene, route: str, **over: Any) -> tuple[str, dict[str, Any]]:
    base = sc.w.base
    if route == "add":
        body = {
            "user_id": str(over.get("user", sc.new_user)),
            "role_id": str(over.get("role", sc.player)),
        }
        return f"{base}/memberships", body
    if route == "assign":
        body = {"role_id": str(over.get("role", sc.observer))}
        if over.get("expires"):
            body["expires_at"] = over["expires"]
        return f"{base}/memberships/{over.get('membership', sc.target_membership)}/roles", body
    if route == "change":
        return (
            f"{base}/memberships/roles/{over.get('target', sc.target_role)}/change",
            {"new_role_id": str(over.get("role", sc.observer))},
        )
    return f"{base}/memberships/roles/{over.get('target', sc.target_role)}/revoke", {}


def call(
    factory: Factory,
    sc: Scene,
    route: str,
    *,
    key: str | None,
    actor: uuid.UUID | None = None,
    **over: Any,
) -> Any:
    path, body = request_for(sc, route, **over)
    headers = {"Idempotency-Key": key} if key else {}
    with factory(actor or sc.m.manager_user) as client:
        return client.post(path, json=body, headers=headers)


def snapshot(sc: Scene, key: str | None = None) -> tuple[Any, ...]:
    """Everything any of the four routes can persist: memberships, assignments, audit rows, the key's receipt."""
    with sc.w.engine.connect() as c:
        memberships = c.execute(
            text(
                "SELECT campaign_membership_id, user_id, ended_at IS NULL FROM security.campaign_memberships "
                "WHERE campaign_id = :c ORDER BY 1"
            ),
            {"c": sc.w.campaign_id},
        ).all()
        assignments = c.execute(
            text(
                "SELECT mr.membership_role_id, mr.role_id, mr.revoked_at IS NULL, mr.expires_at "
                "FROM security.membership_roles mr JOIN security.campaign_memberships cm "
                "USING (campaign_membership_id) WHERE cm.campaign_id = :c "
                "AND mr.membership_role_id <> :mgr ORDER BY 1"
            ),
            {"c": sc.w.campaign_id, "mgr": sc.m.manager_role},
        ).all()
        audit = c.execute(
            text(
                "SELECT command_name, table_name, record_id FROM audit.change_log WHERE world_id = :w "
                "AND table_name IN ('campaign_memberships','membership_roles') ORDER BY change_log_id"
            ),
            {"w": sc.w.world_id},
        ).all()
        receipt = (
            c.execute(
                text(
                    "SELECT response_status_code, response_body, completed_at IS NOT NULL "
                    "FROM security.idempotent_requests WHERE campaign_id = :c AND idempotency_key = :k"
                ),
                {"c": sc.w.campaign_id, "k": key},
            ).one_or_none()
            if key
            else None
        )
    return (
        [tuple(r) for r in memberships],
        [tuple(r) for r in assignments],
        [tuple(r) for r in audit],
        tuple(receipt) if receipt else (),
    )


def audits(sc: Scene, command: str) -> list[tuple[Any, ...]]:
    return [r for r in snapshot(sc)[2] if r[0] == command]


def index(events: list[str], pattern: str, start: int = 0) -> int:
    matches = [i for i, e in enumerate(events) if i >= start and re.search(pattern, e)]
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


def add_open_delegation(sc: Scene) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A gm member with a live reveal delegation bound to its gm assignment: (membership, gm role row, delegation)."""
    with sc.w.engine.begin() as c:
        user = make_user(c, "S5E2 GM")
        membership = make_campaign_membership(c, sc.w.campaign_id, user)
        gm_row = make_membership_role(c, membership, sc.gm)
        delegation = c.execute(
            text(
                "INSERT INTO security.character_reveal_delegations (campaign_id, grantee_campaign_membership_id, "
                "gm_membership_role_id, granted_by_membership_id, reason) "
                "VALUES (:c, :g, :r, :a, 'x') RETURNING character_reveal_delegation_id"
            ),
            {"c": sc.w.campaign_id, "g": membership, "r": gm_row, "a": sc.m.keeper_membership},
        ).scalar_one()
    return membership, gm_row, delegation


# --- success, no-op, invalid targets ----------------------------------------------------------------------------------


@ALL_ROUTES
@KEYED
def test_a_manager_runs_each_route_with_its_audit_rows_and_receipt(
    route: str, keyed: bool, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the documented status and body; the rows the command always wrote; the audit rows (two for add,
    one otherwise, naming the command); a receipt only for a keyed request, whose stored body is the response."""
    before = snapshot(s)
    key = new_key() if keyed else None
    response = call(pooled_factory, s, route, key=key)
    assert code(response) == STATUS[route], response.text
    after = snapshot(s, key)
    body = response.json()
    if route == "add":
        assert len(after[0]) == len(before[0]) + 1 and len(after[1]) == len(before[1]) + 1
        assert len(audits(s, "add_campaign_member")) == 2
        assert {"campaign_membership_id", "membership_role_id"} == set(body)
    elif route == "assign":
        assert len(after[1]) == len(before[1]) + 1 and len(audits(s, COMMAND[route])) == 1
    elif route == "change":
        assert len(after[1]) == len(before[1]) + 1 and len(audits(s, COMMAND[route])) == 1
        old = next(a for a in after[1] if a[0] == s.target_role)
        assert old[2] is False, "the old assignment is revoked"
    else:
        assert next(a for a in after[1] if a[0] == s.target_role)[2] is False
        assert len(audits(s, COMMAND[route])) == 1 and body == {
            "membership_role_id": str(s.target_role)
        }
    if keyed:
        assert after[3] == (STATUS[route], body, True)
    else:
        assert after[3] == ()
    assert idle_in_transaction(s.w.engine) == 0


@KEYED
def test_revoking_an_already_revoked_assignment_writes_nothing_and_a_keyed_one_completes_its_receipt(
    keyed: bool, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: the legitimate no-op. No update, no delegation write, no audit row; a fresh keyed no-op
    still completes its receipt and replays it."""
    revoke_role(s.w.engine, s.target_role)
    before = snapshot(s)
    key = new_key() if keyed else None
    with Recorder(pooled) as recorded:
        response = call(pooled_factory, s, "revoke", key=key)
    assert code(response) == 200 and response.json() == {"membership_role_id": str(s.target_role)}
    after = snapshot(s, key)
    assert after[:3] == before[:3]
    assert not [e for e in recorded.events if re.search(UPDATE_ROLE + "|" + AUDIT_INSERT, e)]
    assert len([e for e in recorded.events if re.search(RECEIPT_UPDATE, e)]) == (1 if keyed else 0)
    if keyed:
        assert after[3] == (200, response.json(), True)
        again = call(pooled_factory, s, "revoke", key=key)
        assert code(again) == 200 and again.json() == response.json() and snapshot(s, key) == after


@KEYED
def test_refusals_keep_their_errors_and_persist_nothing_and_the_key_is_reusable(
    keyed: bool, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: invalid targets keep the classified errors they always had. Nothing persists, no key is consumed,
    the connection returns clean."""
    with s.w.engine.begin() as c:
        inactive = make_role(c, campaign_id=s.w.campaign_id)
        c.execute(
            text("UPDATE security.roles SET is_active = false WHERE role_id = :r"), {"r": inactive}
        )
        ended = make_campaign_membership(c, s.w.campaign_id, make_user(c, "S5E2 Ended"), ended=True)
        inactive_user = make_user(c, "S5E2 Inactive", status_code="inactive")
        make_external_identity(c, inactive_user, issuer=LOCAL_AUTH_ISSUER)
        no_identity = make_user(c, "S5E2 NoIdentity")
    key = new_key() if keyed else None
    absent = uuid.uuid4()
    cases: list[tuple[str, dict[str, Any], int]] = [
        ("add", {"user": absent}, 404),
        ("add", {"user": inactive_user}, 404),
        ("add", {"user": no_identity}, 404),
        ("add", {"user": s.new_user, "role": inactive}, 404),
        ("add", {"user": s.target_user}, 409),
        ("assign", {"membership": absent}, 404),
        ("assign", {"membership": ended}, 409),
        ("assign", {"role": inactive}, 404),
        ("assign", {"role": s.player}, 409),
        ("change", {"target": absent}, 404),
        ("change", {"role": s.player}, 422),
        ("change", {"role": inactive}, 404),
        ("revoke", {"target": absent}, 404),
    ]
    before = snapshot(s, key)
    for route, over, status in cases:
        response = call(pooled_factory, s, route, key=key, **over)
        assert code(response) == status, (route, over, response.text)
        assert snapshot(s, key) == before, (route, over)
        assert idle_in_transaction(s.w.engine) == 0
    ok = call(pooled_factory, s, "assign", key=key)
    assert code(ok) == 201, ok.text


def test_an_assignment_that_has_an_expiry_keeps_it(
    s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    response = call(pooled_factory, s, "assign", key=new_key(), expires="2099-01-01T00:00:00Z")
    assert code(response) == 201
    assert any(a[3] is not None for a in snapshot(s)[1])


# --- replay and authority ------------------------------------------------------------------------------------------


@ALL_ROUTES
def test_an_authorized_replay_returns_the_stored_receipt_without_a_lock_or_a_write(
    route: str, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: the stored body, no row lock, no write, and the final authority statement last before
    COMMIT (the receipt does not leave before the check). The replay does not re-run the command's rules."""
    key = new_key()
    first = call(pooled_factory, s, route, key=key)
    assert code(first) == STATUS[route]
    stored = snapshot(s, key)
    with Recorder(pooled) as recorded:
        replay = call(pooled_factory, s, route, key=key)
    assert code(replay) == STATUS[route] and replay.json() == first.json()
    assert snapshot(s, key) == stored
    finals = [e for e in recorded.events if FINAL_RE.search(e)]
    assert len(finals) == 1 and recorded.events[-2:] == [finals[0], "COMMIT"]
    assert not [
        e for e in recorded.events if re.search(r"FOR (KEY SHARE|SHARE|UPDATE|NO KEY UPDATE)", e)
    ]
    writes = [e for e in recorded.events if e.startswith(("INSERT", "UPDATE", "DELETE"))]
    assert all("idempotent_requests" in e and "ON CONFLICT" in e for e in writes), writes


@ALL_ROUTES
def test_a_replay_after_authority_loss_is_refused_and_returns_nothing_from_the_receipt(
    route: str, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    key = new_key()
    first = call(pooled_factory, s, route, key=key)
    assert code(first) == STATUS[route]
    stored = snapshot(s, key)
    revoke_role(s.w.engine, s.m.manager_role)
    again = call(pooled_factory, s, route, key=key)
    assert code(again) in (403, 404), again.text
    assert "membership_role_id" not in again.text and "campaign_membership_id" not in again.text
    assert snapshot(s, key) == stored


@ALL_ROUTES
def test_a_reused_key_with_another_payload_is_the_same_conflict_and_changes_nothing(
    route: str, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    key = new_key()
    assert code(call(pooled_factory, s, route, key=key)) == STATUS[route]
    stored = snapshot(s, key)
    other: dict[str, Any] = {
        "add": {"user": s.target_user},
        "assign": {"role": s.gm},
        "change": {"role": s.gm},
        "revoke": {"target": uuid.uuid4()},
    }[route]
    response = call(pooled_factory, s, route, key=key, **other)
    assert code(response) == 409 and error_of(response) == "conflict", response.text
    assert snapshot(s, key) == stored


@ALL_ROUTES
@KEYED
def test_a_role_that_lapses_before_the_final_statement_refuses_the_route_and_rolls_everything_back(
    route: str, keyed: bool, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* (race): the manager's role is valid for every early check and has lapsed (a DATABASE condition,
    polled) when the final authority statement runs, every lock already held. Nothing persists; the key is
    reusable."""
    key = new_key() if keyed else None
    before = snapshot(s, key)
    response = run_with_role_lapsing_before_final(
        s.w.engine,
        pooled,
        s.m.manager_role,
        lambda: call(pooled_factory, s, route, key=key),
        first_gate=KEY_LOCK if keyed else FIRST_LOCK[route],
    )
    assert code(response) in (403, 404), (route, keyed, response.text)
    assert snapshot(s, key) == before
    assert idle_in_transaction(s.w.engine) == 0
    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = NULL WHERE membership_role_id = :r"
            ),
            {"r": s.m.manager_role},
        )
    assert code(call(pooled_factory, s, route, key=key)) == STATUS[route]


@ALL_ROUTES
def test_a_role_revoked_before_the_request_is_refused_early_and_writes_nothing(
    route: str, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    revoke_role(s.w.engine, s.m.manager_role)
    key = new_key()
    before = snapshot(s, key)
    response = call(pooled_factory, s, route, key=key)
    assert code(response) in (403, 404), response.text
    assert snapshot(s, key) == before


def _revoke_manager(s: Scene) -> Callable[[Any], Any]:
    return lambda c: c.execute(
        text(
            "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
        ),
        {"r": s.m.manager_role},
    )


@ALL_ROUTES
def test_a_role_revocation_in_flight_makes_the_request_wait_then_refuses_it_without_a_deadlock(
    route: str, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, ordering 1 (the authority change holds first): a revocation of the manager's role has updated the
    row and not committed. The request passes its early check and queues at its first lock on role rows, blocked
    by the revoker's pid, holding nothing the revoker wants (its retention trigger wants the campaign at its
    COMMIT). The revoker commits; the request's lock then finds no unrevoked role and `finalize` refuses it."""
    key = new_key()
    before = snapshot(s, key)
    deadlocks = deadlock_count(s.w.engine)
    with LockRace(s.w.engine) as race:
        hold = race.hold(_revoke_manager(s))
        request = run_in_thread(route, lambda: call(pooled_factory, s, route, key=key))
        race.wait_blocked_by(hold, expected=1)
        statement = waiting_statement(s.w.engine, hold.pid)
        assert "security.membership_roles" in statement and re.search(
            r"FOR (SHARE|UPDATE)", statement
        )
        assert not request.finished()
        hold.commit()
        response = request.wait("the request finishes after the revocation commits")
        race.join_all()
    assert code(response) in (403, 404), response.text
    after = snapshot(s, key)
    assert after[0] == before[0] and after[2] == before[2] and after[3] == before[3]
    assert wait_for_deadlock_count(s.w.engine, deadlocks) == deadlocks
    assert idle_in_transaction(s.w.engine) == 0


@ALL_ROUTES
def test_a_request_holding_the_actors_rows_makes_a_role_revocation_wait_and_both_commit(
    route: str, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, ordering 2 (the request holds first): parked at its final statement the request holds the actor's
    role rows. A revocation of the manager's role queues at that row (blocked by the request's pid, waiting in its
    `UPDATE`), the request commits, then the revocation commits: authority was judged before the change."""
    key = new_key()
    deadlocks = deadlock_count(s.w.engine)
    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread(route, lambda: call(pooled_factory, s, route, key=key))
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            revoker = race.start("revoke", _revoke_manager(s))
            race.wait_blocked_by(gate, expected=1)
            assert "membership_roles" in waiting_statement(s.w.engine, gate.pid)
            assert not revoker.done
            gate.release()
            response = request.wait("the request finishes")
            race.join_all()
    assert code(response) == STATUS[route], response.text
    assert revoker.error is None
    assert wait_for_deadlock_count(s.w.engine, deadlocks) == deadlocks


# --- self-affecting operations ------------------------------------------------------------------------------------------


def _remove_keeper(s: Scene) -> None:
    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = now() + interval '1 day' "
                "WHERE campaign_membership_id IN (SELECT campaign_membership_id FROM "
                "security.campaign_memberships WHERE campaign_id = :c) AND membership_role_id <> :mgr"
            ),
            {"c": s.w.campaign_id, "mgr": s.m.manager_role},
        )


def test_a_manager_may_revoke_their_own_manager_role_when_another_manager_survives(
    s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: self-revocation is judged against the pre-command authority (the route requirement is evaluated at
    `finalize`, before the update), so it succeeds; the keeper survives; the receipt is then refused to the same
    caller, whose authority the revocation took."""
    key = new_key()
    response = call(pooled_factory, s, "revoke", key=key, target=s.m.manager_role)
    assert code(response) == 200, response.text
    with s.w.engine.connect() as c:
        assert c.execute(
            text(
                "SELECT revoked_at IS NOT NULL FROM security.membership_roles WHERE membership_role_id = :r"
            ),
            {"r": s.m.manager_role},
        ).scalar_one()
    assert code(call(pooled_factory, s, "revoke", key=key, target=s.m.manager_role)) in (403, 404)


@pytest.mark.parametrize("route", ("revoke", "change"))
@KEYED
def test_the_last_manager_cannot_revoke_or_demote_themselves_and_nothing_persists(
    route: str, keyed: bool, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: with the keeper's role expiring the manager is the only non-expiring `access.manage` holder. The
    pre-check (before `finalize`, under the held campaign lock) refuses with the same 400 as before; the deferred
    trigger is not reached. Nothing persists; the key is reusable once a keeper is restored."""
    _remove_keeper(s)
    key = new_key() if keyed else None
    before = snapshot(s, key)
    response = call(pooled_factory, s, route, key=key, target=s.m.manager_role)
    assert code(response) == 400, response.text
    assert snapshot(s, key) == before and idle_in_transaction(s.w.engine) == 0
    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = NULL WHERE campaign_membership_id = :m"
            ),
            {"m": s.m.keeper_membership},
        )
    assert code(call(pooled_factory, s, route, key=key, target=s.m.manager_role)) == STATUS[route]


def test_changing_the_only_manager_role_to_another_manager_role_is_not_a_retention_failure(
    s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the change moves `access.manage` from one assignment to another, so the pre-check counts the new
    assignment and permits it, as the post-write check did."""
    _remove_keeper(s)
    response = call(
        pooled_factory, s, "change", key=new_key(), target=s.m.manager_role, role=s.manage_role
    )
    assert code(response) == 201, response.text


def test_a_manager_may_assign_themselves_another_role_judged_before_the_insert(
    s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    response = call(
        pooled_factory,
        s,
        "assign",
        key=new_key(),
        membership=s.m.manager_membership,
        role=s.observer,
    )
    assert code(response) == 201, response.text


@KEYED
def test_newly_granted_authority_does_not_mask_a_lapse_on_a_self_assignment(
    keyed: bool, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* (race): the manager assigns *themselves* a role that grants `access.manage` while their own role
    lapses before the final statement. Authority is judged at `finalize`, before the insert, so the lapse refuses
    the request: the new role does not exist yet and cannot stand in for the lost one."""
    key = new_key() if keyed else None
    before = snapshot(s, key)
    response = run_with_role_lapsing_before_final(
        s.w.engine,
        pooled,
        s.m.manager_role,
        lambda: call(
            pooled_factory,
            s,
            "assign",
            key=key,
            membership=s.m.manager_membership,
            role=s.manage_role,
        ),
        first_gate=KEY_LOCK if keyed else ROLES_S,
    )
    assert code(response) in (403, 404), response.text
    assert snapshot(s, key) == before


@pytest.mark.parametrize("route", ("add", "assign", "change"))
def test_granting_the_owner_role_needs_a_live_owner_and_a_non_owner_learns_nothing_else(
    route: str, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: decision D3. A manager who is not a campaign owner is refused (403) before any other check, and
    nothing persists; a live owner may grant it."""
    before = snapshot(s)
    refused = call(pooled_factory, s, route, key=new_key(), role=s.owner)
    assert code(refused) == 403 and error_of(refused) is not None
    assert snapshot(s) == before
    with s.w.engine.begin() as c:
        make_membership_role(c, s.m.manager_membership, s.owner)
    ok = call(pooled_factory, s, route, key=new_key(), role=s.owner)
    assert code(ok) == STATUS[route], ok.text


# --- ordering and the declared obligations ------------------------------------------------------------------------------


@ALL_ROUTES
def test_the_keyed_route_runs_its_statements_in_the_documented_order(
    route: str, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*sql*: key lock, deferral, reservation, the actor's rows (together with the target's where the class has
    one), the actor's account, the campaign, the catalogue role row, our reservation row, the one final authority
    statement, and only after it the declared writes, COMMIT last, no row lock after the final statement."""
    with Recorder(pooled) as recorded:
        response = call(pooled_factory, s, route, key=new_key())
    assert code(response) == STATUS[route], response.text
    e = recorded.events
    chain = [
        index(e, KEY_LOCK),
        index(e, r"SET CONSTRAINTS security\.idempotent_requests_campaign_id_fkey DEFERRED"),
        index(e, r"^INSERT INTO security\.idempotent_requests"),
        index(e, FIRST_LOCK[route]),
    ]
    chain.append(index(e, MEMBERSHIPS_U if route in ("assign", "change") else MEMBERSHIP_S))
    chain.append(index(e, ACCOUNT_S))
    chain.append(index(e, CAMPAIGN_KS if route == "assign" else CAMPAIGN_U))
    if route != "revoke":
        chain.append(index(e, ROLE_CATALOGUE_U))
    chain += [index(e, RECEIPT_U), index(e, FINAL)]
    writes = {
        "add": INSERT_MEMBERSHIP,
        "assign": INSERT_ROLE,
        "change": UPDATE_ROLE,
        "revoke": UPDATE_ROLE,
    }
    chain += [index(e, writes[route]), index(e, AUDIT_INSERT), index(e, RECEIPT_UPDATE)]
    first_lock = min(
        i for i, x in enumerate(e) if re.search(r"FOR (KEY SHARE|SHARE|UPDATE)|pg_advisory", x)
    )
    assert first_lock == chain[0] and chain[1] < chain[0] < chain[2], (route, e)
    assert chain[2:] == sorted(chain[2:]), (route, chain, e)
    assert e[-1] == "COMMIT"
    final = index(e, FINAL)
    assert not [
        x for x in e[final:] if re.search(r"\bFOR (KEY SHARE|SHARE|UPDATE|NO KEY UPDATE)\b", x)
    ]
    if route == "add":
        assert index(e, INSERT_MEMBERSHIP) < index(e, INSERT_ROLE)
    if route == "change":
        assert index(e, UPDATE_ROLE) < index(e, INSERT_ROLE)


@ALL_ROUTES
def test_an_unkeyed_route_takes_the_same_locks_without_a_key_lock_or_receipt(
    route: str, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    with Recorder(pooled) as recorded:
        response = call(pooled_factory, s, route, key=None)
    assert code(response) == STATUS[route]
    e = recorded.events
    assert not [x for x in e if re.search(r"pg_advisory|idempotent_requests|SET CONSTRAINTS", x)]
    assert index(e, FIRST_LOCK[route]) < index(e, FINAL) < index(e, AUDIT_INSERT)
    assert e[-1] == "COMMIT"


@ALL_ROUTES
@KEYED
def test_a_handler_that_forgets_to_finalize_is_a_sanitized_500_that_persists_nothing(
    route: str,
    keyed: bool,
    s: Scene,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = new_key() if keyed else None
    before = snapshot(s, key)
    monkeypatch.setattr(AuthorizationPlan, "finalize", lambda self, connection: None)
    response = call(pooled_factory, s, route, key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error"
    assert snapshot(s, key) == before and idle_in_transaction(s.w.engine) == 0


def _wrap(
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


def _steps(route: str, kind: str) -> list[str]:
    if kind == "receipt":
        return ["receipt"]
    return list(BUSINESS_STEPS[route] if kind == "business" else AUDIT_STEPS[route])


@ALL_ROUTES
@pytest.mark.parametrize(
    ("keyed", "kind"),
    ((True, "business"), (True, "audit"), (True, "receipt"), (False, "business"), (False, "audit")),
    ids=("keyed-business", "keyed-audit", "keyed-receipt", "unkeyed-business", "unkeyed-audit"),
)
def test_an_omitted_required_write_is_refused_at_commit_and_rolls_everything_back(
    route: str,
    keyed: bool,
    kind: str,
    s: Scene,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: each business, audit and (keyed) receipt write is owed by the locked state. A
    request that never runs one cannot commit: the guard refuses the incomplete plan (sanitized 500), everything
    rolls back, the key is reusable, the connection is clean. (Add and change have two business steps; the first
    is omitted here and the second by the next test.)"""
    step = _steps(route, kind)[0]
    key = new_key() if keyed else None
    before = snapshot(s, key)
    _wrap(monkeypatch, skip=(step,))
    response = call(pooled_factory, s, route, key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error", (step, response.text)
    assert snapshot(s, key) == before and idle_in_transaction(s.w.engine) == 0, step
    assert code(call(pooled_factory, s, route, key=key)) == STATUS[route]


@pytest.mark.parametrize(
    ("route", "step"),
    (
        ("add", "insert_initial_role"),
        ("add", "audit_role_created"),
        ("change", "insert_new_role"),
    ),
)
def test_the_second_business_or_audit_write_of_a_two_write_route_cannot_be_omitted_either(
    route: str,
    step: str,
    s: Scene,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = new_key()
    before = snapshot(s, key)
    _wrap(monkeypatch, skip=(step,))
    response = call(pooled_factory, s, route, key=key)
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert snapshot(s, key) == before


@ALL_ROUTES
@KEYED
@pytest.mark.parametrize("extra", ("business", "audit"))
def test_a_repeated_write_is_refused_and_the_whole_request_rolls_back(
    route: str,
    keyed: bool,
    extra: str,
    s: Scene,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: a second insert or update, or a second audit row, is a forbidden extra write. The
    second attempt is refused before the driver and nothing persists."""
    key = new_key() if keyed else None
    before = snapshot(s, key)
    step = _steps(route, extra)[0]
    pattern = {
        "revoke_role": UPDATE_ROLE,
        "revoke_old_role": UPDATE_ROLE,
        "insert_membership": INSERT_MEMBERSHIP,
        "insert_role": INSERT_ROLE,
        "audit_membership_created": AUDIT_INSERT,
        "audit_assigned": AUDIT_INSERT,
        "audit_changed": AUDIT_INSERT,
        "audit_revoked": AUDIT_INSERT,
    }[step]
    _wrap(monkeypatch, repeat=(step,))
    with Recorder(pooled) as recorded:
        response = call(pooled_factory, s, route, key=key)
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert len([e for e in recorded.events if re.search(pattern, e)]) == 1, (
        "the second never reached the driver"
    )
    assert snapshot(s, key) == before and idle_in_transaction(s.w.engine) == 0


@pytest.mark.parametrize("route", ("revoke", "change"))
@KEYED
def test_a_delegation_bound_to_the_role_is_closed_exactly_when_it_exists_and_omitting_it_cannot_commit(
    route: str,
    keyed: bool,
    s: Scene,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*route* and *mutation (test-side)*: revoking or changing a gm assignment closes the live reveal delegation
    bound to it (`EachLockedRow(complete=True)` over the delegation lock's evidence: required for each locked
    row). A request that skips the closure is refused at COMMIT and rolls back; the real request closes it with
    the documented end reason."""
    _, gm_row, delegation = add_open_delegation(s)
    key = new_key() if keyed else None
    step = "close_delegation" if route == "revoke" else "close_delegation_on_change"
    before = snapshot(s, key)
    _wrap(monkeypatch, skip=(step,))
    response = call(pooled_factory, s, route, key=key, target=gm_row, role=s.player)
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert snapshot(s, key) == before
    ok = call(pooled_factory, s, route, key=key, target=gm_row, role=s.player)
    assert code(ok) == STATUS[route], ok.text
    with s.w.engine.connect() as c:
        closed = c.execute(
            text(
                "SELECT revoked_at IS NOT NULL, end_reason FROM security.character_reveal_delegations "
                "WHERE character_reveal_delegation_id = :d"
            ),
            {"d": delegation},
        ).one()
    assert tuple(closed) == (True, "gm_role_revoked" if route == "revoke" else "gm_role_changed")


@pytest.mark.parametrize("route", ("revoke", "change"))
def test_a_role_without_a_delegation_runs_no_delegation_update(
    route: str, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    with Recorder(pooled) as recorded:
        assert code(call(pooled_factory, s, route, key=new_key())) == STATUS[route]
    assert not [e for e in recorded.events if "character_reveal_delegations SET" in e]


# --- competitors for the declared writes, the cascades, the foreign keys, the triggers ----------------------------------


def _competitors(s: Scene, route: str) -> list[tuple[str, str, Any]]:
    out: list[tuple[str, str, Any]] = [
        (
            "roles",
            "SELECT 1 FROM security.membership_roles WHERE membership_role_id = :id FOR UPDATE",
            s.m.manager_role,
        ),
        (
            "actor membership",
            "SELECT 1 FROM security.campaign_memberships WHERE campaign_membership_id = :id FOR UPDATE",
            s.m.manager_membership,
        ),
        (
            "actor account",
            "SELECT 1 FROM security.users WHERE user_id = :id FOR UPDATE",
            s.m.manager_user,
        ),
        (
            "campaign",
            "SELECT 1 FROM campaign.campaigns WHERE campaign_id = :id FOR UPDATE",
            s.w.campaign_id,
        ),
    ]
    if route in ("assign", "change"):
        out.append(
            (
                "target membership",
                "SELECT 1 FROM security.campaign_memberships WHERE campaign_membership_id = :id FOR UPDATE",
                s.target_membership,
            )
        )
    if route in ("add", "assign", "change"):
        role = s.player if route == "add" else s.observer
        out.append(
            ("catalogue role", "SELECT 1 FROM security.roles WHERE role_id = :id FOR UPDATE", role)
        )
    if route in ("add", "assign"):
        user = s.new_user if route == "add" else s.target_user
        out.append(
            ("target account", "SELECT 1 FROM security.users WHERE user_id = :id FOR UPDATE", user)
        )
    if route in ("revoke", "change"):
        out.append(
            (
                "target role",
                "SELECT 1 FROM security.membership_roles WHERE membership_role_id = :id FOR UPDATE",
                s.target_role,
            )
        )
    return out


@ALL_ROUTES
def test_the_locks_held_at_the_final_statement_exclude_every_conflicting_competitor(
    route: str, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*: at its final statement the request holds every row of its declaration. A competitor taking any of
    them `FOR UPDATE` (a revocation, an end, an account change, an archive, a role deactivation) queues behind it,
    blocked by the request's pid, and the request still commits with all of them queued: no post-finalization
    write, foreign-key re-check or COMMIT-time trigger can wait for one of these rows."""
    targets = _competitors(s, route)
    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread(route, lambda: call(pooled_factory, s, route, key=new_key()))
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            workers = [
                race.start(n, lambda c, q=q, i=i: c.execute(text(q), {"id": i}).all())
                for n, q, i in targets
            ]
            race.wait_blocked_by(gate, expected=len(targets))
            assert all(not x.done for x in workers)
            gate.release()
            response = request.wait("the request commits with its competitors queued")
            race.join_all()
    assert code(response) == STATUS[route], response.text
    assert all(x.error is None for x in workers)


def _hold_and_expect_wait(
    s: Scene, pooled_factory: Factory, route: str, sql: str, params: dict[str, Any], waits_in: str
) -> Any:
    with LockRace(s.w.engine) as race:
        hold = race.hold(lambda c: c.execute(text(sql), params).all())
        request = run_in_thread(route, lambda: call(pooled_factory, s, route, key=new_key()))
        race.wait_blocked_by(hold, expected=1)
        statement = waiting_statement(s.w.engine, hold.pid)
        assert waits_in in statement, statement
        assert not request.finished()
        hold.commit()
        response = request.wait("the request finishes once the holder commits")
        race.join_all()
    return response


@pytest.mark.parametrize(
    ("route", "action"),
    (("add", "created"), ("assign", "created"), ("change", "updated"), ("revoke", "updated")),
)
def test_the_audit_insert_waits_for_a_competitor_holding_its_action_row_and_then_commits(
    route: str, action: str, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, a reviewed *unlocked* foreign-key target (permitted residual wait): `audit.change_actions` is seed
    data nobody in the application locks; a holder of the action's row makes the audit insert wait, bounded by the
    holder, and the request then commits."""
    response = _hold_and_expect_wait(
        s,
        pooled_factory,
        route,
        "SELECT 1 FROM audit.change_actions WHERE code = :c FOR UPDATE",
        {"c": action},
        "audit.change_log",
    )
    assert code(response) == STATUS[route], response.text


def test_the_membership_insert_waits_for_a_competitor_holding_the_status_lookup_row(
    s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, a reviewed *unlocked* foreign-key target (permitted residual wait): the new membership's status FK
    takes `FOR KEY SHARE` on `security.membership_statuses` (seed data nobody updates)."""
    response = _hold_and_expect_wait(
        s,
        pooled_factory,
        "add",
        "SELECT 1 FROM security.membership_statuses WHERE code = 'active' FOR UPDATE",
        {},
        "campaign_memberships",
    )
    assert code(response) == 201, response.text


def test_a_competing_open_membership_for_the_same_account_is_a_unique_wait(
    s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, `ux_campaign_memberships_open`. A transaction that has inserted (and not committed) an open
    membership for the same account holds the campaign `FOR KEY SHARE` (its own foreign key). The add therefore
    queues one step earlier than the index, at its campaign `FOR UPDATE` (blocked by that pid, before any write),
    and never reaches a unique wait; once the competitor commits, its insert meets the committed row and is
    refused with the 409 it always had. Nothing of it persists. The declared `UniqueWait` is thus a wait the
    campaign lock pre-empts in the application; the index remains the backstop."""
    with LockRace(s.w.engine) as race:
        hold = race.hold(
            lambda c: c.execute(
                text(
                    "INSERT INTO security.campaign_memberships (campaign_id, user_id, membership_status_id, "
                    "joined_at) VALUES (:c, :u, (SELECT membership_status_id FROM "
                    "security.membership_statuses WHERE code = 'active'), now())"
                ),
                {"c": s.w.campaign_id, "u": s.new_user},
            )
        )
        request = run_in_thread("add", lambda: call(pooled_factory, s, "add", key=new_key()))
        race.wait_blocked_by(hold, expected=1)
        assert "FROM campaign.campaigns" in waiting_statement(s.w.engine, hold.pid)
        hold.commit()
        response = request.wait("the add finishes")
        race.join_all()
    assert code(response) == 409, response.text
    assert audits(s, "add_campaign_member") == []


def test_a_competing_active_assignment_of_the_same_role_is_a_unique_wait(
    s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, `ux_membership_roles_active`. A transaction holding an uncommitted insert of the same
    (membership, role) holds the membership `FOR KEY SHARE` (its foreign key), which conflicts with the
    assignment's `FOR UPDATE` on the target membership: the request queues there (blocked by that pid, before any
    write) and never reaches the index. Once the competitor commits, the insert meets the committed row and is
    refused (409); nothing persists."""
    with LockRace(s.w.engine) as race:
        hold = race.hold(
            lambda c: c.execute(
                text(
                    "INSERT INTO security.membership_roles (campaign_membership_id, role_id) VALUES (:m, :r)"
                ),
                {"m": s.target_membership, "r": s.observer},
            )
        )
        request = run_in_thread("assign", lambda: call(pooled_factory, s, "assign", key=new_key()))
        race.wait_blocked_by(hold, expected=1)
        assert "FROM security.campaign_memberships" in waiting_statement(s.w.engine, hold.pid)
        hold.commit()
        response = request.wait("the assignment finishes")
        race.join_all()
    assert code(response) == 409, response.text
    assert audits(s, "assign_membership_role") == []


def test_an_update_leaving_the_active_assignment_index_never_waits_for_a_competing_insert(
    s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, `ux_membership_roles_active`: the revoke's `UPDATE` leaves the partial index, so it takes no unique
    wait. A competitor inserting the same (membership, role) while the request is parked at its audit insert (its
    update done, uncommitted) queues behind *the request* (blocked by its pid); the request finishes while the
    competitor is still queued, then the competitor completes (the key is free)."""
    with StatementGate(pooled, AUDIT_INSERT) as gate:
        request = run_in_thread("revoke", lambda: call(pooled_factory, s, "revoke", key=new_key()))
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            competitor = race.start(
                "insert",
                lambda c: c.execute(
                    text(
                        "INSERT INTO security.membership_roles (campaign_membership_id, role_id) VALUES (:m, :r)"
                    ),
                    {"m": s.target_membership, "r": s.player},
                ),
            )
            race.wait_blocked_by(gate, expected=1)
            assert "membership_roles" in waiting_statement(s.w.engine, gate.pid)
            gate.release()
            response = request.wait("the revoke finishes while the competitor is queued")
            race.join_all()
    assert code(response) == 200 and competitor.error is None


def test_a_delegation_closure_leaving_the_live_index_never_waits_for_a_competing_insert(
    s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, `ux_character_reveal_delegations_live`: closing the delegation leaves the partial index. A
    competitor inserting a live delegation for the same grantee queues behind the request at its audit insert
    (the closure done, uncommitted) and completes after it commits."""
    membership, gm_row, _ = add_open_delegation(s)
    with StatementGate(pooled, AUDIT_INSERT) as gate:
        request = run_in_thread(
            "revoke", lambda: call(pooled_factory, s, "revoke", key=new_key(), target=gm_row)
        )
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            competitor = race.start(
                "insert",
                lambda c: c.execute(
                    text(
                        "INSERT INTO security.character_reveal_delegations (campaign_id, "
                        "grantee_campaign_membership_id, gm_membership_role_id, granted_by_membership_id, "
                        "reason) VALUES (:c, :g, :r, :a, 'x')"
                    ),
                    {
                        "c": s.w.campaign_id,
                        "g": membership,
                        "r": gm_row,
                        "a": s.m.keeper_membership,
                    },
                ),
            )
            race.wait_blocked_by(gate, expected=1)
            assert "character_reveal_delegations" in waiting_statement(s.w.engine, gate.pid)
            gate.release()
            response = request.wait("the revoke finishes while the competitor is queued")
            race.join_all()
    assert code(response) == 200 and competitor.error is None


# --- concurrent role changes and membership end --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second"), (("revoke", "change"), ("change", "revoke"), ("revoke", "revoke"))
)
def test_two_requests_on_the_same_assignment_serialize_in_both_orders_without_a_deadlock(
    first: str, second: str, s: Scene, pooled2: Engine, pooled2_factory: Factory
) -> None:
    """*race*: the first request is parked at its final statement holding the target role `FOR UPDATE`; the second
    queues at its own first lock on that row (blocked by the first's pid). The first commits; the second then
    finds the assignment revoked: a revoke is the documented no-op (200, no second audit row), a change is
    refused (409 not active)."""
    deadlocks = deadlock_count(s.w.engine)
    with StatementGate(pooled2, FINAL) as gate:
        one = run_in_thread(first, lambda: call(pooled2_factory, s, first, key=new_key()))
        gate.wait_reached()
        assert gate.pid is not None
        two = run_in_thread(second, lambda: call(pooled2_factory, s, second, key=new_key()))
        with LockRace(s.w.engine) as race:
            race.wait_blocked_by(gate, expected=1)
        assert "membership_roles" in waiting_statement(s.w.engine, gate.pid)
        gate.release()
        done_one = one.wait("the first finishes")
        done_two = two.wait("the second finishes")
    assert code(done_one) == STATUS[first]
    assert code(done_two) == (200 if second == "revoke" else 409), done_two.text
    assert len(audits(s, "revoke_membership_role")) + len(audits(s, "change_membership_role")) == 1
    assert wait_for_deadlock_count(s.w.engine, deadlocks) == deadlocks


@pytest.mark.parametrize("route", ("assign", "revoke"))
def test_an_end_of_the_target_membership_and_a_role_route_serialize_without_a_deadlock(
    route: str, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, against the legacy `end_campaign_membership` (still a direct command, S5-E3). The request is parked
    at its final statement holding the target's rows; the end queues behind it (blocked by the request's pid) and
    commits after the request. Run afterwards, the route finds the membership ended. No deadlock."""
    deadlocks = deadlock_count(s.w.engine)

    def end(c: Any) -> Any:
        return end_campaign_membership(
            c,
            campaign_membership_id=s.target_membership,
            campaign_id=s.w.campaign_id,
            ended_by_membership_id=s.m.keeper_membership,
        )

    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread(route, lambda: call(pooled_factory, s, route, key=new_key()))
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            ender = race.start("end", end)
            race.wait_blocked_by(gate, expected=1)
            assert not ender.done
            gate.release()
            response = request.wait("the request finishes")
            race.join_all()
    assert code(response) == STATUS[route], response.text
    assert ender.error is None
    after = call(pooled_factory, s, route, key=new_key())
    assert code(after) in ((409, 404) if route == "assign" else (200, 404, 409))
    assert wait_for_deadlock_count(s.w.engine, deadlocks) == deadlocks


# --- retention backstop -------------------------------------------------------------------------------------------------


def test_a_commit_time_retention_failure_is_a_500_that_persists_nothing_and_leaves_the_key_reusable(
    s: Scene, pooled: Engine, pooled_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """*mutation (test-side)*: the pre-check that makes the deferred trigger unreachable in the application is
    defeated, so the last manager's revocation passes it and the trigger refuses at COMMIT (it re-acquires the
    campaign lock the request holds). Expected: a server error, the assignment still active, no audit row and no
    receipt; the key is reusable and, with the pre-check back, gets the classified 400."""
    _remove_keeper(s)
    from dnd_ai.commands import membership_role_plans as plans

    monkeypatch.setattr(plans, "_require_manager_survives", lambda *a, **k: None)
    key = new_key()
    before = snapshot(s, key)
    response = call(pooled_factory, s, "revoke", key=key, target=s.m.manager_role)
    monkeypatch.undo()
    assert code(response) >= 500, response.text
    assert snapshot(s, key) == before and idle_in_transaction(s.w.engine) == 0
    assert code(call(pooled_factory, s, "revoke", key=key, target=s.m.manager_role)) == 400


# --- the declarations hold against the live catalogue ----------------------------------------------------------------------


def test_the_declarations_hold_against_the_live_catalogue(w: World) -> None:
    """The S1 catalogue helper checks every assumption a declaration makes about the database (triggers pinned by
    function-source hash, unique waits, FK match type and order, defaults, CHECK expressions). An empty list is the
    only passing answer."""
    from dnd_ai.commands import membership_role_plans as p
    from tests.r01_pre_write_catalogue import check_declaration

    problems: list[str] = []
    with w.engine.connect() as connection:
        for name, d in (
            ("add", p.ADD_DECLARATIONS),
            ("assign", p.ASSIGN_DECLARATIONS),
            ("change", p.CHANGE_DECLARATIONS),
            ("revoke", p.REVOKE_DECLARATIONS),
        ):
            for kind, decl in (("reserved", d.reserved), ("unkeyed", d.unkeyed)):
                assert decl is not None
                problems += [f"{name}/{kind}: {x}" for x in check_declaration(connection, decl)]
    assert problems == []
