# ruff: noqa: F811 - the imported `g` and `client_factory` are pytest fixtures used by parameter name
"""Lock order of the D3 ownership gate and the membership commands it shares rows with
(docs/PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md §3).

Every scenario is made deterministic with real PostgreSQL locks, not sleeps: a test holds a row
lock (or an uncommitted command) to park one request exactly where the interleaving needs it, waits
until PostgreSQL reports the other request as waiting on a lock, then releases. Each scenario
asserts the request outcomes, the final owner and membership state, and the audit rows.

The two scenarios that deadlocked before the order was fixed are
`test_ending_the_recipient_while_a_relinquishing_transfer_is_in_flight` and
`test_ending_an_owners_membership_while_they_assign_themselves_the_owner_role`.
"""

import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.memberships import (
    assign_membership_role,
    end_campaign_membership,
    revoke_membership_role,
    transfer_campaign_ownership,
)
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    _live_owner_memberships,
    client_factory,
    g,
)

pytestmark = pytest.mark.database

_WAIT_SECONDS = 15.0


# --- harness ----------------------------------------------------------------------------------


_open_holds: list["_Hold"] = []
_open_commands: list["_Command"] = []


class _Hold:
    """An open transaction holding one row lock until `release`."""

    def __init__(self, engine: Engine, sql: str, params: dict[str, object]) -> None:
        self._connection = engine.connect()
        self._connection.begin()
        self._connection.execute(text(sql), params).all()
        self._released = False
        _open_holds.append(self)

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._connection.rollback()
        self._connection.close()


@pytest.fixture(autouse=True)
def _release_everything(g: Gate) -> Iterator[None]:
    """A failing test must not leave a lock held or a parked transaction open: the `g` fixture's
    cleanup would wait on them forever. Runs before `g` is torn down."""
    yield
    for command in _open_commands:
        command.finish.set()
    for hold in _open_holds:
        hold.release()
    _open_commands.clear()
    _open_holds.clear()


@dataclass
class _Command:
    """An uncommitted command parked in its own transaction; `commit` or `rollback` ends it."""

    thread: threading.Thread
    ready: threading.Event = field(default_factory=threading.Event)
    finish: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None
    commit_it: bool = True

    def end(self, *, commit: bool) -> None:
        self.commit_it = commit
        self.finish.set()
        self.thread.join(timeout=_WAIT_SECONDS)
        assert not self.thread.is_alive()


def _park_command(engine: Engine, operation: Callable[[Connection], object]) -> _Command:
    parked = _Command(thread=threading.Thread())

    def run() -> None:
        try:
            with engine.connect() as connection:
                connection.begin()
                operation(connection)
                parked.ready.set()
                parked.finish.wait(timeout=_WAIT_SECONDS)
                if parked.commit_it:
                    connection.commit()
                else:
                    connection.rollback()
        except BaseException as exc:  # noqa: BLE001 - surfaced to the test
            parked.error = exc
        finally:
            parked.ready.set()

    parked.thread = threading.Thread(target=run, daemon=True)
    _open_commands.append(parked)
    parked.thread.start()
    assert parked.ready.wait(timeout=_WAIT_SECONDS)
    return parked


@dataclass
class _Request:
    thread: threading.Thread
    response: object = None
    error: BaseException | None = None

    def join(self) -> TestClient | None:
        self.thread.join(timeout=_WAIT_SECONDS)
        assert not self.thread.is_alive(), "a request did not finish"
        assert self.error is None, self.error
        return self.response  # type: ignore[return-value]

    @property
    def done(self) -> bool:
        return not self.thread.is_alive()


def _post(
    client_factory: Callable[[uuid.UUID], TestClient],
    user_id: uuid.UUID,
    url: str,
    body: dict[str, object],
) -> _Request:
    request = _Request(thread=threading.Thread())

    def run() -> None:
        try:
            with client_factory(user_id) as client:
                request.response = client.post(url, json=body)
        except BaseException as exc:  # noqa: BLE001 - surfaced to the test
            request.error = exc

    request.thread = threading.Thread(target=run, daemon=True)
    request.thread.start()
    return request


def _waiting_on_locks(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("""
                    SELECT count(*) FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND pid <> pg_backend_pid()
                      AND wait_event_type = 'Lock'
                """)
            ).scalar_one()
        )


def _wait_until_waiting(engine: Engine, expected: int) -> None:
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        if _waiting_on_locks(engine) >= expected:
            return
        time.sleep(0.02)
    raise AssertionError(f"expected {expected} session(s) waiting on a lock")


def _wait_until_not_waiting(engine: Engine) -> None:
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        if _waiting_on_locks(engine) == 0:
            return
        time.sleep(0.02)
    raise AssertionError("a session is still waiting on a lock")


