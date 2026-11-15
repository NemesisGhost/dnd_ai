# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E2 combined role/membership lock-order correction C1-C4: unconditional application-path regressions.

Design: docs/R01_S5E2_LOCK_ORDER_CORRECTION_DESIGN_2026-11-15.md (cases A-I, section 5). Every case drives real
routes over real connections. One request is parked at a named statement (before it executes, holding what it took
earlier); the competitor is started and observed queued behind the parked backend's pid; then the parked request is
released. Each case asserts, unconditionally and in this order:

1. the gate was reached (a gated statement that does not exist in the tree under test is an *incompatible gate*,
   reported as such, never read as an absence of a cycle);
2. the competitor's direct blockers were exactly the parked pid and the waiting statement matches an exact regex
   (or, where the design says the competitor must not wait, that it did not);
3. no driver exception on any statement (SQLSTATE and statement are in the message: `40P01` is a deadlock);
4. the database deadlock counter did not move (read after the pool's backends have exited);
5. every request's exact status and error code;
6. the final role, delegation and audit rows; a refused request left nothing behind (no row, no audit row).
"""

import json
import os
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import OperationalError

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.domain.authorization import install_authorization_guard
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixture by name
    World,
    code,
    error_of,
    w,
)
from tests.factories import make_campaign_membership, make_user, oidc_principal, system_role_id
from tests.http_race_support import (
    StatementGate,
    activity_report,
    run_in_thread,
    sessions_blocked_by,
)
from tests.r01_s5d_support import make_managers

pytestmark = pytest.mark.database

#: How long a request may take, and a parked request is held. Generous on purpose: the four-shard runner puts four
#: PostgreSQL servers and four test processes on one machine, and the shared `PATIENCE` (15 s) is a hang
#: detector, not a timing assumption these cases may depend on (a held request that times out *releases itself*).
PATIENCE = 90.0

LOW = "00000000-0000-4000-8000-0000"
HIGH = "ffffffff-ffff-4fff-bfff-ffff"

# -- statement patterns (SQLAlchemy Core text, whitespace-normalised) ------------------------------------------
#: A role-class lock of the reveal-delegation grant: the owner row (`FOR SHARE OF mr`) or the gm rows (`FOR UPDATE OF mr`).
GRANT_ROLE_LOCK = (
    r"FROM security\.membership_roles mr JOIN security\.roles r ON r\.role_id = mr\.role_id "
    r".*FOR (SHARE|UPDATE) OF mr$"
)
GRANT_GRANTEE_NKU = (
    r"FROM security\.campaign_memberships WHERE campaign_membership_id = \S+ FOR NO KEY UPDATE$"
)
GRANT_DELEGATIONS = (
    r"FROM security\.character_reveal_delegations WHERE grantee_campaign_membership_id"
)
#: The role routes' delegation lock: the statement after their role-class statement.
ROUTE_DELEGATIONS = (
    r"FROM security\.character_reveal_delegations WHERE security\.character_reveal_delegations\."
    r"gm_membership_role_id = "
)
TRANSFER_EXPIRED = r"expires_at IS NOT NULL AND \S*expires_at <= (pg_catalog\.)?clock_timestamp\(\).* FOR NO KEY UPDATE$"
TRANSFER_LIVE = r"expires_at > (pg_catalog\.)?clock_timestamp\(\)\).* FOR KEY SHARE$"
#: Any membership-class lock of assign, change and transfer (a Core `select` of the membership id).
MEMBERSHIP_LOCK = (
    r"SELECT security\.campaign_memberships\.campaign_membership_id FROM security\.campaign_memberships "
    r"WHERE .* FOR (SHARE|UPDATE)$"
)
ACTOR_ACCOUNT = r"SELECT security\.users\.user_id FROM security\.users WHERE security\.users\.user_id = \S+ FOR SHARE$"
END_ACTOR_KEY_SHARE = (
    r"FROM security\.campaign_memberships WHERE campaign_membership_id = \S+ FOR KEY SHARE$"
)


def tag(side: str, suffix: str) -> uuid.UUID:
    """An id ordered below (`low`) or above (`high`) every random v4 id; `suffix` orders ids of one side, and six
    random digits keep ids unique across tests that share a database (a leftover row must never collide)."""
    return uuid.UUID((LOW if side == "low" else HIGH) + suffix + uuid.uuid4().hex[:6])


# -- harness ----------------------------------------------------------------------------------------------------


class NthGate(StatementGate):
    """`StatementGate` that stops the n-th matching statement (the grant's *second* role lock, whichever it is), and
    holds it for `PATIENCE` seconds instead of the shared gate's 15."""

    def __init__(self, engine: Engine, pattern: str, n: int = 1) -> None:
        super().__init__(engine, pattern)
        self.n = n
        self.seen = 0

    def _hook(self, conn: Any, cursor: Any, statement: Any, *rest: Any) -> None:
        normalised = " ".join(str(statement).split())
        if self._fired or not self.pattern.search(normalised):
            return
        self.seen += 1
        if self.seen < self.n:
            return
        self._fired = True
        self.pid = conn.connection.driver_connection.info.backend_pid
        self.matched = normalised[:150]
        self.reached_at = time.monotonic()
        self.reached.set()
        self.resume.wait(PATIENCE)


def finish(request: Any, why: str) -> Any:
    """`Request.wait` with this module's patience."""
    assert request.done.wait(PATIENCE), f"{request.name} did not finish: {why}"
    assert request.error is None, f"{request.name} raised {request.error!r}"
    return request.result


@dataclass
class Pool:
    engine: Engine
    failures: list[tuple[str | None, str]] = field(default_factory=list)
    pids: list[int] = field(default_factory=list)


@pytest.fixture
def pool(postgres_engine: Engine) -> Any:
    engine = create_engine(
        postgres_engine.url, pool_size=8, max_overflow=0, isolation_level="READ COMMITTED"
    )
    install_authorization_guard(engine)
    p = Pool(engine)

    def on_error(context: Any) -> None:
        original = context.original_exception
        p.failures.append(
            (
                getattr(original, "sqlstate", None),
                " ".join(str(context.statement or "").split())[:150],
            )
        )

    def on_connect(dbapi: Any, _record: Any) -> None:
        p.pids.append(dbapi.info.backend_pid)

    event.listen(engine, "handle_error", on_error)
    event.listen(engine, "connect", on_connect)
    try:
        yield p
    finally:
        engine.dispose()


def client_for(p: Pool, user_id: uuid.UUID) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: p.engine
    app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
    return TestClient(app, raise_server_exceptions=False)


def deadlocks_now(admin: Engine) -> int:
    with admin.connect() as c:
        c.execute(text("SELECT pg_stat_clear_snapshot()"))
        return int(
            c.execute(
                text("SELECT deadlocks FROM pg_stat_database WHERE datname = current_database()")
            ).scalar_one()
        )


def settled_deadlock_delta(admin: Engine, p: Pool, before: int) -> int:
    """Dispose the pool, wait until each of its backends has exited (their statistics are then flushed), read."""
    p.engine.dispose()
    deadline = time.monotonic() + PATIENCE
    while time.monotonic() < deadline:
        with admin.connect() as c:
            alive = c.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE pid = ANY(:p)"), {"p": p.pids}
            ).scalar_one()
        if alive == 0:
            break
        time.sleep(0.05)
    return deadlocks_now(admin) - before


def blocked_view(admin: Engine, holder: int) -> list[dict[str, Any]]:
    with admin.connect() as c:
        return [
            dict(r._mapping)
            for r in c.execute(
                text(
                    r"SELECT pid, pg_blocking_pids(pid) AS blockers, "
                    r"regexp_replace(query, '\s+', ' ', 'g') AS query "
                    "FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND :p = ANY(pg_blocking_pids(pid))"
                ),
                {"p": holder},
            )
        ]


def lock_waiters(admin: Engine) -> int:
    with admin.connect() as c:
        return int(
            c.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            ).scalar_one()
        )


