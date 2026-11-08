# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""The idempotency key lock (P03-A prerequisite P2): same-key requests queue before any row lock.

`begin_idempotent_request` takes `lock_idempotency_key` (a transaction-scoped advisory lock on the
`(actor, campaign, key)` scope) immediately before its reservation INSERT. These tests drive the
real HTTP routes with an `Idempotency-Key` header on two existing routes, ending a membership and
revoking a role:

- request A reserves the key and is then held at a row lock this test owns;
- request B arrives with the same key and must wait at the *advisory* key lock (an ungranted
  `advisory` entry in `pg_locks` on A's scope, with `pg_blocking_pids(B)` naming A), holding no row
  lock of its own;
- the test releases its hold and asserts the HTTP results, the receipts, the audit rows and the
  business state.

P2 addresses same-key lock cycles. Cycles between different keys (DEF-019) and a request's stale
authorization are separate defects and are not asserted here.
"""

import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

import dnd_ai.api.memberships as memberships_api
from dnd_ai.api.idempotency import (
    IdempotencyKeyLockError,
    idempotency_key_lock_scope,
    lock_idempotency_key,
    reset_idempotency_key_lock,
)
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_campaign_owner_lock_order import (  # noqa: F401 - autouse fixture
    _WAIT_SECONDS,
    _audit,
    _release_everything,
    _Request,
    _status,
)
from tests.database.test_character_reveal_delegation_deadlocks import (
    _blocked_by,
    _PidHold,
    _waiting_sessions,
)

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]


# --- helpers ---------------------------------------------------------------------------------------


def _urls(g: Gate) -> dict[str, str]:
    base = f"/campaigns/{g.campaign_id}"
    return {
        "end_player": f"{base}/memberships/{g.player}/end",
        "end_o2": f"{base}/memberships/{g.o2}/end",
        "revoke_player": f"{base}/memberships/roles/{g.player_role}/revoke",
    }


def _post_keyed(client_factory: Factory, user: uuid.UUID, url: str, key: str | None) -> _Request:
    request = _Request(thread=threading.Thread())
    headers = {"Idempotency-Key": key} if key else {}

    def run() -> None:
        try:
            with client_factory(user) as client:
                request.response = client.post(url, json={}, headers=headers)
        except BaseException as exc:  # noqa: BLE001 - surfaced to the test
            request.error = exc

    request.thread = threading.Thread(target=run, daemon=True)
    request.thread.start()
    return request


def _hold_membership(engine: Engine, membership: uuid.UUID) -> _PidHold:
    return _PidHold(
        engine,
        "SELECT 1 FROM security.campaign_memberships WHERE campaign_membership_id = :m FOR UPDATE",
        {"m": membership},
    )


def _hold_role(engine: Engine, membership_role: uuid.UUID) -> _PidHold:
    return _PidHold(
        engine,
        "SELECT 1 FROM security.membership_roles WHERE membership_role_id = :r FOR UPDATE",
        {"r": membership_role},
    )


def _key_lock_ids(engine: Engine, g: Gate, key: str) -> tuple[int, int]:
    """(classid, objid) of the advisory lock for the owner's scope, as `pg_locks` shows it."""
    scope = idempotency_key_lock_scope(
        actor_user_id=g.o1_user_id, campaign_id=g.campaign_id, idempotency_key=key
    )
    with engine.connect() as connection:
        value = int(
            connection.execute(text("SELECT hashtextextended(:s, 0)"), {"s": scope}).scalar_one()
        )
    unsigned = value & 0xFFFFFFFFFFFFFFFF
    return unsigned >> 32, unsigned & 0xFFFFFFFF


def _key_lock_state(engine: Engine, ids: tuple[int, int]) -> list[tuple[int, bool, list[int]]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT pid, granted, pg_blocking_pids(pid)
                FROM pg_locks
                WHERE locktype = 'advisory' AND objsubid = 1
                  AND classid::bigint = :hi AND objid::bigint = :lo
            """),
            {"hi": ids[0], "lo": ids[1]},
        ).all()
    return [(int(r[0]), bool(r[1]), [int(p) for p in r[2]]) for r in rows]


def _advisory_locks_held(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("""
                    SELECT count(*) FROM pg_locks
                    WHERE locktype = 'advisory' AND pid <> pg_backend_pid()
                      AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
                """)
            ).scalar_one()
        )


def _wait_for_the_key_queue(
    engine: Engine, ids: tuple[int, int], first: _Request, second: _Request, hold: _PidHold
) -> int:
    """Waits until `first` holds the key lock (and waits on `hold`'s row lock) and `second` waits at
    the key lock behind it, blocked by `first`. Returns `first`'s backend pid."""
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        for request in (first, second):
            if request.done:
                response = getattr(request.response, "text", None)
                raise AssertionError(f"ended before the queue formed: {response} {request.error!r}")
        state = _key_lock_state(engine, ids)
        granted = [pid for pid, ok, _ in state if ok]
        waiting = [(pid, blockers) for pid, ok, blockers in state if not ok]
        if len(granted) == 1 and len(waiting) == 1 and granted[0] in waiting[0][1]:
            assert _blocked_by(engine, hold.pid) >= 1, "the first request is not held at the row"
            return granted[0]
        time.sleep(0.02)
    raise AssertionError(
        f"no key-lock queue formed: {_key_lock_state(engine, ids)}; "
        f"waiting sessions: {_waiting_sessions(engine)}"
    )


def _receipts(engine: Engine, g: Gate, key: str) -> list[tuple[int | None, bool]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT response_status_code, response_body IS NOT NULL
                FROM security.idempotent_requests
                WHERE campaign_id = :c AND actor_user_id = :u AND idempotency_key = :k
            """),
            {"c": g.campaign_id, "u": g.o1_user_id, "k": key},
        ).all()
    return [(r[0], bool(r[1])) for r in rows]


def _open(engine: Engine, membership: uuid.UUID) -> bool:
    with engine.connect() as connection:
        return (
            connection.execute(
                text(
                    "SELECT ended_at IS NULL FROM security.campaign_memberships "
                    "WHERE campaign_membership_id = :m"
                ),
                {"m": membership},
            ).scalar_one()
            is True
        )


def _role_active(engine: Engine, role: uuid.UUID) -> bool:
    with engine.connect() as connection:
        return (
            connection.execute(
                text(
                    "SELECT revoked_at IS NULL FROM security.membership_roles WHERE membership_role_id = :r"
                ),
                {"r": role},
            ).scalar_one()
            is True
        )


def _fresh_key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _race(
    client_factory: Factory,
    engine: Engine,
    g: Gate,
    hold: _PidHold,
    first_url: str,
    second_url: str,
    key: str,
) -> tuple[Any, Any]:
    """A reserves `key` and is held at `hold`; B uses the same key and waits at the key lock behind
    A; the hold is released and both finish."""
    ids = _key_lock_ids(engine, g, key)
    first = _post_keyed(client_factory, g.o1_user_id, first_url, key)
    # A must hold the key lock before B arrives, or B could win the queue.
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline and not any(ok for _, ok, _ in _key_lock_state(engine, ids)):
        assert not first.done, getattr(first.response, "text", first.error)
        time.sleep(0.02)
    second = _post_keyed(client_factory, g.o1_user_id, second_url, key)
    _wait_for_the_key_queue(engine, ids, first, second, hold)
    hold.release()
    return first.join(), second.join()


# --- same route ------------------------------------------------------------------------------------------------------------------------


def test_a_same_key_same_payload_request_queues_at_the_key_lock_and_replays_the_receipt(
    client_factory: Factory, postgres_engine: Engine, g: Gate
) -> None:
    key = _fresh_key("same")
    urls = _urls(g)
    hold = _hold_membership(postgres_engine, g.player)
    a, b = _race(
        client_factory, postgres_engine, g, hold, urls["end_player"], urls["end_player"], key
    )
    assert (_status(a), _status(b)) == (200, 200)
    assert a.json() == b.json()  # the identical receipt
    assert _receipts(postgres_engine, g, key) == [(200, True)]  # one completed reservation
    assert _audit(postgres_engine, g).get("end_campaign_membership") == 1  # one mutation
    assert not _open(postgres_engine, g.player)


def test_a_same_key_conflicting_payload_is_a_409_that_writes_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate
) -> None:
    key = _fresh_key("conflict")
    urls = _urls(g)
    hold = _hold_membership(postgres_engine, g.player)
    a, b = _race(client_factory, postgres_engine, g, hold, urls["end_player"], urls["end_o2"], key)
    assert _status(a) == 200
    assert _status(b) == 409 and b.json()["error"]["code"] != "stale_write"
    assert _receipts(postgres_engine, g, key) == [(200, True)]  # A's, unchanged
    assert _audit(postgres_engine, g).get("end_campaign_membership") == 1
    assert not _open(postgres_engine, g.player)
    assert _open(postgres_engine, g.o2)  # the conflicting target was never touched


# --- across routes, both orders -----------------------------------------------------------------------------------------


def test_ending_a_membership_then_revoking_a_role_with_one_key_conflicts(
    client_factory: Factory, postgres_engine: Engine, g: Gate
) -> None:
    key = _fresh_key("end-then-revoke")
    urls = _urls(g)
    hold = _hold_membership(postgres_engine, g.player)
    a, b = _race(
        client_factory, postgres_engine, g, hold, urls["end_player"], urls["revoke_player"], key
    )
    assert (_status(a), _status(b)) == (200, 409)
    assert _receipts(postgres_engine, g, key) == [(200, True)]
    audit = _audit(postgres_engine, g)
    assert audit.get("end_campaign_membership") == 1 and "revoke_membership_role" not in audit
    assert not _open(postgres_engine, g.player)


def test_revoking_a_role_then_ending_a_membership_with_one_key_conflicts(
    client_factory: Factory, postgres_engine: Engine, g: Gate
) -> None:
    key = _fresh_key("revoke-then-end")
    urls = _urls(g)
    hold = _hold_role(postgres_engine, g.player_role)
    a, b = _race(
        client_factory, postgres_engine, g, hold, urls["revoke_player"], urls["end_player"], key
    )
    assert (_status(a), _status(b)) == (200, 409)
    assert _receipts(postgres_engine, g, key) == [(200, True)]
    audit = _audit(postgres_engine, g)
    assert audit.get("revoke_membership_role") == 1 and "end_campaign_membership" not in audit
    assert not _role_active(postgres_engine, g.player_role)
    assert _open(postgres_engine, g.player)  # the conflicting end never ran


def test_the_same_revoke_with_one_key_replays_in_the_other_route_family_too(
    client_factory: Factory, postgres_engine: Engine, g: Gate
) -> None:
    key = _fresh_key("revoke-twice")
    urls = _urls(g)
    hold = _hold_role(postgres_engine, g.player_role)
    a, b = _race(
        client_factory, postgres_engine, g, hold, urls["revoke_player"], urls["revoke_player"], key
    )
    assert (_status(a), _status(b)) == (200, 200) and a.json() == b.json()
    assert _receipts(postgres_engine, g, key) == [(200, True)]
    assert _audit(postgres_engine, g).get("revoke_membership_role") == 1


# --- a first request that rolls back releases the key to the second ----------------------------------------------


def test_a_first_request_that_rolls_back_leaves_the_key_free_for_the_second(
    client_factory: Factory,
    postgres_engine: Engine,
    g: Gate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = _fresh_key("rollback")
    urls = _urls(g)
    real = memberships_api.record_change_log
    calls: list[int] = []
    guard = threading.Lock()

    def fail_once(*args: Any, **kwargs: Any) -> Any:
        with guard:
            calls.append(1)
            first = len(calls) == 1
        if first:
            raise RuntimeError("audit unavailable")
        return real(*args, **kwargs)

    monkeypatch.setattr(memberships_api, "record_change_log", fail_once)
    hold = _hold_membership(postgres_engine, g.player)
    a, b = _race(
        client_factory, postgres_engine, g, hold, urls["end_player"], urls["end_player"], key
    )
    assert (
        _status(a) == 500
    )  # rolled back with its reservation, its mutation and its (failed) audit
    assert _status(b) == 200  # reserved the key afresh and ran
    assert _receipts(postgres_engine, g, key) == [(200, True)]  # B's receipt, not A's
    assert _audit(postgres_engine, g).get("end_campaign_membership") == 1
    assert not _open(postgres_engine, g.player)


# --- no key, no key lock; and the helper's own invariants --------------------------------------------------------------


def test_a_request_without_a_key_takes_no_advisory_lock(
    client_factory: Factory, postgres_engine: Engine, g: Gate
) -> None:
    urls = _urls(g)
    hold = _hold_membership(postgres_engine, g.player)
    request = _post_keyed(client_factory, g.o1_user_id, urls["end_player"], None)
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline and _blocked_by(postgres_engine, hold.pid) < 1:
        assert not request.done, getattr(request.response, "text", request.error)
        time.sleep(0.02)
    assert _blocked_by(postgres_engine, hold.pid) == 1  # it is waiting on the row, and
    assert _advisory_locks_held(postgres_engine) == 0  # has taken no advisory lock
    hold.release()
    assert _status(request.join()) == 200
    with postgres_engine.connect() as connection:  # nothing was reserved
        reserved = connection.execute(
            text("SELECT count(*) FROM security.idempotent_requests WHERE campaign_id = :c"),
            {"c": g.campaign_id},
        ).scalar_one()
    assert reserved == 0


def test_the_helper_takes_nothing_without_a_key_and_allows_one_distinct_key_per_transaction(
    postgres_engine: Engine, g: Gate
) -> None:
    actor, campaign = g.o1_user_id, g.campaign_id
    with postgres_engine.connect() as connection, connection.begin():
        reset_idempotency_key_lock(connection)
        assert (
            lock_idempotency_key(
                connection, actor_user_id=actor, campaign_id=campaign, idempotency_key=None
            )
            is False
        )
        assert _advisory_locks_held_by_me(connection) == 0
        assert (
            lock_idempotency_key(
                connection, actor_user_id=actor, campaign_id=campaign, idempotency_key="one"
            )
            is True
        )
        # The same scope again is reentrant and takes no second lock...
        assert (
            lock_idempotency_key(
                connection, actor_user_id=actor, campaign_id=campaign, idempotency_key="one"
            )
            is True
        )
        assert _advisory_locks_held_by_me(connection) == 1
        # ...but a different key in the same transaction is a programming error.
        with pytest.raises(IdempotencyKeyLockError):
            lock_idempotency_key(
                connection, actor_user_id=actor, campaign_id=campaign, idempotency_key="two"
            )
        assert _advisory_locks_held_by_me(connection) == 1  # the refused request took nothing
    with postgres_engine.connect() as connection, connection.begin():  # a new transaction is free
        assert lock_idempotency_key(
            connection, actor_user_id=actor, campaign_id=campaign, idempotency_key="two"
        )


def _advisory_locks_held_by_me(connection: Any) -> int:
    return int(
        connection.execute(
            text(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
            )
        ).scalar_one()
    )


def test_the_lock_scope_is_unambiguous_across_actor_campaign_and_key() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    scopes = {
        idempotency_key_lock_scope(actor_user_id=a, campaign_id=b, idempotency_key="k"),
        idempotency_key_lock_scope(actor_user_id=b, campaign_id=a, idempotency_key="k"),
        idempotency_key_lock_scope(actor_user_id=a, campaign_id=b, idempotency_key="k2"),
        idempotency_key_lock_scope(actor_user_id=a, campaign_id=b, idempotency_key="k|1:k"),
        idempotency_key_lock_scope(actor_user_id=a, campaign_id=a, idempotency_key="k"),
    }
    assert len(scopes) == 5
    # Deterministic, and stable across calls.
    assert idempotency_key_lock_scope(
        actor_user_id=a, campaign_id=b, idempotency_key="k"
    ) == idempotency_key_lock_scope(actor_user_id=a, campaign_id=b, idempotency_key="k")


def test_a_different_key_takes_its_own_key_lock_without_queueing_behind_a_held_request(
    client_factory: Factory, postgres_engine: Engine, g: Gate
) -> None:
    """The key lock is per scope: while one keyed request is held, a request with another key is
    granted its own key lock at once (it may then wait on business rows; that is not the key lock)."""
    urls = _urls(g)
    first_key, second_key = _fresh_key("one"), _fresh_key("two")
    hold = _hold_membership(postgres_engine, g.player)
    first = _post_keyed(client_factory, g.o1_user_id, urls["end_player"], first_key)
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline and _blocked_by(postgres_engine, hold.pid) < 1:
        assert not first.done, getattr(first.response, "text", first.error)
        time.sleep(0.02)
    second = _post_keyed(client_factory, g.o1_user_id, urls["end_o2"], second_key)
    ids = _key_lock_ids(postgres_engine, g, second_key)
    deadline = time.monotonic() + _WAIT_SECONDS
    state: list[tuple[int, bool, list[int]]] = []
    while time.monotonic() < deadline:
        state = _key_lock_state(postgres_engine, ids)
        if state or second.done:
            break
        time.sleep(0.02)
    assert state and all(granted for _, granted, _ in state)  # granted, never queued
    hold.release()
    assert (_status(first.join()), _status(second.join())) == (200, 200)
