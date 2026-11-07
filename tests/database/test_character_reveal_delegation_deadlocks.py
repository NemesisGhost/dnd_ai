# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""The two reveal-delegation deadlocks found in review of A1 (design section 3).

Each scenario is made deterministic with real PostgreSQL locks. A test holds one row lock, starts
the requests, and waits until PostgreSQL reports each one blocked *by that holder's session*
(`pg_blocking_pids`), not merely "someone is waiting". A request that finishes or fails before it
blocks is reported as that failure rather than as a timeout. The holder is released by the
lock-order harness's autouse fixture if a test fails. No scenario relies on a longer timeout.

1. Reciprocal grants. Two owners who both hold live built-in `gm` assignments grant each other a
   delegation. Each request locks its grantee's membership; the delegation insert then takes a
   foreign-key lock on the *granting* membership, which is the other request's grantee. A
   `FOR UPDATE` on the grantee membership conflicts with that key-share lock; `FOR NO KEY UPDATE`
   does not.
2. A grant against administrative recovery. Recovery locked the campaign row and then the
   membership it promotes; a grant locked that membership and then the campaign row (explicitly,
   and through the delegation insert's foreign key). Recovery runs whenever no *non-expiring*
   access manager exists, so a live owner with a finite assignment can grant at the same time.
"""

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.commands.recovery import recover_campaign_access_manager
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_campaign_owner_lock_order import (  # noqa: F401 - autouse fixture
    _WAIT_SECONDS,
    _Hold,
    _post,
    _release_everything,
    _Request,
    _status,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    _audit,
    _authority,
    _delegations,
    _grant_body,
    _live_delegations,
    _urls_for,
    m,
)
from tests.factories import make_membership_role, make_system_role_assignment, make_user

pytestmark = pytest.mark.database


# --- harness ----------------------------------------------------------------------------------


class _PidHold(_Hold):
    """A held row lock that knows its own backend pid, so a test can wait for a request to be
    blocked by *this* holder."""

    def __init__(self, engine: Engine, sql: str, params: dict[str, object]) -> None:
        super().__init__(engine, sql, params)
        self.pid: int = self._connection.connection.driver_connection.info.backend_pid  # type: ignore[union-attr]


@dataclass
class _Command:
    """A command running in its own transaction on its own thread; it commits on success."""

    thread: threading.Thread
    result: object = None
    error: BaseException | None = None
    _done: threading.Event = field(default_factory=threading.Event)

    @property
    def done(self) -> bool:
        return self._done.is_set()


def _run_command(engine: Engine, operation: Callable[..., object]) -> _Command:
    command = _Command(thread=threading.Thread())

    def run() -> None:
        try:
            with engine.begin() as connection:
                command.result = operation(connection)
        except BaseException as exc:  # noqa: BLE001 - surfaced to the test
            command.error = exc
        finally:
            command._done.set()

    command.thread = threading.Thread(target=run, daemon=True)
    command.thread.start()
    return command


def _blocked_by(engine: Engine, holder_pid: int) -> int:
    """Sessions waiting on a lock whose chain of blockers reaches `holder_pid`. Waiters on one row
    queue behind each other (the second is blocked by the first), so a chain is followed."""
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("""
                    WITH RECURSIVE chain(pid, blocker) AS (
                        SELECT a.pid, b.blocker
                        FROM pg_stat_activity a, unnest(pg_blocking_pids(a.pid)) AS b(blocker)
                        WHERE a.datname = current_database() AND a.wait_event_type = 'Lock'
                      UNION
                        SELECT chain.pid, b.blocker
                        FROM chain, unnest(pg_blocking_pids(chain.blocker)) AS b(blocker)
                    )
                    SELECT count(DISTINCT pid) FROM chain WHERE blocker = :holder
                """),
                {"holder": holder_pid},
            ).scalar_one()
        )


def _waiting_sessions(engine: Engine) -> list[tuple[object, ...]]:
    """(pid, blocking pids, query head) of every session waiting on a lock, for failure messages."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(r"""
                SELECT pid, pg_blocking_pids(pid), left(regexp_replace(query, '\s+', ' ', 'g'), 110)
                FROM pg_stat_activity
                WHERE datname = current_database() AND wait_event_type = 'Lock'
            """)
        ).all()
    return [tuple(row) for row in rows]


def _describe(request: object) -> str:
    if isinstance(request, _Request):
        return f"HTTP request finished with {getattr(request.response, 'status_code', None)} " + (
            f"{getattr(request.response, 'text', '')} {request.error!r}"
        )
    assert isinstance(request, _Command)
    return f"command finished with result={request.result!r} error={request.error!r}"


def _wait_until_blocked_by(
    engine: Engine, hold: _PidHold, expected: int, *requests: _Request | _Command
) -> None:
    """Waits until `expected` sessions are blocked by `hold`. A request that has already finished
    cannot be the one blocked, so it is reported as it ended instead of waiting out the clock."""
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        for request in requests:
            finished = request.done
            if finished:
                raise AssertionError(f"ended before blocking on the holder: {_describe(request)}")
        if _blocked_by(engine, hold.pid) >= expected:
            return
        time.sleep(0.02)
    raise AssertionError(
        f"expected {expected} session(s) blocked by pid {hold.pid}; "
        f"{_blocked_by(engine, hold.pid)} were. Waiting sessions: {_waiting_sessions(engine)}"
    )


def _join(request: _Request | _Command) -> None:
    request.thread.join(timeout=_WAIT_SECONDS)
    assert not request.thread.is_alive(), f"did not finish: {_describe(request)}"


# --- 1. reciprocal grants -----------------------------------------------------------------------


def test_two_owners_who_are_gms_can_grant_each_other_at_the_same_time(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    """Both requests lock their own grantee's membership, then wait on the campaign row held by the
    test. Released, each must insert a delegation whose foreign keys touch the *other* request's
    locked grantee membership. Before the fix this was a deadlock (`FOR UPDATE` against the
    foreign-key `FOR KEY SHARE`) and PostgreSQL aborted one request."""
    with postgres_engine.begin() as connection:
        make_membership_role(connection, g.o1, g.gm_role_id)
        make_membership_role(connection, g.o2, g.gm_role_id)
    hold = _PidHold(
        postgres_engine,
        "SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c FOR UPDATE",
        {"c": g.campaign_id},
    )
    url = _urls_for(g)["grant"]
    first = _post(client_factory, g.o1_user_id, url, _grant_body(g.o2))
    second = _post(client_factory, g.o2_user_id, url, _grant_body(g.o1))
    _wait_until_blocked_by(postgres_engine, hold, 2, first, second)
    hold.release()
    _join(first)
    _join(second)

    responses = (first.response, second.response)
    assert [_status(r) for r in responses] == [200, 200], [
        (_status(r), getattr(r, "text", "")) for r in responses
    ]
    assert all(r.json()["granted"] is True for r in responses)  # type: ignore[attr-defined]
    live = _live_delegations(postgres_engine, g)
    assert {row["grantee"]: row["granted_by"] for row in live} == {g.o2: g.o1, g.o1: g.o2}
    assert len(_delegations(postgres_engine, g)) == 2
    assert _audit(postgres_engine, g) == {"grant_character_reveal_delegation": 2}
    # Both are still owners, which outranks the delegation in the resolver.
    assert _authority(postgres_engine, g, g.o1) == _authority(postgres_engine, g, g.o2) == "owner"


# --- 2. a grant against administrative recovery ---------------------------------------------------


def _strand_the_campaign_for_recovery(engine: Engine, g: Gate) -> uuid.UUID:
    """Leaves `o1` as a *finite* owner (so recovery's check, which needs a non-expiring manager,
    lets it run while `o1` can still grant) and disables the other two managers' accounts, the
    ordinary way a campaign is stranded. Returns an administrator's user id."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = now() + interval '1 day' "
                "WHERE membership_role_id = :r"
            ),
            {"r": g.o1_role},
        )
    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.users SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived')
                WHERE user_id = ANY(:users)
            """),
            {"users": [g.o2_user_id, g.manager_user_id]},
        )
        admin = make_user(connection, "Recovery Admin")
        make_system_role_assignment(connection, admin, "admin")
    return admin


def test_a_grant_to_the_member_that_recovery_promotes_commits_beside_it(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    """The grant locks the GM's membership first; recovery then takes the campaign row and queues
    for that membership. Before the fix the grant went on to want the campaign row: a deadlock."""
    admin = _strand_the_campaign_for_recovery(postgres_engine, g)
    hold = _PidHold(
        postgres_engine,
        "SELECT 1 FROM security.campaign_memberships WHERE campaign_membership_id = :m FOR UPDATE",
        {"m": m.gm},
    )
    grant = _post(client_factory, g.o1_user_id, _urls_for(g)["grant"], _grant_body(m.gm))
    _wait_until_blocked_by(postgres_engine, hold, 1, grant)
    recovery = _run_command(
        postgres_engine,
        lambda connection: recover_campaign_access_manager(
            connection,
            admin_user_id=admin,
            campaign_id=g.campaign_id,
            new_user_id=m.gm_user_id,
            reason="Recover the table",
        ),
    )
    _wait_until_blocked_by(postgres_engine, hold, 2, grant, recovery)
    hold.release()
    _join(grant)
    _join(recovery)

    assert recovery.error is None, recovery.error
    assert _status(grant.response) == 200, getattr(grant.response, "text", "")
    assert grant.response.json()["granted"] is True  # type: ignore[attr-defined]
    (delegation,) = _live_delegations(postgres_engine, g)
    assert delegation["grantee"] == m.gm and delegation["granted_by"] == g.o1
    assert delegation["gm_role"] == m.gm_role
    # Recovery made the member an owner as well; their status did not change, so the delegation
    # recovery would close on a status flip stays in force.
    assert _authority(postgres_engine, g, m.gm) == "owner"
    assert recovery.result.membership_role_id is not None  # type: ignore[attr-defined]
    with postgres_engine.connect() as connection:
        status = connection.execute(
            text("""
                SELECT ms.code, cm.ended_at IS NULL FROM security.campaign_memberships cm
                JOIN security.membership_statuses ms
                  ON ms.membership_status_id = cm.membership_status_id
                WHERE cm.campaign_membership_id = :m
            """),
            {"m": m.gm},
        ).one()
    assert tuple(status) == ("active", True)
    assert _audit(postgres_engine, g) == {"grant_character_reveal_delegation": 1}
    assert _authority(postgres_engine, g, g.o1) == "owner"


def test_recovery_that_flips_a_suspended_members_status_closes_a_delegation_after_the_grant(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    """The membership recovery reactivates keeps no delegation granted while it was suspended: the
    status flip closes it. A grant that commits first is closed, not lost, and not deadlocked."""
    admin = _strand_the_campaign_for_recovery(postgres_engine, g)
    # A grant to a GM, then the member is suspended directly (no application path does this).
    grant_first = _post(client_factory, g.o1_user_id, _urls_for(g)["grant"], _grant_body(m.gm))
    _join(grant_first)
    assert _status(grant_first.response) == 200
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.campaign_memberships SET membership_status_id = (
                    SELECT membership_status_id FROM security.membership_statuses
                    WHERE code = 'suspended')
                WHERE campaign_membership_id = :m
            """),
            {"m": m.gm},
        )
    with postgres_engine.begin() as connection:
        recover_campaign_access_manager(
            connection,
            admin_user_id=admin,
            campaign_id=g.campaign_id,
            new_user_id=m.gm_user_id,
            reason="Reactivate",
        )
    (closed,) = _delegations(postgres_engine, g)
    assert closed["live"] is False and closed["end_reason"] == "membership_status_changed"
    assert _authority(postgres_engine, g, m.gm) == "owner"