@dataclass
class Outcome:
    results: dict[str, Any]
    blocked: list[dict[str, Any]] | None
    gate_statement: str | None
    failures: list[tuple[str | None, str]]
    deadlock_delta: int

    def __post_init__(self) -> None:
        """With `LO_REPORT=<file>` set, every outcome is appended as one JSON line (evidence; never an assertion)."""
        report = os.environ.get("LO_REPORT")
        if report:
            with open(report, "a", encoding="utf-8") as handle:
                current = os.environ.get("PYTEST_CURRENT_TEST", "").split(" ")[0]
                record = {"test": current, **json.loads(self.summary())}
                handle.write(json.dumps(record) + chr(10))

    def status(self, name: str) -> tuple[int, str | None]:
        r = self.results[name]
        return (code(r), error_of(r))

    def summary(self) -> str:
        return json.dumps(
            {
                "statuses": {n: (code(r), error_of(r)) for n, r in self.results.items()},
                "blocked": self.blocked,
                "gate": self.gate_statement,
                "driver_failures": self.failures,
                "deadlock_delta": self.deadlock_delta,
            },
            default=str,
        )


def wait_blocked_or_finished(
    admin: Engine, gate: StatementGate, request: Any
) -> list[dict[str, Any]] | None:
    assert gate.pid is not None
    deadline = time.monotonic() + PATIENCE
    while time.monotonic() < deadline:
        if sessions_blocked_by(admin, gate.pid) >= 1:
            return blocked_view(admin, gate.pid)
        if request.finished():
            return None
        time.sleep(0.02)
    raise AssertionError(
        f"the competitor neither queued behind pid {gate.pid} nor finished\n{activity_report(admin)}"
    )


def race(
    w: World,
    p: Pool,
    *,
    gate_pattern: str,
    parked: Callable[[], Any],
    second: Callable[[], Any],
    nth: int = 1,
) -> Outcome:
    """Park `parked` at the `nth` statement matching `gate_pattern`; start `second`; observe; release; collect."""
    before = deadlocks_now(w.engine)
    with NthGate(p.engine, gate_pattern, nth) as gate:
        first = run_in_thread("parked", parked)
        if not gate.reached.wait(PATIENCE):
            gate.release()
            finish(first, "parked request finishes")
            raise AssertionError(
                "INCOMPATIBLE GATE (not a deadlock finding): the statement "
                f"{gate_pattern!r} never executed in this tree; the parked request answered "
                f"{first.describe()}"
            )
        later = run_in_thread("second", second)
        blocked = wait_blocked_or_finished(w.engine, gate, later)
        statement = gate.matched
        gate.release()
        results = {
            "parked": finish(first, "parked finishes"),
            "second": finish(later, "second finishes"),
        }
    delta = settled_deadlock_delta(w.engine, p, before)
    return Outcome(results, blocked, statement, list(p.failures), delta)


def assert_clean(o: Outcome) -> None:
    assert not o.failures, f"driver exceptions (40P01 = deadlock): {o.summary()}"
    assert o.deadlock_delta == 0, f"the deadlock counter moved: {o.summary()}"


def assert_waited_on_parked(o: Outcome, waiting: str) -> None:
    """The competitor queued, its only direct blocker was the parked backend, and it waited on `waiting`."""
    assert o.blocked, f"the competitor never queued behind the parked request: {o.summary()}"
    for row in o.blocked:
        assert len(row["blockers"]) == 1, f"more than one blocker: {o.summary()}"
        assert re.search(waiting, row["query"]), (
            f"waiting statement {row['query']!r} !~ {waiting!r}"
        )


def rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(sql), params)]


def insert_role(c: Any, rid: uuid.UUID | None, membership: uuid.UUID, role: uuid.UUID) -> uuid.UUID:
    rid = rid or uuid.uuid4()
    c.execute(
        text(
            "INSERT INTO security.membership_roles (membership_role_id, campaign_membership_id, role_id) "
            "VALUES (:r, :m, :role)"
        ),
        {"r": rid, "m": membership, "role": role},
    )
    return rid


ROLES = (
    "SELECT mr.membership_role_id AS id, r.code, mr.campaign_membership_id AS membership, "
    "mr.revoked_at IS NOT NULL AS revoked FROM security.membership_roles mr "
    "JOIN security.roles r ON r.role_id = mr.role_id WHERE mr.campaign_membership_id = ANY(:ms) "
    "ORDER BY mr.campaign_membership_id, mr.membership_role_id"
)
DELEGATIONS = (
    "SELECT grantee_campaign_membership_id AS grantee, gm_membership_role_id AS gm, "
    "revoked_at IS NOT NULL AS revoked FROM security.character_reveal_delegations "
    "WHERE campaign_id = :c ORDER BY created_at, character_reveal_delegation_id"
)
AUDITS = (
    "SELECT command_name, record_id FROM audit.change_log WHERE command_name = ANY(:names) "
    "AND record_id = ANY(:ids) ORDER BY command_name"
)


def live_roles(engine: Engine, ms: list[uuid.UUID]) -> dict[str, list[uuid.UUID]]:
    out: dict[str, list[uuid.UUID]] = {}
    for r in rows(engine, ROLES, ms=ms):
        if not r["revoked"]:
            out.setdefault(r["code"], []).append(r["id"])
    return out


def post(
    p: Pool, user: uuid.UUID, path: str, body: dict[str, Any] | None = None, **headers: str
) -> Any:
    with client_for(p, user) as client:
        return client.post(path, json=body if body is not None else {}, headers=headers or None)


# -- scenes ----------------------------------------------------------------------------------------------------


@dataclass
class Cast:
    """The owner C, the second member X (and optionally a third B), their membership and role ids."""

    c_user: uuid.UUID
    c_m: uuid.UUID
    x_user: uuid.UUID
    x_m: uuid.UUID
    ids: dict[str, uuid.UUID]


def cast_two(w: World, *, roles: dict[str, tuple[str, str, str]], label: str) -> Cast:
    """`roles`: name -> (member 'c'|'x', system role code, id suffix with 'low:'/'high:' side)."""
    with w.engine.begin() as c:
        c_user, x_user = make_user(c, f"{label} C"), make_user(c, f"{label} X")
        c_m = make_campaign_membership(c, w.campaign_id, c_user)
        x_m = make_campaign_membership(c, w.campaign_id, x_user)
        ids: dict[str, uuid.UUID] = {}
        for name, (who, role_code, spec) in roles.items():
            side, suffix = spec.split(":")
            ids[name] = insert_role(
                c, tag(side, suffix), c_m if who == "c" else x_m, system_role_id(c, role_code)
            )
    return Cast(c_user, c_m, x_user, x_m, ids)


# ======================================================================================================================
# A. F-4a / F-4b: the reveal-delegation grant against the S5-E2 change and revoke routes
# ======================================================================================================================


@pytest.mark.parametrize(
    "arrival", ("grant_parked_at_its_second_role_lock", "route_parked_after_its_role_statement")
)
@pytest.mark.parametrize("order", ("gX_below_rC", "rC_below_gX"))
@pytest.mark.parametrize("route", ("revoke", "change"))
def test_a_grant_against_a_role_route_never_waits_in_a_cycle(
    route: str, order: str, arrival: str, w: World, pool: Pool
) -> None:
    """Owner C grants reveal authority to X; X (a manager who also holds `gm`) revokes or changes C's owner row.
    Both orders of the two row ids; the grant parked at its second role lock, or the route parked after its one
    ordered role statement (both rows held `FOR UPDATE`)."""
    m = make_managers(w.engine, w.campaign_id, label="A")
    g_side, r_side = ("low", "high") if order == "gX_below_rC" else ("high", "low")
    g_x, r_c = tag(g_side, "a1"), tag(r_side, "c1")
    with w.engine.begin() as c:
        c_user = make_user(c, "A owner C")
        c_m = make_campaign_membership(c, w.campaign_id, c_user)
        insert_role(c, g_x, m.manager_membership, system_role_id(c, "gm"))
        insert_role(c, r_c, c_m, system_role_id(c, "campaign_owner"))
        observer = system_role_id(c, "observer")

    def grant() -> Any:
        return post(
            pool,
            c_user,
            f"{w.base}/reveal-delegations",
            {"grantee_campaign_membership_id": str(m.manager_membership), "reason": "a"},
        )

    def role_route() -> Any:
        if route == "revoke":
            return post(pool, m.manager_user, f"{w.base}/memberships/roles/{r_c}/revoke")
        return post(
            pool,
            m.manager_user,
            f"{w.base}/memberships/roles/{r_c}/change",
            {"new_role_id": str(observer)},
        )

    if arrival.startswith("grant"):
        o = race(
            w,
            pool,
            gate_pattern=GRANT_ROLE_LOCK,
            nth=2,
            parked=grant,
            second=role_route,
        )
        assert_clean(o)
        assert_waited_on_parked(o, r"membership_roles")
        assert o.status("parked") == (200, None), o.summary()
        assert o.status("second") == (200 if route == "revoke" else 201, None), o.summary()
        assert [d["gm"] for d in rows(w.engine, DELEGATIONS, c=w.campaign_id)] == [g_x]
    else:
        o = race(w, pool, gate_pattern=ROUTE_DELEGATIONS, parked=role_route, second=grant)
        assert_clean(o)
        assert_waited_on_parked(o, r"membership_roles")
        assert o.status("parked") == (200 if route == "revoke" else 201, None), o.summary()
        assert o.status("second") == (403, "campaign_owner_required"), o.summary()
        assert rows(w.engine, DELEGATIONS, c=w.campaign_id) == []
    live = live_roles(w.engine, [c_m])
    assert r_c not in live.get("campaign_owner", []), "C's owner row was revoked or replaced"
    assert ("observer" in live) == (route == "change")