def _status(response: object) -> int:
    return response.status_code  # type: ignore[attr-defined,no-any-return]


def _ended(engine: Engine, g: Gate) -> set[uuid.UUID]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text("""
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id = :c AND ended_at IS NOT NULL
                """),
                {"c": g.campaign_id},
            ).scalars()
        )


def _owners(engine: Engine, g: Gate) -> set[uuid.UUID]:
    with engine.connect() as connection:
        return _live_owner_memberships(connection, g)


def _audit(engine: Engine, g: Gate) -> dict[str, int]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT command_name, count(*) FROM audit.change_log
                WHERE world_id = :w GROUP BY command_name
            """),
            {"w": g.world_id},
        ).all()
    return dict(rows)


def _lock_membership_role_share(engine: Engine, membership_role_id: uuid.UUID) -> _Hold:
    return _Hold(
        engine,
        "SELECT 1 FROM security.membership_roles WHERE membership_role_id = :r FOR SHARE",
        {"r": membership_role_id},
    )


def _lock_owner_template(engine: Engine, g: Gate) -> _Hold:
    return _Hold(
        engine,
        "SELECT 1 FROM security.roles WHERE role_id = :r FOR UPDATE",
        {"r": g.owner_role_id},
    )


def _urls(g: Gate) -> dict[str, str]:
    base = f"/campaigns/{g.campaign_id}"
    return {
        "transfer": f"{base}/ownership-transfer",
        "end_player": f"{base}/memberships/{g.player}/end",
        "end_o1": f"{base}/memberships/{g.o1}/end",
        "assign_o1": f"{base}/memberships/{g.o1}/roles",
        "assign_player": f"{base}/memberships/{g.player}/roles",
        "revoke_o1_owner": f"{base}/memberships/roles/{g.o1_role}/revoke",
        "change_player": f"{base}/memberships/roles/{g.player_role}/change",
    }


# --- relinquishing transfer vs ending the recipient's membership ----------------------------------


def test_ending_the_recipient_while_a_relinquishing_transfer_is_in_flight(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    """Deadlocked before: the end held the recipient's membership and waited on a role row, while
    the transfer held the campaign row and waited on that membership. Now the end parks on the role
    row first, the transfer runs to completion, and the end then ends a recipient who has become an
    owner."""
    urls = _urls(g)
    hold = _lock_membership_role_share(postgres_engine, g.player_role)
    end = _post(client_factory, g.o2_user_id, urls["end_player"], {})
    _wait_until_waiting(postgres_engine, 1)
    transfer = _post(
        client_factory,
        g.o1_user_id,
        urls["transfer"],
        {"target_campaign_membership_id": str(g.player), "relinquish_own_ownership": True},
    )
    transfer_response = transfer.join()
    assert _status(transfer_response) == 200, transfer_response.text  # type: ignore[attr-defined]
    assert transfer_response.json() == {  # type: ignore[attr-defined]
        "target_campaign_membership_id": str(g.player),
        "assigned": True,
        "relinquished": True,
    }
    assert not end.done, "the end must still be waiting on the role row"
    hold.release()
    assert _status(end.join()) == 200

    assert _owners(postgres_engine, g) == {g.o2}
    assert _ended(postgres_engine, g) == {g.player}
    audit = _audit(postgres_engine, g)
    assert audit.get("transfer_campaign_ownership") == 1
    assert audit.get("end_campaign_membership") == 1


def test_a_recipient_ended_first_refuses_the_transfer_without_losing_the_owner(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    urls = _urls(g)
    ending = _park_command(
        postgres_engine,
        lambda c: end_campaign_membership(
            c,
            campaign_membership_id=g.player,
            campaign_id=g.campaign_id,
            ended_by_membership_id=g.o2,
        ),
    )
    assert ending.error is None
    transfer = _post(
        client_factory,
        g.o1_user_id,
        urls["transfer"],
        {"target_campaign_membership_id": str(g.player), "relinquish_own_ownership": True},
    )
    _wait_until_waiting(postgres_engine, 1)
    ending.end(commit=True)
    response = transfer.join()
    assert _status(response) == 409, response.text  # type: ignore[attr-defined]

    assert _owners(postgres_engine, g) == {g.o1, g.o2}
    assert _ended(postgres_engine, g) == {g.player}
    assert "transfer_campaign_ownership" not in _audit(postgres_engine, g)


def test_a_transfer_in_flight_makes_ending_its_recipient_wait_for_it(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    urls = _urls(g)
    hold = _lock_owner_template(postgres_engine, g)
    transfer = _post(
        client_factory,
        g.o1_user_id,
        urls["transfer"],
        {"target_campaign_membership_id": str(g.player), "relinquish_own_ownership": True},
    )
    _wait_until_waiting(postgres_engine, 1)
    end = _post(client_factory, g.o2_user_id, urls["end_player"], {})
    _wait_until_waiting(postgres_engine, 2)
    hold.release()
    assert _status(transfer.join()) == 200
    assert _status(end.join()) == 200

    assert _owners(postgres_engine, g) == {g.o2}
    assert _ended(postgres_engine, g) == {g.player}
    audit = _audit(postgres_engine, g)
    assert audit.get("transfer_campaign_ownership") == 1
    assert audit.get("end_campaign_membership") == 1


# --- owner self-assignment vs ending that owner's membership ------------------------------------


def test_ending_an_owners_membership_while_they_assign_themselves_the_owner_role(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    """Deadlocked before: the assignment held the owner assignment and wanted the membership; the
    end held the membership and wanted the owner assignment. Now the end takes the role rows first.
    The assignment keeps its row lock, so it fails on the unique index (it already is an owner), a
    normal 409, and the end then proceeds."""
    urls = _urls(g)
    hold = _lock_membership_role_share(postgres_engine, g.o1_role)
    end = _post(client_factory, g.o2_user_id, urls["end_o1"], {})
    _wait_until_waiting(postgres_engine, 1)
    assign = _post(
        client_factory, g.o1_user_id, urls["assign_o1"], {"role_id": str(g.owner_role_id)}
    )
    assign_response = assign.join()
    assert _status(assign_response) == 409, assign_response.text  # type: ignore[attr-defined]
    hold.release()
    assert _status(end.join()) == 200

    assert _owners(postgres_engine, g) == {g.o2}
    assert _ended(postgres_engine, g) == {g.o1}
    audit = _audit(postgres_engine, g)
    assert audit.get("end_campaign_membership") == 1
    assert "assign_membership_role" not in audit


def test_an_owner_ended_first_cannot_then_assign_themselves_the_owner_role(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    urls = _urls(g)
    ending = _park_command(
        postgres_engine,
        lambda c: end_campaign_membership(
            c,
            campaign_membership_id=g.o1,
            campaign_id=g.campaign_id,
            ended_by_membership_id=g.o2,
        ),
    )
    assert ending.error is None
    assign = _post(
        client_factory, g.o1_user_id, urls["assign_o1"], {"role_id": str(g.owner_role_id)}
    )
    _wait_until_waiting(postgres_engine, 1)
    ending.end(commit=True)
    response = assign.join()
    assert _status(response) == 403, response.text  # type: ignore[attr-defined]
    assert response.json()["error"]["code"] == "campaign_owner_required"  # type: ignore[attr-defined]

    assert _owners(postgres_engine, g) == {g.o2}
    assert _ended(postgres_engine, g) == {g.o1}
    assert "assign_membership_role" not in _audit(postgres_engine, g)


def test_a_self_assignment_that_wins_the_lock_is_a_conflict_not_a_deadlock(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    """The assignment takes the owner row and the membership, then parks on the owner template; the
    end queues behind it and runs once the assignment has failed on the unique index."""
    urls = _urls(g)
    hold = _lock_owner_template(postgres_engine, g)
    assign = _post(
        client_factory, g.o1_user_id, urls["assign_o1"], {"role_id": str(g.owner_role_id)}
    )
    _wait_until_waiting(postgres_engine, 1)
    end = _post(client_factory, g.o2_user_id, urls["end_o1"], {})
    _wait_until_waiting(postgres_engine, 2)
    hold.release()
    assert _status(assign.join()) == 409
    assert _status(end.join()) == 200

    assert _owners(postgres_engine, g) == {g.o2}
    assert _ended(postgres_engine, g) == {g.o1}
    assert _audit(postgres_engine, g).get("end_campaign_membership") == 1


# --- the protections that must survive -----------------------------------------------------------


def test_two_owners_relinquishing_to_each_other_leave_exactly_one_owner(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    """Parked on the owner template so both requests hold their own owner assignment and the
    other's membership before either reads the owners; the campaign row then serializes them, and
    the second re-reads the first's committed result."""
    urls = _urls(g)
    hold = _lock_owner_template(postgres_engine, g)
    first = _post(
        client_factory,
        g.o1_user_id,
        urls["transfer"],
        {"target_campaign_membership_id": str(g.o2), "relinquish_own_ownership": True},
    )
    second = _post(
        client_factory,
        g.o2_user_id,
        urls["transfer"],
        {"target_campaign_membership_id": str(g.o1), "relinquish_own_ownership": True},
    )
    _wait_until_waiting(postgres_engine, 2)
    hold.release()
    statuses = sorted([_status(first.join()), _status(second.join())])
    assert statuses == [200, 200]

    assert len(_owners(postgres_engine, g)) == 1
    assert _ended(postgres_engine, g) == set()
    assert _audit(postgres_engine, g).get("transfer_campaign_ownership") == 2


