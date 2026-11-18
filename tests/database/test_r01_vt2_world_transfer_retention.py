# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 V-T2: the deferred `tr_world_memberships_retain_owner` trigger under the real world ownership transfer.

Plan section 2 (V-T2), section 9.4 and 9.6 (deterministic competitor tests in both directions) and section 12.6
(trigger verification tasks are not guarantees until a test passes). The route is the production
`POST /worlds/{world_id}/ownership-transfer` (`transfer_world_ownership_endpoint`), driven over HTTP on a pool engine.

The transfer takes `core.worlds ... FOR UPDATE` first (`_lock_and_authorize`), inserts the recipient's owner row, then
ends the caller's own owner row. That UPDATE fires the deferred constraint trigger, which at COMMIT calls
`security.assert_world_retains_owner`, whose first statement is `SELECT 1 FROM core.worlds ... FOR UPDATE`: the lock the
command already holds. Two directions, each with the former owner ending with a retained role and with no role:

* competitor first: a competitor holds the world row `FOR UPDATE`; the route must wait at its *initial* world lock,
  before any membership write; on release it completes and the transfer is durable;
* command first: the route is parked after it holds the world lock and before it updates the former owner's
  membership; a competitor asking for the same lock is blocked by the route's backend (`pg_blocking_pids`); the route
  then commits (its deferred trigger re-takes the held lock) while the competitor is still queued, and the competitor
  proceeds and sees the durable transfer.

What this establishes, and what it does not, is stated in the plan's V-T2 record (6.56); the assertions here are only
what the observed orderings show. Every case also asserts: no driver exception, the deadlock counter did not move, the
trigger functions each ran exactly once, and nothing is left open.
"""

import re
import threading
import time
import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, event, text

from tests.database.test_r01_s3_authoring_routes import World, w  # noqa: F401 - fixture by name
from tests.database.test_r01_s5e2_lock_order import (  # noqa: F401 - fixtures by name
    PATIENCE,
    NthGate,
    Pool,
    blocked_view,
    client_for,
    deadlocks_now,
    finish,
    pool,
    settled_deadlock_delta,
)
from tests.factories import make_external_identity, make_system_role_assignment, make_user
from tests.http_race_support import run_in_thread

pytestmark = pytest.mark.database

WORLD_LOCK = r"^SELECT 1 FROM core\.worlds WHERE world_id = \S+ FOR UPDATE$"
FORMER_OWNER_UPDATE = r"^UPDATE security\.world_memberships wm SET ended_at"
TRIGGER_FUNCTIONS = (
    "enforce_world_memberships_retain_owner",
    "assert_world_retains_owner",
)


@pytest.fixture
def function_stats(postgres_engine: Engine) -> Any:
    """`track_functions = 'all'` for connections the test's pool opens afterwards, so the trigger functions' calls are
    countable (`pg_stat_user_functions`). The database is the suite's own throwaway one; the setting is reset after."""
    with postgres_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        name = c.execute(text("SELECT current_database()")).scalar_one()
        quoted = '"' + name.replace('"', '""') + '"'
        c.execute(text(f"ALTER DATABASE {quoted} SET track_functions = 'all'"))
    try:
        yield
    finally:
        with postgres_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text(f"ALTER DATABASE {quoted} RESET track_functions"))


def function_calls(admin: Engine, *, wait_for: dict[str, int] | None = None) -> dict[str, int]:
    """Cumulative calls of the two trigger functions. With `wait_for`, polls (statistics are flushed asynchronously)
    until each function has reached its target, within the module's patience."""
    deadline = time.monotonic() + PATIENCE
    while True:
        with admin.connect() as c:
            c.execute(text("SELECT pg_stat_clear_snapshot()"))
            rows = c.execute(
                text("SELECT funcname, calls FROM pg_stat_user_functions WHERE funcname = ANY(:f)"),
                {"f": list(TRIGGER_FUNCTIONS)},
            ).all()
        seen = dict.fromkeys(TRIGGER_FUNCTIONS, 0) | {r.funcname: int(r.calls) for r in rows}
        if wait_for is None or all(seen[k] >= v for k, v in wait_for.items()):
            return seen
        if time.monotonic() > deadline:
            return seen
        time.sleep(0.1)