# ======================================================================================================================
# B. T-4: ownership transfer against a role route that reaches the same rows from the other side
# ======================================================================================================================

TBD = (
    "TBD",
    "TBD",
)  # calibration marker: an assertion naming this fails with the observed statuses


def transfer_body(m: uuid.UUID, relinquish: bool) -> dict[str, Any]:
    return {"target_campaign_membership_id": str(m), "relinquish_own_ownership": relinquish}


@pytest.mark.parametrize(
    "arrival",
    ("transfer_parked_at_its_first_recipient_lock", "route_parked_after_its_role_statement"),
)
@pytest.mark.parametrize("order", ("rA_below_rC", "rC_below_rA"))
@pytest.mark.parametrize(
    "variant", ("C_revokes_the_recipients_row", "A_changes_the_transferors_row")
)
def test_b_a_transfer_against_a_role_route_never_waits_in_a_cycle(
    variant: str, order: str, arrival: str, w: World, pool: Pool
) -> None:
    """Owners C and A; C transfers to A relinquishing. Either C revokes A's owner row, or A changes C's owner row."""
    make_managers(w.engine, w.campaign_id, label="B")
    a_side, c_side = ("low", "high") if order == "rA_below_rC" else ("high", "low")
    r_a, r_c = tag(a_side, "b1"), tag(c_side, "c1")
    with w.engine.begin() as c:
        c_user, a_user = make_user(c, "B C"), make_user(c, "B A")
        c_m = make_campaign_membership(c, w.campaign_id, c_user)
        a_m = make_campaign_membership(c, w.campaign_id, a_user)
        owner = system_role_id(c, "campaign_owner")
        insert_role(c, r_c, c_m, owner)
        insert_role(c, r_a, a_m, owner)
        observer = system_role_id(c, "observer")

    def transfer() -> Any:
        return post(pool, c_user, f"{w.base}/ownership-transfer", transfer_body(a_m, True))

    def route() -> Any:
        if variant == "C_revokes_the_recipients_row":
            return post(pool, c_user, f"{w.base}/memberships/roles/{r_a}/revoke")
        return post(
            pool, a_user, f"{w.base}/memberships/roles/{r_c}/change", {"new_role_id": str(observer)}
        )

    if arrival.startswith("transfer"):
        o = race(w, pool, gate_pattern=TRANSFER_EXPIRED, parked=transfer, second=route)
    else:
        o = race(w, pool, gate_pattern=ROUTE_DELEGATIONS, parked=route, second=transfer)
    assert_clean(o)
    expected = EXPECTED_B[(variant, order, arrival)]
    got = (o.status("parked"), o.status("second"), o.blocked is not None)
    assert got == expected, o.summary()
    live = live_roles(w.engine, [c_m, a_m])
    assert len(live.get("campaign_owner", [])) >= 1, f"the campaign lost its last owner: {live}"


OK200, OK201 = (200, None), (201, None)
NOT_OWNER = (403, "campaign_owner_required")
_T, _R = "transfer_parked_at_its_first_recipient_lock", "route_parked_after_its_role_statement"
#: (variant, order, arrival) -> (the parked request, the competitor, whether the competitor queued behind the parked
#: backend). Derived from the lock order, then checked against the run. A request that loses its authority to the
#: other request's write is refused after the wait (403), never deadlocked.
EXPECTED_B: dict[tuple[str, str, str], Any] = {
    # C revokes A's owner row. A below C: the transfer holds no row yet when it parks, so the revoke is not queued
    # and the transfer then replaces the revoked row; C below A: the transfer holds C's row and the revoke queues,
    # then C (no longer an owner) is refused.
    ("C_revokes_the_recipients_row", "rA_below_rC", _T): (OK200, OK200, False),
    ("C_revokes_the_recipients_row", "rA_below_rC", _R): (OK200, OK200, True),
    ("C_revokes_the_recipients_row", "rC_below_rA", _T): (OK200, (403, "forbidden"), True),
    ("C_revokes_the_recipients_row", "rC_below_rA", _R): (OK200, OK200, True),
    # A changes C's owner row; the same two orders.
    ("A_changes_the_transferors_row", "rA_below_rC", _T): (NOT_OWNER, OK201, False),
    ("A_changes_the_transferors_row", "rA_below_rC", _R): (OK201, NOT_OWNER, True),
    ("A_changes_the_transferors_row", "rC_below_rA", _T): (OK200, (409, "conflict"), True),
    ("A_changes_the_transferors_row", "rC_below_rA", _R): (OK201, NOT_OWNER, True),
}


# ======================================================================================================================
# C. O-1: the grant (owner row S, then gm row U) against a transfer to the grantor whose owner row expires
# ======================================================================================================================


def wait_expired(engine: Engine, role: uuid.UUID) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        gone = rows(
            engine,
            "SELECT expires_at <= clock_timestamp() AS gone FROM security.membership_roles "
            "WHERE membership_role_id = :r",
            r=role,
        )[0]["gone"]
        if gone:
            return
        time.sleep(0.05)
    raise AssertionError(f"role {role} did not expire")


@pytest.mark.parametrize("owner_row", ("expiring", "live_control"))
@pytest.mark.parametrize("order", ("gX_below_rC", "rC_below_gX"))
def test_c_a_grant_and_a_transfer_to_the_grantor_never_wait_in_a_cycle(
    order: str, owner_row: str, w: World, pool: Pool
) -> None:
    """C is the grantor; X is the grantee (it holds `gm`) and the transferring owner; the transfer hands ownership
    to C. The grant is parked at its second role lock. When C's owner row has expired the transfer must take it
    `FOR NO KEY UPDATE` (to close it), which conflicts with the grant's `FOR SHARE`."""
    make_managers(w.engine, w.campaign_id, label="C")
    g_side, r_side = ("low", "high") if order == "gX_below_rC" else ("high", "low")
    g_x, r_c = tag(g_side, "a1"), tag(r_side, "c1")
    with w.engine.begin() as c:
        owner, gm = system_role_id(c, "campaign_owner"), system_role_id(c, "gm")
        c_user, x_user = make_user(c, "C C"), make_user(c, "C X")
        c_m = make_campaign_membership(c, w.campaign_id, c_user)
        x_m = make_campaign_membership(c, w.campaign_id, x_user)
        insert_role(c, r_c, c_m, owner)
        insert_role(c, tag("low", "a2"), x_m, owner)
        insert_role(c, g_x, x_m, gm)
        if owner_row == "expiring":
            c.execute(
                text(
                    "UPDATE security.membership_roles "
                    "SET expires_at = clock_timestamp() + interval '1500 milliseconds' "
                    "WHERE membership_role_id = :r"
                ),
                {"r": r_c},
            )

    def grant() -> Any:
        return post(
            pool,
            c_user,
            f"{w.base}/reveal-delegations",
            {"grantee_campaign_membership_id": str(x_m), "reason": "c"},
        )

    def transfer() -> Any:
        if (
            owner_row == "expiring"
        ):  # start only once C's row is past its expiry by the database clock
            wait_expired(w.engine, r_c)
        return post(pool, x_user, f"{w.base}/ownership-transfer", transfer_body(c_m, False))

    o = race(w, pool, gate_pattern=GRANT_ROLE_LOCK, nth=2, parked=grant, second=transfer)
    assert_clean(o)
    assert o.status("second") == OK200, o.summary()
    if owner_row == "expiring":
        assert o.status("parked") == NOT_OWNER, (
            o.summary()
        )  # DEF-013: the grantor's row lapsed during the wait
        assert rows(w.engine, DELEGATIONS, c=w.campaign_id) == []
        owners = live_roles(w.engine, [c_m]).get("campaign_owner", [])
        assert len(owners) == 1 and r_c not in owners, "the expired row was closed and replaced"
    else:
        assert o.status("parked") == OK200, o.summary()
        assert [d["gm"] for d in rows(w.engine, DELEGATIONS, c=w.campaign_id)] == [g_x]