# --- the caller re-check still covers the waits the foreign keys add (DEF-013) -----------------


def _let_the_caller_expire(engine: Engine, g: Gate, *, seconds: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles "
                "SET expires_at = clock_timestamp() + make_interval(secs => :s) "
                "WHERE membership_role_id = :r"
            ),
            {"s": seconds, "r": g.o1_role},
        )


def _wait_for_the_caller_to_expire(engine: Engine, g: Gate) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            if connection.execute(
                text(
                    "SELECT clock_timestamp() > expires_at FROM security.membership_roles "
                    "WHERE membership_role_id = :r"
                ),
                {"r": g.o1_role},
            ).scalar_one():
                return
        time.sleep(0.05)
    raise AssertionError("the caller's assignment never expired")


def test_a_grant_waiting_for_the_campaign_row_still_rechecks_the_caller_afterwards(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    """The delegation insert needs the campaign row `FOR KEY SHARE`. That lock is taken before the
    caller re-check, so a wait for a campaign-row `FOR UPDATE` holder (a relinquishing transfer,
    adding a member, the retention trigger) cannot hide the caller's assignment expiring."""
    _let_the_caller_expire(postgres_engine, g, seconds=4)
    hold = _PidHold(
        postgres_engine,
        "SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c FOR UPDATE",
        {"c": g.campaign_id},
    )
    grant = _post(client_factory, g.o1_user_id, _urls_for(g)["grant"], _grant_body(m.gm))
    _wait_until_blocked_by(postgres_engine, hold, 1, grant)
    _wait_for_the_caller_to_expire(postgres_engine, g)
    hold.release()
    _join(grant)
    assert _status(grant.response) == 403, getattr(grant.response, "text", "")
    assert "campaign_owner_required" in grant.response.text  # type: ignore[attr-defined]
    assert _delegations(postgres_engine, g) == []
    assert _audit(postgres_engine, g) == {}


def test_a_revocation_waiting_for_the_callers_membership_still_rechecks_the_caller(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    grant = _post(client_factory, g.o2_user_id, _urls_for(g)["grant"], _grant_body(m.gm))
    _join(grant)
    assert _status(grant.response) == 200
    _let_the_caller_expire(postgres_engine, g, seconds=4)
    hold = _PidHold(
        postgres_engine,
        "SELECT 1 FROM security.campaign_memberships WHERE campaign_membership_id = :m FOR UPDATE",
        {"m": g.o1},
    )
    revoke = _post(
        client_factory,
        g.o1_user_id,
        _urls_for(g)["revoke"].format(m.gm),
        {"reason": "Stepping back"},
    )
    _wait_until_blocked_by(postgres_engine, hold, 1, revoke)
    _wait_for_the_caller_to_expire(postgres_engine, g)
    hold.release()
    _join(revoke)
    assert _status(revoke.response) == 403, getattr(revoke.response, "text", "")
    (still,) = _live_delegations(postgres_engine, g)
    assert still["grantee"] == m.gm
    assert _audit(postgres_engine, g) == {"grant_character_reveal_delegation": 1}