class Recorder:
    """Every statement the pool engine runs, in order, with its backend pid."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.entries: list[tuple[int, str]] = []
        self._lock = threading.Lock()

    def _hook(self, conn: Any, cursor: Any, statement: Any, *_: Any) -> None:
        pid = conn.connection.driver_connection.info.backend_pid
        with self._lock:
            self.entries.append((pid, " ".join(str(statement).split())))

    def __enter__(self) -> "Recorder":
        event.listen(self.engine, "before_cursor_execute", self._hook)
        return self

    def __exit__(self, *exc: object) -> None:
        event.remove(self.engine, "before_cursor_execute", self._hook)

    def of(self, pid: int) -> list[str]:
        with self._lock:
            return [s for p, s in self.entries if p == pid]


def make_recipient(admin: Engine) -> tuple[uuid.UUID, str]:
    """An active local account holding system `gm` (the transfer's recipient must have `world.administer`)."""
    login = f"vt2-{uuid.uuid4().hex[:10]}"
    with admin.begin() as c:
        user = make_user(c, "VT2 Recipient")
        make_system_role_assignment(c, user, "gm")
        make_external_identity(c, user, issuer="local", subject=login)
    return user, login


def membership_rows(admin: Engine, world_id: uuid.UUID) -> list[dict[str, Any]]:
    with admin.connect() as c:
        return [
            dict(r._mapping)
            for r in c.execute(
                text(
                    "SELECT wm.user_id, wr.code AS role, wm.ended_at IS NULL AS open, wm.ended_by_user_id "
                    "FROM security.world_memberships wm JOIN security.world_roles wr "
                    "ON wr.world_role_id = wm.world_role_id WHERE wm.world_id = :w "
                    "ORDER BY wm.joined_at, wr.code"
                ),
                {"w": world_id},
            )
        ]


def audit_count(admin: Engine, world_id: uuid.UUID) -> int:
    with admin.connect() as c:
        return int(
            c.execute(
                text(
                    "SELECT count(*) FROM audit.change_log WHERE world_id = :w "
                    "AND command_name = 'transfer_world_ownership'"
                ),
                {"w": world_id},
            ).scalar_one()
        )


def wait_blocked_on(admin: Engine, holder: int, *, expect: int = 1) -> list[dict[str, Any]]:
    deadline = time.monotonic() + PATIENCE
    while time.monotonic() < deadline:
        view = blocked_view(admin, holder)
        if len(view) >= expect:
            return view
        time.sleep(0.02)
    raise AssertionError(f"nothing queued behind pid {holder}")


def assert_durable(admin: Engine, world: World, recipient: uuid.UUID, retain: str | None) -> None:
    rows = membership_rows(admin, world.world_id)
    owners = [r for r in rows if r["role"] == "world_owner"]
    open_owners = {r["user_id"] for r in owners if r["open"]}
    assert open_owners == {recipient}, rows
    former_owner = [r for r in owners if r["user_id"] == world.owner]
    assert len(former_owner) == 1 and not former_owner[0]["open"], rows
    assert former_owner[0]["ended_by_user_id"] == world.owner, rows
    former_open = {r["role"] for r in rows if r["user_id"] == world.owner and r["open"]}
    assert former_open == (set() if retain is None else {retain}), rows
    assert audit_count(admin, world.world_id) == 1


def assert_response(response: Any, world: World, recipient: uuid.UUID, retain: str | None) -> None:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "world_id": str(world.world_id),
        "previous_owner_user_id": str(world.owner),
        "new_owner_user_id": str(recipient),
        "retained_role_code": retain,
    }


def assert_clean(
    admin: Engine, p: Pool, before_deadlocks: int, before_calls: dict[str, int]
) -> None:
    assert not p.failures, f"driver exceptions (40P01 = deadlock): {p.failures}"
    after = function_calls(admin, wait_for={k: v + 1 for k, v in before_calls.items()})
    assert {k: after[k] - before_calls[k] for k in TRIGGER_FUNCTIONS} == {
        "enforce_world_memberships_retain_owner": 1,
        "assert_world_retains_owner": 1,
    }, (
        "the former owner's UPDATE must fire the deferred trigger exactly once, and it must run the assert once"
    )
    assert settled_deadlock_delta(admin, p, before_deadlocks) == 0, "the deadlock counter moved"
    with admin.connect() as c:
        left = c.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND pid = ANY(:p) AND state <> 'idle'"
            ),
            {"p": p.pids},
        ).scalar_one()
    assert left == 0, "a pool backend is still open or idle in transaction"