# ======================================================================================================================
# D. Three parties: grant C->X, transfer X->B, and B revoking C's owner row
# ======================================================================================================================


def settle(admin: Engine, gate: StatementGate | None, request: Any, waiting_before: int) -> None:
    """Until the request is stopped at its gate, finished, or queued behind a lock (a new Lock waiter)."""
    deadline = time.monotonic() + PATIENCE
    while time.monotonic() < deadline:
        if (gate is not None and gate.reached.is_set()) or request.finished():
            return
        if lock_waiters(admin) > waiting_before:
            return
        time.sleep(0.02)
    raise AssertionError(
        f"the request neither stopped, queued nor finished\n{activity_report(admin)}"
    )


@pytest.mark.parametrize("config", ("C_row_highest", "C_row_lowest"))
def test_d_three_parties_never_wait_in_a_cycle(config: str, w: World, pool: Pool) -> None:
    """Grant C->X (owner row, then X's gm row), transfer X->B (X's rows, then B's owner row), and B revoking C's
    owner row (B's rows and the target, one ordered statement). Each request is stopped where it holds what it has
    and the next is started; the grant is released last. A cycle needs every party to go against the order."""
    make_managers(w.engine, w.campaign_id, label="D")
    hi = config == "C_row_highest"
    g_x, r_x, r_b = tag("low", "a1"), tag("low", "a2"), tag("low", "b1")
    r_c = tag("high", "c1") if hi else tag("low", "01")
    with w.engine.begin() as c:
        owner, gm = system_role_id(c, "campaign_owner"), system_role_id(c, "gm")
        c_user, x_user, b_user = make_user(c, "D C"), make_user(c, "D X"), make_user(c, "D B")
        c_m = make_campaign_membership(c, w.campaign_id, c_user)
        x_m = make_campaign_membership(c, w.campaign_id, x_user)
        b_m = make_campaign_membership(c, w.campaign_id, b_user)
        insert_role(c, r_c, c_m, owner)
        insert_role(c, r_x, x_m, owner)
        insert_role(c, g_x, x_m, gm)
        insert_role(c, r_b, b_m, owner)
    before = deadlocks_now(w.engine)
    with (
        NthGate(pool.engine, GRANT_ROLE_LOCK, 2) as g_grant,
        NthGate(pool.engine, TRANSFER_EXPIRED) as g_tr,
    ):
        grant = run_in_thread(
            "grant",
            lambda: post(
                pool,
                c_user,
                f"{w.base}/reveal-delegations",
                {"grantee_campaign_membership_id": str(x_m), "reason": "d"},
            ),
        )
        assert g_grant.reached.wait(PATIENCE), "INCOMPATIBLE GATE: the grant's second role lock"
        waiting = lock_waiters(w.engine)
        transfer = run_in_thread(
            "transfer",
            lambda: post(pool, x_user, f"{w.base}/ownership-transfer", transfer_body(b_m, False)),
        )
        settle(w.engine, g_tr, transfer, waiting)
        waiting = lock_waiters(w.engine)
        revoke = run_in_thread(
            "revoke", lambda: post(pool, b_user, f"{w.base}/memberships/roles/{r_c}/revoke")
        )
        settle(w.engine, None, revoke, waiting)
        g_tr.release()  # the transfer moves on to the rows the others hold
        time.sleep(0.5)
        g_grant.release()
        results = {
            "grant": finish(grant, "grant"),
            "transfer": finish(transfer, "transfer"),
            "revoke": finish(revoke, "revoke"),
        }
    delta = settled_deadlock_delta(w.engine, pool, before)
    o = Outcome(results, None, None, list(pool.failures), delta)
    assert_clean(o)
    statuses = [o.status(n) for n in ("grant", "transfer", "revoke")]
    if hi:
        # the grant locks g_X first and parks before C's row; B's revoke then takes C's row and the grant, which
        # re-reads its caller's owner row under the lock, is refused (no delegation)
        assert statuses == [NOT_OWNER, OK200, OK200], o.summary()
        assert rows(w.engine, DELEGATIONS, c=w.campaign_id) == []
    else:
        # the grant holds C's row from the start: the revoke queues behind it and applies after
        assert statuses == [OK200, OK200, OK200], o.summary()
        assert [d["gm"] for d in rows(w.engine, DELEGATIONS, c=w.campaign_id)] == [g_x]
    assert r_c not in live_roles(w.engine, [c_m]).get("campaign_owner", [])


# ======================================================================================================================
# E. M-1: the membership class
# ======================================================================================================================


def membership_pair(
    w: World, order: str, label: str, *, c_roles: tuple[str, ...], x_roles: tuple[str, ...]
) -> Cast:
    """Two members holding `c_roles` and `x_roles` (system role codes); `order` says whether C's membership id is
    below or above X's."""
    with w.engine.begin() as c:
        u1, u2 = make_user(c, f"{label} one"), make_user(c, f"{label} two")
        m1 = make_campaign_membership(c, w.campaign_id, u1)
        m2 = make_campaign_membership(c, w.campaign_id, u2)
    (lo_m, lo_u), (hi_m, hi_u) = sorted([(m1, u1), (m2, u2)], key=lambda t: t[0])
    if order == "cmC_below_cmX":
        (c_m, c_user), (x_m, x_user) = (lo_m, lo_u), (hi_m, hi_u)
    else:
        (c_m, c_user), (x_m, x_user) = (hi_m, hi_u), (lo_m, lo_u)
    with w.engine.begin() as c:
        for role_code in c_roles:
            insert_role(c, None, c_m, system_role_id(c, role_code))
        for role_code in x_roles:
            insert_role(c, None, x_m, system_role_id(c, role_code))
    return Cast(c_user, c_m, x_user, x_m, {})


def grant_body(x_m: uuid.UUID) -> dict[str, Any]:
    return {"grantee_campaign_membership_id": str(x_m), "reason": "e"}