def test_two_identical_relinquishing_transfers_apply_once(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    urls = _urls(g)
    hold = _lock_owner_template(postgres_engine, g)
    body = {"target_campaign_membership_id": str(g.player), "relinquish_own_ownership": True}
    first = _post(client_factory, g.o1_user_id, urls["transfer"], body)
    _wait_until_waiting(postgres_engine, 1)
    second = _post(client_factory, g.o1_user_id, urls["transfer"], body)
    _wait_until_waiting(postgres_engine, 2)
    hold.release()
    statuses = sorted([_status(first.join()), _status(second.join())])
    assert statuses == [200, 403]

    assert _owners(postgres_engine, g) == {g.o2, g.player}
    assert _audit(postgres_engine, g).get("transfer_campaign_ownership") == 1


def test_a_revocation_that_commits_first_refuses_the_assignment(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    urls = _urls(g)
    revoking = _park_command(
        postgres_engine,
        lambda c: revoke_membership_role(
            c, membership_role_id=g.o1_role, campaign_id=g.campaign_id
        ),
    )
    assert revoking.error is None
    assign = _post(
        client_factory, g.o1_user_id, urls["assign_player"], {"role_id": str(g.owner_role_id)}
    )
    _wait_until_waiting(postgres_engine, 1)
    revoking.end(commit=True)
    response = assign.join()
    assert _status(response) == 403, response.text  # type: ignore[attr-defined]

    assert _owners(postgres_engine, g) == {g.o2}
    assert "assign_membership_role" not in _audit(postgres_engine, g)


def test_an_assignment_that_commits_first_makes_the_revocation_wait(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    urls = _urls(g)
    assigning = _park_command(
        postgres_engine,
        lambda c: assign_membership_role(
            c,
            campaign_membership_id=g.player,
            role_id=g.owner_role_id,
            campaign_id=g.campaign_id,
            granted_by_membership_id=g.o1,
        ),
    )
    assert assigning.error is None
    revoke = _post(client_factory, g.o2_user_id, urls["revoke_o1_owner"], {})
    _wait_until_waiting(postgres_engine, 1)
    assigning.end(commit=True)
    assert _status(revoke.join()) == 200

    assert _owners(postgres_engine, g) == {g.o2, g.player}
    assert _audit(postgres_engine, g).get("revoke_membership_role") == 1


def test_a_role_change_and_a_transfer_by_the_same_owner_serialize(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    urls = _urls(g)
    hold = _lock_owner_template(postgres_engine, g)
    change = _post(
        client_factory, g.o1_user_id, urls["change_player"], {"new_role_id": str(g.owner_role_id)}
    )
    _wait_until_waiting(postgres_engine, 1)
    transfer = _post(
        client_factory,
        g.o1_user_id,
        urls["transfer"],
        {"target_campaign_membership_id": str(g.player), "relinquish_own_ownership": True},
    )
    _wait_until_waiting(postgres_engine, 2)
    hold.release()
    assert _status(change.join()) == 201
    transfer_response = transfer.join()
    assert _status(transfer_response) == 200, transfer_response.text  # type: ignore[attr-defined]
    assert transfer_response.json()["assigned"] is False  # type: ignore[attr-defined]
    assert transfer_response.json()["relinquished"] is True  # type: ignore[attr-defined]

    assert _owners(postgres_engine, g) == {g.o2, g.player}
    audit = _audit(postgres_engine, g)
    assert audit.get("change_membership_role") == 1
    assert audit.get("transfer_campaign_ownership") == 1


def test_a_relinquishing_transfer_command_leaves_no_partial_state_when_its_recipient_is_gone(
    postgres_engine: Engine, g: Gate
) -> None:
    """The recipient's eligibility is rechecked under the locks, before anything is written."""
    with postgres_engine.begin() as connection:
        end_campaign_membership(
            connection,
            campaign_membership_id=g.player,
            campaign_id=g.campaign_id,
            ended_by_membership_id=g.o2,
        )
    with pytest.raises(Exception) as excinfo, postgres_engine.begin() as connection:  # noqa: PT011
        transfer_campaign_ownership(
            connection,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            target_campaign_membership_id=g.player,
            relinquish_own_ownership=True,
        )
    assert type(excinfo.value).__name__ == "MembershipNotActiveError"
    assert _owners(postgres_engine, g) == {g.o1, g.o2}