@pytest.mark.parametrize("retain", [None, "world_editor"], ids=["ended", "retained-editor"])
def test_competitor_first_the_route_waits_at_its_initial_world_lock_then_completes(
    postgres_engine: Engine, w: World, function_stats: None, pool: Pool, retain: str | None
) -> None:
    admin = postgres_engine
    recipient, login = make_recipient(admin)
    before_rows = membership_rows(admin, w.world_id)
    before_calls = function_calls(admin)
    before_deadlocks = deadlocks_now(admin)
    competitor = admin.connect()
    try:
        competitor.execute(
            text("SELECT 1 FROM core.worlds WHERE world_id = :w FOR UPDATE"), {"w": w.world_id}
        )
        competitor_pid = int(competitor.execute(text("SELECT pg_backend_pid()")).scalar_one())
        with Recorder(pool.engine) as recorder:
            client = client_for(pool, w.owner)
            request = run_in_thread(
                "transfer",
                lambda: client.post(
                    f"/worlds/{w.world_id}/ownership-transfer",
                    json={"login_name": login, "retain_previous_owner_as": retain},
                ),
            )
            # the route queues behind the competitor, directly and only behind it
            view = wait_blocked_on(admin, competitor_pid)
            assert len(view) == 1
            waiting = view[0]
            assert waiting["blockers"] == [competitor_pid]
            assert re.search(WORLD_LOCK, waiting["query"]), waiting["query"]
            route_pid = int(waiting["pid"])
            # it waits *before* any membership write: nothing of the route has run on a membership row, and the
            # committed state is untouched while the block persists
            seen = recorder.of(route_pid)
            assert not [
                s for s in seen if "world_memberships" in s and not s.startswith("SELECT")
            ], seen
            assert not any(s.startswith(("INSERT", "UPDATE", "DELETE")) for s in seen), seen
            assert membership_rows(admin, w.world_id) == before_rows
            assert not request.finished()
            competitor.rollback()  # release
            response = finish(request, "the route after the competitor released")
        assert_response(response, w, recipient, retain)
        assert_durable(admin, w, recipient, retain)
        steps = recorder.of(route_pid)
        lock_at = next(i for i, s in enumerate(steps) if re.search(WORLD_LOCK, s))
        update_at = next(i for i, s in enumerate(steps) if re.search(FORMER_OWNER_UPDATE, s))
        assert lock_at < update_at, steps
    finally:
        competitor.close()
    assert_clean(admin, pool, before_deadlocks, before_calls)


@pytest.mark.parametrize("retain", [None, "world_editor"], ids=["ended", "retained-editor"])
def test_command_first_the_route_blocks_a_competitor_and_commits_while_it_is_queued(
    postgres_engine: Engine, w: World, function_stats: None, pool: Pool, retain: str | None
) -> None:
    admin = postgres_engine
    recipient, login = make_recipient(admin)
    before_rows = membership_rows(admin, w.world_id)
    before_calls = function_calls(admin)
    before_deadlocks = deadlocks_now(admin)
    acquired = threading.Event()
    seen_by_competitor: dict[str, Any] = {}

    def compete() -> None:
        with admin.connect() as c:
            c.execute(
                text("SELECT 1 FROM core.worlds WHERE world_id = :w FOR UPDATE"), {"w": w.world_id}
            )
            acquired.set()
            seen_by_competitor["pid"] = int(c.execute(text("SELECT pg_backend_pid()")).scalar_one())
            # a fresh read-committed statement after the lock: the route's commit must be visible
            seen_by_competitor["rows"] = [
                dict(r._mapping)
                for r in c.execute(
                    text(
                        "SELECT wm.user_id, wr.code AS role, wm.ended_at IS NULL AS open, wm.ended_by_user_id "
                        "FROM security.world_memberships wm JOIN security.world_roles wr "
                        "ON wr.world_role_id = wm.world_role_id WHERE wm.world_id = :w "
                        "ORDER BY wm.joined_at, wr.code"
                    ),
                    {"w": w.world_id},
                )
            ]
            c.rollback()

    gate = NthGate(pool.engine, FORMER_OWNER_UPDATE)
    with Recorder(pool.engine) as recorder, gate:
        client = client_for(pool, w.owner)
        request = run_in_thread(
            "transfer",
            lambda: client.post(
                f"/worlds/{w.world_id}/ownership-transfer",
                json={"login_name": login, "retain_previous_owner_as": retain},
            ),
        )
        gate.wait_reached()
        assert gate.pid is not None
        route_pid = gate.pid
        steps_at_gate = recorder.of(route_pid)
        # parked after the world lock and the recipient's owner row, before the former owner's membership update
        assert any(re.search(WORLD_LOCK, s) for s in steps_at_gate), steps_at_gate
        assert any(s.startswith("INSERT INTO security.world_memberships") for s in steps_at_gate), (
            steps_at_gate
        )
        assert not any(re.search(FORMER_OWNER_UPDATE, s) for s in steps_at_gate[:-1]), steps_at_gate
        thread = run_in_thread("competitor", lambda: compete())
        view = wait_blocked_on(admin, route_pid)
        assert len(view) == 1 and view[0]["blockers"] == [route_pid], view
        assert re.search(WORLD_LOCK, view[0]["query"]), view[0]["query"]
        competitor_pid = int(view[0]["pid"])
        assert not acquired.is_set() and not thread.finished()
        assert (
            membership_rows(admin, w.world_id) == before_rows
        )  # nothing of the route is visible yet
        gate.release()
        response = finish(
            request, "the route after the gate released, with a competitor queued behind it"
        )
        finish(thread, "the competitor after the route committed")
    assert_response(response, w, recipient, retain)
    assert acquired.is_set() and seen_by_competitor["pid"] == competitor_pid
    # the competitor only proceeded once the route had committed: its first read sees the whole transfer
    rows = seen_by_competitor["rows"]
    assert {r["user_id"] for r in rows if r["role"] == "world_owner" and r["open"]} == {
        recipient
    }, rows
    assert_durable(admin, w, recipient, retain)
    assert_clean(admin, pool, before_deadlocks, before_calls)