@pytest.mark.parametrize("order", ("cmC_below_cmX", "cmC_above_cmX"))
@pytest.mark.parametrize(
    "pair", ("grant_vs_assign", "grant_vs_transfer", "end_vs_assign", "end_vs_transfer")
)
def test_e_membership_locks_never_wait_in_a_cycle(
    pair: str, order: str, w: World, pool: Pool
) -> None:
    make_managers(w.engine, w.campaign_id, label="E")
    if pair == "grant_vs_assign":
        cast = membership_pair(w, order, "E1", c_roles=("campaign_owner",), x_roles=("gm",))
        with w.engine.connect() as c:
            player = system_role_id(c, "player")
        o = race(
            w,
            pool,
            gate_pattern=GRANT_DELEGATIONS,
            parked=lambda: post(
                pool, cast.c_user, f"{w.base}/reveal-delegations", grant_body(cast.x_m)
            ),
            second=lambda: post(
                pool,
                cast.c_user,
                f"{w.base}/memberships/{cast.x_m}/roles",
                {"role_id": str(player)},
            ),
        )
        assert_clean(o)
        assert (o.status("parked"), o.status("second")) == (OK200, OK201), o.summary()
        assert "player" in live_roles(w.engine, [cast.x_m])
    elif pair == "grant_vs_transfer":
        # X holds no gm: the grant is refused at its final check, after every lock; the transfer X->C is a no-op
        cast = membership_pair(
            w, order, "E2", c_roles=("campaign_owner",), x_roles=("campaign_owner",)
        )
        o = race(
            w,
            pool,
            gate_pattern=GRANT_DELEGATIONS,
            parked=lambda: post(
                pool, cast.c_user, f"{w.base}/reveal-delegations", grant_body(cast.x_m)
            ),
            second=lambda: post(
                pool, cast.x_user, f"{w.base}/ownership-transfer", transfer_body(cast.c_m, False)
            ),
        )
        assert_clean(o)
        assert (o.status("parked"), o.status("second")) == (
            (409, "reveal_delegation_recipient_not_gm"),
            OK200,
        ), o.summary()
        assert rows(w.engine, DELEGATIONS, c=w.campaign_id) == []
    elif pair == "end_vs_assign":
        cast = membership_pair(w, order, "E3", c_roles=("campaign_owner",), x_roles=("player",))
        with w.engine.connect() as c:
            observer = system_role_id(c, "observer")
        o = race(
            w,
            pool,
            gate_pattern=END_ACTOR_KEY_SHARE,
            parked=lambda: post(pool, cast.c_user, f"{w.base}/memberships/{cast.x_m}/end"),
            second=lambda: post(
                pool,
                cast.c_user,
                f"{w.base}/memberships/{cast.x_m}/roles",
                {"role_id": str(observer)},
            ),
        )
        assert_clean(o)
        # the assign-after-end response (HEAD answers 409 `conflict`; the pre-S5-E2 baseline answered 404)
        assert (o.status("parked"), o.status("second")) == (OK200, (409, "conflict")), o.summary()
        assert "observer" not in live_roles(w.engine, [cast.x_m])
    else:
        cast = membership_pair(w, order, "E4", c_roles=("campaign_owner",), x_roles=("player",))
        o = race(
            w,
            pool,
            gate_pattern=END_ACTOR_KEY_SHARE,
            parked=lambda: post(pool, cast.c_user, f"{w.base}/memberships/{cast.x_m}/end"),
            second=lambda: post(
                pool, cast.c_user, f"{w.base}/ownership-transfer", transfer_body(cast.x_m, False)
            ),
        )
        assert_clean(o)
        # the transfer to a member whose membership has ended is refused after the end commits
        assert (o.status("parked"), o.status("second")) == (OK200, (409, "conflict")), o.summary()
        assert "campaign_owner" not in live_roles(w.engine, [cast.x_m])


# ======================================================================================================================
# F. P-1: authoring (role rows, then the membership) against the grant, change and transfer
# ======================================================================================================================


def author_request(pool: Pool, w: World) -> Any:
    return post(
        pool,
        w.gm_user,
        f"{w.base}/authoring/dungeons",
        {"name": f"F {uuid.uuid4().hex[:6]}", "summary": None},
        **{"Idempotency-Key": str(uuid.uuid4())},
    )


_CAMPAIGN_ROW_CYCLE = pytest.mark.xfail(
    strict=True,
    reason=(
        "OPEN CONFLICT with the design (reported, not fixed): C3 removes the membership edge, but an authoring request "
        "already holds the campaign row FOR KEY SHARE (its idempotency reservation's foreign key) when it waits for a "
        "role row, and `change` and `transfer` want that row FOR UPDATE after their role rows. The residual cycle is not "
        "introduced by S5-E2 or by C1-C4: the 0edb94d tree with C3 applied deadlocks the same way (plan "
        "6.28.5)."
    ),
)


@pytest.mark.parametrize("other_row", ("below_gX", "above_gX"))
@pytest.mark.parametrize(
    "peer",
    (
        "grant",
        pytest.param("change", marks=_CAMPAIGN_ROW_CYCLE),
        pytest.param("transfer_to_expired_owner", marks=_CAMPAIGN_ROW_CYCLE),
    ),
)
def test_f_authoring_never_waits_in_a_cycle_with_a_role_writer(
    peer: str, other_row: str, w: World, pool: Pool
) -> None:
    """X (`w.gm_user`) authors while another request holds one of X's role rows and wants X's membership. Authoring
    takes its role rows, then the membership: it holds only role rows while it waits."""
    m = make_managers(w.engine, w.campaign_id, label="F")
    other = tag("low" if other_row == "below_gX" else "high", "01")
    assert (other < w.gm_role) == (other_row == "below_gX")
    with w.engine.begin() as c:
        c_user = make_user(c, "F C")
        c_m = make_campaign_membership(c, w.campaign_id, c_user)
        insert_role(c, None, c_m, system_role_id(c, "campaign_owner"))
        insert_role(c, other, w.gm_membership, system_role_id(c, "player"))
        observer = system_role_id(c, "observer")
        if peer == "transfer_to_expired_owner":
            c.execute(
                text(
                    "INSERT INTO security.membership_roles (membership_role_id, campaign_membership_id, "
                    "role_id, granted_at, expires_at) VALUES (:r, :m, :role, "
                    "now() - interval '2 hours', now() - interval '1 hour')"
                ),
                {
                    "r": tag("high", "e1"),
                    "m": w.gm_membership,
                    "role": system_role_id(c, "campaign_owner"),
                },
            )
    if peer == "grant":
        o = race(
            w,
            pool,
            gate_pattern=GRANT_GRANTEE_NKU,
            parked=lambda: post(
                pool, c_user, f"{w.base}/reveal-delegations", grant_body(w.gm_membership)
            ),
            second=lambda: author_request(pool, w),
        )
        assert o.status("parked") == OK200, o.summary()
    elif peer == "change":
        o = race(
            w,
            pool,
            gate_pattern=MEMBERSHIP_LOCK,
            parked=lambda: post(
                pool,
                m.manager_user,
                f"{w.base}/memberships/roles/{w.gm_role}/change",
                {"new_role_id": str(observer)},
            ),
            second=lambda: author_request(pool, w),
        )
        assert o.status("parked") == OK201, o.summary()
    else:
        o = race(
            w,
            pool,
            gate_pattern=MEMBERSHIP_LOCK,
            parked=lambda: post(
                pool, c_user, f"{w.base}/ownership-transfer", transfer_body(w.gm_membership, False)
            ),
            second=lambda: author_request(pool, w),
        )
        assert o.status("parked") == OK200, o.summary()
    assert_clean(o)
    assert_waited_on_parked(o, r"membership_roles")
    # after a `change` the author lost `gm` (and so `canon.edit`): its request is refused after the wait
    if peer != "change":
        assert o.status("second") == OK201, o.summary()


# ======================================================================================================================
# G. Actual lock modes, probed on the live rows while each request is parked after its passes
# ======================================================================================================================

_VECTOR = {
    (0, 0, 0, 0): "none",
    (0, 0, 0, 1): "KS",
    (0, 0, 1, 1): "S",
    (0, 1, 1, 1): "NKU",
    (1, 1, 1, 1): "U",
}
ROLE_ROW = ("security.membership_roles", "membership_role_id")
MEMBERSHIP_ROW = ("security.campaign_memberships", "campaign_membership_id")


def held_mode(admin: Engine, kind: tuple[str, str], row: uuid.UUID) -> str:
    """The strongest row lock another backend holds, by which `NOWAIT` requests it refuses: `KEY SHARE` is refused
    only by `UPDATE`, `SHARE` by `NO KEY UPDATE` and `UPDATE`, `NO KEY UPDATE` by those and `SHARE`."""
    table, pk = kind
    refused: list[int] = []
    for mode in ("KEY SHARE", "SHARE", "NO KEY UPDATE", "UPDATE"):
        with admin.connect() as c:
            try:
                c.execute(
                    text(f"SELECT 1 FROM {table} WHERE {pk} = :i FOR {mode} NOWAIT"), {"i": row}
                )
                refused.append(0)
            except OperationalError as exc:
                assert getattr(exc.orig, "sqlstate", None) == "55P03", exc
                refused.append(1)
    return _VECTOR[tuple(refused)]  # type: ignore[index]


def park_and_probe(
    w: World,
    p: Pool,
    *,
    gate_pattern: str,
    request: Callable[[], Any],
    probes: dict[str, tuple[tuple[str, str], uuid.UUID]],
    nth: int = 1,
    meanwhile: Callable[[], None] | None = None,
) -> tuple[Any, dict[str, str]]:
    """Park `request` at the gate, probe the named rows' held modes (and run `meanwhile`), release, return."""
    with NthGate(p.engine, gate_pattern, nth) as gate:
        parked = run_in_thread("parked", request)
        if not gate.reached.wait(PATIENCE):
            gate.release()
            finish(parked, "parked request finishes")
            raise AssertionError(
                f"INCOMPATIBLE GATE (not a deadlock finding): {gate_pattern!r} never executed in this tree"
            )
        modes = {label: held_mode(w.engine, *spec) for label, spec in probes.items()}
        if meanwhile is not None:
            meanwhile()
        gate.release()
        response = finish(parked, "parked finishes")
    assert not p.failures, f"driver exceptions: {p.failures}"
    return response, modes


def owners(w: World, label: str, *, ids: dict[str, str] | None = None) -> Cast:
    """C and A, both live non-expiring owners."""
    ids = ids or {}
    return cast_two(
        w,
        label=label,
        roles={
            "r_c": ("c", "campaign_owner", ids.get("r_c", "high:c1")),
            "r_a": ("x", "campaign_owner", ids.get("r_a", "low:b1")),
        },
    )


def test_g_grant_holds_each_row_at_the_mode_it_needs(w: World, pool: Pool) -> None:
    make_managers(w.engine, w.campaign_id, label="G1")
    cast = cast_two(
        w,
        label="G1",
        roles={"r_c": ("c", "campaign_owner", "low:c1"), "g_x": ("x", "gm", "high:a1")},
    )
    response, modes = park_and_probe(
        w,
        pool,
        gate_pattern=GRANT_DELEGATIONS,
        request=lambda: post(
            pool, cast.c_user, f"{w.base}/reveal-delegations", grant_body(cast.x_m)
        ),
        probes={
            "owner row": (ROLE_ROW, cast.ids["r_c"]),
            "gm row": (ROLE_ROW, cast.ids["g_x"]),
            "grantee membership": (MEMBERSHIP_ROW, cast.x_m),
            "caller membership": (MEMBERSHIP_ROW, cast.c_m),
        },
    )
    assert code(response) == 200
    assert modes == {
        "owner row": "S",
        "gm row": "U",
        "grantee membership": "NKU",
        "caller membership": "KS",
    }


@pytest.mark.parametrize("recipient_row", ("live", "expired"))
def test_g_transfer_holds_each_row_at_the_mode_it_needs(
    recipient_row: str, w: World, pool: Pool
) -> None:
    make_managers(w.engine, w.campaign_id, label="G2")
    cast = owners(w, "G2")
    if recipient_row == "expired":
        with w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.membership_roles SET granted_at = now() - interval '2 hours', "
                    "expires_at = now() - interval '1 hour' WHERE membership_role_id = :r"
                ),
                {"r": cast.ids["r_a"]},
            )
    response, modes = park_and_probe(
        w,
        pool,
        gate_pattern=ACTOR_ACCOUNT,
        request=lambda: post(
            pool, cast.c_user, f"{w.base}/ownership-transfer", transfer_body(cast.x_m, False)
        ),
        probes={
            "actor owner row": (ROLE_ROW, cast.ids["r_c"]),
            "recipient owner row": (ROLE_ROW, cast.ids["r_a"]),
            "actor membership": (MEMBERSHIP_ROW, cast.c_m),
            "recipient membership": (MEMBERSHIP_ROW, cast.x_m),
        },
    )
    assert code(response) == 200
    assert modes == {
        "actor owner row": "NKU",
        "recipient owner row": "KS" if recipient_row == "live" else "NKU",
        "actor membership": "S",
        "recipient membership": "U",
    }


@pytest.mark.parametrize("route", ("assign", "change"))
def test_g_assign_and_change_hold_the_actor_membership_shared_and_the_target_exclusive(
    route: str, w: World, pool: Pool
) -> None:
    make_managers(w.engine, w.campaign_id, label="G3")
    cast = cast_two(
        w,
        label="G3",
        roles={"r_c": ("c", "campaign_owner", "low:c1"), "p_x": ("x", "player", "high:a1")},
    )
    with w.engine.connect() as c:
        observer = system_role_id(c, "observer")
    if route == "assign":
        request = lambda: post(  # noqa: E731
            pool, cast.c_user, f"{w.base}/memberships/{cast.x_m}/roles", {"role_id": str(observer)}
        )
        probes = {
            "actor membership": (MEMBERSHIP_ROW, cast.c_m),
            "target membership": (MEMBERSHIP_ROW, cast.x_m),
        }
    else:
        request = lambda: post(  # noqa: E731
            pool,
            cast.c_user,
            f"{w.base}/memberships/roles/{cast.ids['p_x']}/change",
            {"new_role_id": str(observer)},
        )
        probes = {
            "actor membership": (MEMBERSHIP_ROW, cast.c_m),
            "target membership": (MEMBERSHIP_ROW, cast.x_m),
            "actor role row": (ROLE_ROW, cast.ids["r_c"]),
            "target role row": (ROLE_ROW, cast.ids["p_x"]),
        }
    response, modes = park_and_probe(
        w, pool, gate_pattern=ACTOR_ACCOUNT, request=request, probes=probes
    )
    assert code(response) == 201
    expected = {"actor membership": "S", "target membership": "U"}
    if route == "change":
        expected |= {"actor role row": "U", "target role row": "U"}
    assert modes == expected


AUTHOR_MEMBERSHIP = (
    r"FROM security\.campaign_memberships cm WHERE cm\.campaign_id = \S+ AND cm\.user_id = \S+ "
    r"AND cm\.ended_at IS NULL FOR SHARE$"
)


def test_g_authoring_locks_its_role_rows_before_its_membership(w: World, pool: Pool) -> None:
    response, modes = park_and_probe(
        w,
        pool,
        gate_pattern=AUTHOR_MEMBERSHIP,
        request=lambda: author_request(pool, w),
        probes={
            "gm role row": (ROLE_ROW, w.gm_role),
            "membership": (MEMBERSHIP_ROW, w.gm_membership),
        },
    )
    assert code(response) == 201
    assert modes == {"gm role row": "S", "membership": "none"}


# ======================================================================================================================
# H. Candidate binding and drift: the recipient's owner row changes after discovery
# ======================================================================================================================


def transfer_audits(engine: Engine) -> int:
    return int(
        rows(
            engine,
            "SELECT count(*) AS n FROM audit.change_log WHERE command_name = 'transfer_campaign_ownership'",
        )[0]["n"]
    )


def park_transfer(
    w: World, pool: Pool, cast: Cast, gate_pattern: str, meanwhile: Callable[[], None]
) -> Any:
    response, _ = park_and_probe(
        w,
        pool,
        gate_pattern=gate_pattern,
        request=lambda: post(
            pool, cast.c_user, f"{w.base}/ownership-transfer", transfer_body(cast.x_m, False)
        ),
        probes={},
        meanwhile=meanwhile,
    )
    return response


def test_h_an_owner_row_inserted_after_discovery_is_a_classified_409_not_a_unique_violation(
    w: World, pool: Pool
) -> None:
    make_managers(w.engine, w.campaign_id, label="H1")
    cast = cast_two(
        w,
        label="H1",
        roles={"r_c": ("c", "campaign_owner", "high:c1"), "p_x": ("x", "player", "low:b1")},
    )
    injected: list[uuid.UUID] = []

    def insert_owner() -> None:
        with w.engine.begin() as c:
            injected.append(insert_role(c, None, cast.x_m, system_role_id(c, "campaign_owner")))

    audits = transfer_audits(w.engine)
    response = park_transfer(w, pool, cast, TRANSFER_EXPIRED, insert_owner)
    assert (code(response), error_of(response)) == (409, "ownership_transfer_recipient_changed")
    assert live_roles(w.engine, [cast.x_m])["campaign_owner"] == injected, "nothing was written"
    assert live_roles(w.engine, [cast.c_m])["campaign_owner"] == [cast.ids["r_c"]]
    assert transfer_audits(w.engine) == audits


def test_h_a_candidate_revoked_after_discovery_takes_the_insert_path(w: World, pool: Pool) -> None:
    make_managers(w.engine, w.campaign_id, label="H2")
    cast = owners(w, "H2")

    def revoke_candidate() -> None:
        with w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
                ),
                {"r": cast.ids["r_a"]},
            )

    audits = transfer_audits(w.engine)
    response = park_transfer(w, pool, cast, TRANSFER_EXPIRED, revoke_candidate)
    assert (code(response), error_of(response)) == OK200
    now_owners = live_roles(w.engine, [cast.x_m])["campaign_owner"]
    assert len(now_owners) == 1 and now_owners != [cast.ids["r_a"]], (
        "a fresh owner row was inserted"
    )
    assert live_roles(w.engine, [cast.c_m])["campaign_owner"] == [cast.ids["r_c"]]
    assert transfer_audits(w.engine) == audits + 1


def expiring_recipient(w: World, label: str) -> Cast:
    cast = owners(w, label)
    with w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles "
                "SET expires_at = clock_timestamp() + interval '1500 milliseconds' "
                "WHERE membership_role_id = :r"
            ),
            {"r": cast.ids["r_a"]},
        )
    return cast


def test_h_expiry_between_the_two_recipient_statements_is_a_409(w: World, pool: Pool) -> None:
    make_managers(w.engine, w.campaign_id, label="H3")
    cast = expiring_recipient(w, "H3")
    audits = transfer_audits(w.engine)
    response = park_transfer(
        w, pool, cast, TRANSFER_LIVE, lambda: wait_expired(w.engine, cast.ids["r_a"])
    )
    assert (code(response), error_of(response)) == (409, "ownership_transfer_recipient_changed")
    assert live_roles(w.engine, [cast.x_m])["campaign_owner"] == [cast.ids["r_a"]], (
        "nothing was written"
    )
    assert transfer_audits(w.engine) == audits


def test_h_the_callers_ownership_is_judged_before_the_recipients_drift(
    w: World, pool: Pool
) -> None:
    """Exact refusal precedence: the owner gate (403) comes before the drift refusal (409)."""
    make_managers(w.engine, w.campaign_id, label="H4")
    cast = expiring_recipient(w, "H4")

    def lose_ownership_and_let_the_recipient_expire() -> None:
        wait_expired(w.engine, cast.ids["r_a"])
        with w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
                ),
                {"r": cast.ids["r_c"]},
            )

    audits = transfer_audits(w.engine)
    response = park_transfer(
        w, pool, cast, TRANSFER_LIVE, lose_ownership_and_let_the_recipient_expire
    )
    assert (code(response), error_of(response)) == NOT_OWNER
    assert transfer_audits(w.engine) == audits


# ======================================================================================================================
# I. Self-delegation, self-transfer, self assign and change
# ======================================================================================================================


def test_i_self_delegation_takes_the_membership_once_at_the_stronger_mode(
    w: World, pool: Pool
) -> None:
    make_managers(w.engine, w.campaign_id, label="I1")
    with w.engine.begin() as c:
        user = make_user(c, "I1 C")
        m = make_campaign_membership(c, w.campaign_id, user)
        r_c = insert_role(c, tag("low", "c1"), m, system_role_id(c, "campaign_owner"))
        g_c = insert_role(c, tag("high", "a1"), m, system_role_id(c, "gm"))
    response, modes = park_and_probe(
        w,
        pool,
        gate_pattern=GRANT_DELEGATIONS,
        request=lambda: post(pool, user, f"{w.base}/reveal-delegations", grant_body(m)),
        probes={
            "owner row": (ROLE_ROW, r_c),
            "gm row": (ROLE_ROW, g_c),
            "membership": (MEMBERSHIP_ROW, m),
        },
    )
    assert code(response) == 200
    assert modes == {"owner row": "S", "gm row": "U", "membership": "NKU"}
    assert [d["gm"] for d in rows(w.engine, DELEGATIONS, c=w.campaign_id)] == [g_c]


@pytest.mark.parametrize("relinquish", (False, True))
def test_i_self_transfer_changes_nothing_and_does_not_upgrade_any_lock(
    relinquish: bool, w: World, pool: Pool
) -> None:
    make_managers(w.engine, w.campaign_id, label="I2")
    with w.engine.begin() as c:
        user = make_user(c, "I2 C")
        m = make_campaign_membership(c, w.campaign_id, user)
        r_c = insert_role(c, None, m, system_role_id(c, "campaign_owner"))
    audits = transfer_audits(w.engine)
    response, modes = park_and_probe(
        w,
        pool,
        gate_pattern=ACTOR_ACCOUNT,
        request=lambda: post(
            pool, user, f"{w.base}/ownership-transfer", transfer_body(m, relinquish)
        ),
        probes={"owner row": (ROLE_ROW, r_c), "membership": (MEMBERSHIP_ROW, m)},
    )
    assert (code(response), error_of(response)) == OK200
    assert modes == {"owner row": "NKU", "membership": "U"}
    assert live_roles(w.engine, [m])["campaign_owner"] == [r_c]
    assert transfer_audits(w.engine) == audits


@pytest.mark.parametrize("route", ("assign", "change"))
def test_i_self_assign_and_self_change_take_the_membership_once_exclusively(
    route: str, w: World, pool: Pool
) -> None:
    make_managers(w.engine, w.campaign_id, label="I3")
    with w.engine.begin() as c:
        user = make_user(c, "I3 C")
        m = make_campaign_membership(c, w.campaign_id, user)
        insert_role(c, None, m, system_role_id(c, "campaign_owner"))
        player_row = insert_role(c, None, m, system_role_id(c, "player"))
        observer = system_role_id(c, "observer")
    if route == "assign":
        request = lambda: post(  # noqa: E731
            pool, user, f"{w.base}/memberships/{m}/roles", {"role_id": str(observer)}
        )
    else:
        request = lambda: post(  # noqa: E731
            pool,
            user,
            f"{w.base}/memberships/roles/{player_row}/change",
            {"new_role_id": str(observer)},
        )
    response, modes = park_and_probe(
        w,
        pool,
        gate_pattern=ACTOR_ACCOUNT,
        request=request,
        probes={"membership": (MEMBERSHIP_ROW, m)},
    )
    assert (code(response), error_of(response)) == OK201
    assert modes == {"membership": "U"}
    assert "observer" in live_roles(w.engine, [m])


# ======================================================================================================================
# J. The transfer against other lifecycle operations of the design review (E6, E7, E10)
#    (E8 recovery promoting the recipient, E9 invitation acceptance reopening the recipient and E11 campaign archive
#    are NOT executed against this route here; they stay source-traced, see plan 6.28.)
# ======================================================================================================================


@pytest.mark.parametrize("arrival", ("transfer_parked", "end_parked"))
def test_e6_ending_the_actors_membership_and_the_actors_transfer_serialize(
    arrival: str, w: World, pool: Pool
) -> None:
    """The manager ends the transferring owner's membership while the owner transfers (relinquishing) to A."""
    m = make_managers(w.engine, w.campaign_id, label="E6")
    cast = owners(w, "E6")
    audits = transfer_audits(w.engine)

    def transfer() -> Any:
        return post(
            pool, cast.c_user, f"{w.base}/ownership-transfer", transfer_body(cast.x_m, True)
        )

    def end() -> Any:
        return post(pool, m.manager_user, f"{w.base}/memberships/{cast.c_m}/end")

    if arrival == "transfer_parked":
        o = race(w, pool, gate_pattern=ACTOR_ACCOUNT, parked=transfer, second=end)
        assert_clean(o)
        assert_waited_on_parked(o, r"membership_roles|campaign_memberships")
        assert (o.status("parked"), o.status("second")) == (OK200, OK200), o.summary()
        assert transfer_audits(w.engine) == audits + 1
    else:
        o = race(w, pool, gate_pattern=END_ACTOR_KEY_SHARE, parked=end, second=transfer)
        assert_clean(o)
        assert_waited_on_parked(o, r"membership_roles|campaign_memberships")
        assert (o.status("parked"), o.status("second")) == (OK200, NOT_OWNER), o.summary()
        assert transfer_audits(w.engine) == audits
    assert live_roles(w.engine, [cast.x_m]).get("campaign_owner"), "the recipient is an owner"


def test_e7_deactivating_the_recipients_account_before_the_transfers_account_check_refuses_it(
    w: World, pool: Pool
) -> None:
    make_managers(w.engine, w.campaign_id, label="E7")
    cast = cast_two(
        w,
        label="E7",
        roles={"r_c": ("c", "campaign_owner", "high:c1"), "p_x": ("x", "player", "low:b1")},
    )
    with w.engine.connect() as c:
        recipient_user = c.execute(
            text(
                "SELECT user_id FROM security.campaign_memberships WHERE campaign_membership_id = :m"
            ),
            {"m": cast.x_m},
        ).scalar_one()

    def deactivate() -> None:
        with w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.users SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                    "core.lifecycle_statuses WHERE code = 'archived') WHERE user_id = :u"
                ),
                {"u": recipient_user},
            )

    audits = transfer_audits(w.engine)
    response, _ = park_and_probe(
        w,
        pool,
        gate_pattern=ACTOR_ACCOUNT,
        request=lambda: post(
            pool, cast.c_user, f"{w.base}/ownership-transfer", transfer_body(cast.x_m, False)
        ),
        probes={},
        meanwhile=deactivate,
    )
    assert (code(response), error_of(response)) == (409, "conflict")
    assert transfer_audits(w.engine) == audits
    assert "campaign_owner" not in live_roles(w.engine, [cast.x_m])


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OPEN CONFLICT with the design (reported, not fixed): the actor's own authoring request holds the campaign "
        "row FOR KEY SHARE (its reservation) while it waits for a role row the transfer holds, and the transfer wants "
        "that row FOR UPDATE: the same residual cycle as the `change` and `transfer` cases of test_f."
    ),
)
def test_e10_the_actors_authoring_request_against_its_own_transfer(w: World, pool: Pool) -> None:
    make_managers(w.engine, w.campaign_id, label="E10")
    with w.engine.begin() as c:
        insert_role(c, None, w.gm_membership, system_role_id(c, "campaign_owner"))
    recipient = owners(w, "E10")
    o = race(
        w,
        pool,
        gate_pattern=ACTOR_ACCOUNT,
        parked=lambda: post(
            pool,
            w.gm_user,
            f"{w.base}/ownership-transfer",
            transfer_body(recipient.x_m, False),
        ),
        second=lambda: author_request(pool, w),
    )
    assert_clean(o)
    assert (o.status("parked"), o.status("second")) == (OK200, OK201), o.summary()


# ======================================================================================================================
# K. Ascending-order probes (TA-1: the lower id is locked first, in each class) and BA-1
# ======================================================================================================================

GRANT_MEMBERSHIP = (
    r"^SELECT 1 FROM security\.campaign_memberships WHERE campaign_membership_id = \S+ "
    r"FOR (KEY SHARE|NO KEY UPDATE)$"
)


@pytest.mark.parametrize("order", ("gX_below_rC", "rC_below_gX"))
def test_k_the_grants_role_pass_takes_the_lower_row_first(order: str, w: World, pool: Pool) -> None:
    make_managers(w.engine, w.campaign_id, label="K1")
    g_below = order == "gX_below_rC"
    cast = cast_two(
        w,
        label="K1",
        roles={
            "r_c": ("c", "campaign_owner", "high:c1" if g_below else "low:c1"),
            "g_x": ("x", "gm", "low:a1" if g_below else "high:a1"),
        },
    )
    response, modes = park_and_probe(
        w,
        pool,
        gate_pattern=GRANT_ROLE_LOCK,
        nth=2,
        request=lambda: post(
            pool, cast.c_user, f"{w.base}/reveal-delegations", grant_body(cast.x_m)
        ),
        probes={"owner row": (ROLE_ROW, cast.ids["r_c"]), "gm row": (ROLE_ROW, cast.ids["g_x"])},
    )
    assert code(response) == 200
    assert modes == (
        {"owner row": "none", "gm row": "U"} if g_below else {"owner row": "S", "gm row": "none"}
    )


@pytest.mark.parametrize("order", ("cmC_below_cmX", "cmC_above_cmX"))
def test_k_the_grants_membership_pass_takes_the_lower_membership_first(
    order: str, w: World, pool: Pool
) -> None:
    make_managers(w.engine, w.campaign_id, label="K2")
    cast = membership_pair(w, order, "K2", c_roles=("campaign_owner",), x_roles=("gm",))
    response, modes = park_and_probe(
        w,
        pool,
        gate_pattern=GRANT_MEMBERSHIP,
        nth=2,
        request=lambda: post(
            pool, cast.c_user, f"{w.base}/reveal-delegations", grant_body(cast.x_m)
        ),
        probes={"caller": (MEMBERSHIP_ROW, cast.c_m), "grantee": (MEMBERSHIP_ROW, cast.x_m)},
    )
    assert code(response) == 200
    assert modes == (
        {"caller": "KS", "grantee": "none"}
        if order == "cmC_below_cmX"
        else {"caller": "none", "grantee": "NKU"}
    )


@pytest.mark.parametrize("order", ("actor_below_target", "actor_above_target"))
@pytest.mark.parametrize("route", ("assign", "change", "transfer"))
def test_k_the_membership_pass_of_assign_change_and_transfer_takes_the_lower_membership_first(
    route: str, order: str, w: World, pool: Pool
) -> None:
    make_managers(w.engine, w.campaign_id, label="K3")
    cast = membership_pair(
        w,
        "cmC_below_cmX" if order == "actor_below_target" else "cmC_above_cmX",
        "K3",
        c_roles=("campaign_owner",),
        x_roles=("player",),
    )
    with w.engine.connect() as c:
        observer = system_role_id(c, "observer")
    player_row = rows(
        w.engine,
        "SELECT membership_role_id AS id FROM security.membership_roles WHERE campaign_membership_id = :m",
        m=cast.x_m,
    )[0]["id"]
    requests: dict[str, Callable[[], Any]] = {
        "assign": lambda: post(
            pool, cast.c_user, f"{w.base}/memberships/{cast.x_m}/roles", {"role_id": str(observer)}
        ),
        "change": lambda: post(
            pool,
            cast.c_user,
            f"{w.base}/memberships/roles/{player_row}/change",
            {"new_role_id": str(observer)},
        ),
        "transfer": lambda: post(
            pool, cast.c_user, f"{w.base}/ownership-transfer", transfer_body(cast.x_m, False)
        ),
    }
    response, modes = park_and_probe(
        w,
        pool,
        gate_pattern=MEMBERSHIP_LOCK,
        nth=2,
        request=requests[route],
        probes={"actor": (MEMBERSHIP_ROW, cast.c_m), "target": (MEMBERSHIP_ROW, cast.x_m)},
    )
    assert code(response) == (200 if route == "transfer" else 201)
    assert modes == (
        {"actor": "S", "target": "none"}
        if order == "actor_below_target"
        else {"actor": "none", "target": "U"}
    )


def test_h_a_gm_row_inserted_after_discovery_is_refused_with_a_retryable_409(
    w: World, pool: Pool
) -> None:
    """BA-1: the grantee had no `gm` row when the grant chose the rows to lock; one appears before the final check.
    The delegation would bind to a row nobody holds, so the grant refuses (nothing written) and a retry succeeds."""
    make_managers(w.engine, w.campaign_id, label="H5")
    cast = cast_two(w, label="H5", roles={"r_c": ("c", "campaign_owner", "low:c1")})
    injected: list[uuid.UUID] = []

    def insert_gm() -> None:
        with w.engine.begin() as c:
            injected.append(insert_role(c, None, cast.x_m, system_role_id(c, "gm")))

    def grant() -> Any:
        return post(pool, cast.c_user, f"{w.base}/reveal-delegations", grant_body(cast.x_m))

    response, _ = park_and_probe(
        w, pool, gate_pattern=GRANT_ROLE_LOCK, request=grant, probes={}, meanwhile=insert_gm
    )
    assert (code(response), error_of(response)) == (409, "reveal_delegation_recipient_changed")
    assert rows(w.engine, DELEGATIONS, c=w.campaign_id) == []
    retry = grant()
    assert (code(retry), error_of(retry)) == OK200
    assert [d["gm"] for d in rows(w.engine, DELEGATIONS, c=w.campaign_id)] == injected
