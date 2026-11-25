# ruff: noqa: F811 - the imported `g` and `client_factory` are pytest fixtures used by parameter name
"""DEF-013: a caller whose built-in owner assignment expires while a gated command waits on a lock.

The HTTP routes check access.manage at entry, lock their rows, then judge ownership as of
transaction start and at a fresh database instant before writing. Park the real request just
before its first role lock to set up a finite expiry. PostgreSQL must report that this request
started waiting on the held target row before expiry and still waits when the deadline passes.
The final case drives the direct transfer command and lets time pass after the recipient write.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, text

from dnd_ai.commands import memberships as memberships_module
from dnd_ai.commands.memberships import CampaignOwnerRequiredError, transfer_campaign_ownership
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    _live_owner_memberships,
    _snapshot,
    client_factory,
    g,
)
from tests.database.test_campaign_owner_lock_order import _owners, _urls
from tests.http_race_support import WAIT_SECONDS, Request, StatementGate, run_in_thread

pytestmark = pytest.mark.database

_EXPIRES_IN_SECONDS = 4


@dataclass(frozen=True)
class _Path:
    url: str
    body: dict[str, object]
    hold_sql: str
    hold_params: dict[str, object]


def _paths(g: Gate) -> dict[str, _Path]:
    urls = _urls(g)
    player_membership = (
        "SELECT 1 FROM security.campaign_memberships WHERE campaign_membership_id = :m FOR UPDATE"
    )
    owner = str(g.owner_role_id)
    return {
        "assign": _Path(
            urls["assign_player"], {"role_id": owner}, player_membership, {"m": g.player}
        ),
        "change": _Path(
            urls["change_player"], {"new_role_id": owner}, player_membership, {"m": g.player}
        ),
        "add_member": _Path(
            f"/campaigns/{g.campaign_id}/memberships",
            {"user_id": str(g.new_user_id), "role_id": owner},
            "SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c FOR UPDATE",
            {"c": g.campaign_id},
        ),
        "transfer": _Path(
            urls["transfer"],
            {"target_campaign_membership_id": str(g.player), "relinquish_own_ownership": True},
            player_membership,
            {"m": g.player},
        ),
        "transfer_keeping_ownership": _Path(
            urls["transfer"],
            {"target_campaign_membership_id": str(g.player)},
            player_membership,
            {"m": g.player},
        ),
    }


_PATH_NAMES = ["assign", "change", "add_member", "transfer", "transfer_keeping_ownership"]


def _set_o1_expiry(engine: Engine, g: Gate, *, seconds: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.membership_roles
                SET expires_at = clock_timestamp() + make_interval(secs => :s)
                WHERE membership_role_id = :r
            """),
            {"s": seconds, "r": g.o1_role},
        )


def _observe_target_wait(
    engine: Engine,
    request: Request,
    *,
    request_pid: int,
    holder_pid: int,
    role_id: uuid.UUID,
    wait_for_caller_expiry: bool,
) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        assert not request.finished(), request.describe()
        with engine.connect() as observer:
            wait = observer.execute(
                text("""
                    SELECT l.waitstart, mr.expires_at, clock_timestamp() AS observed_at
                    FROM pg_locks l CROSS JOIN security.membership_roles mr
                    WHERE l.pid = :request AND NOT l.granted AND l.waitstart IS NOT NULL
                      AND :holder = ANY(pg_blocking_pids(l.pid))
                      AND mr.membership_role_id = :role
                """),
                {"request": request_pid, "holder": holder_pid, "role": role_id},
            ).one_or_none()
        if wait:
            assert wait.waitstart < wait.expires_at, (
                f"caller already expired at lock arrival: {wait}"
            )
            if not wait_for_caller_expiry or wait.expires_at < wait.observed_at:
                return
        time.sleep(0.02)
    raise AssertionError(
        f"expected request pid {request_pid} blocked by {holder_pid}, "
        f"wait_for_caller_expiry={wait_for_caller_expiry}; {request.describe()}"
    )


def _run_while_waiting(
    client_factory: Callable[[uuid.UUID], TestClient],
    engine: Engine,
    g: Gate,
    path: _Path,
    *,
    wait_for_caller_expiry: bool,
) -> Response:
    def post() -> Response:
        with client_factory(g.o1_user_id) as client:
            return client.post(path.url, json=path.body)

    _set_o1_expiry(engine, g, seconds=3600)
    # All five routes lock the actor's role rows after entry. A fixture UPDATE after those
    # locks could itself block. Arm just before the first such SELECT goes to PostgreSQL.
    role_lock = r"^SELECT security\.membership_roles\.membership_role_id FROM security\.membership_roles .* FOR "
    with StatementGate(engine, role_lock, strict=True) as gate:
        request = gate.track(run_in_thread("owner request", post))
        try:
            gate.wait_reached()
            assert gate.pid is not None
            if wait_for_caller_expiry:
                _set_o1_expiry(engine, g, seconds=_EXPIRES_IN_SECONDS)
            # Arm before taking the target lock: committing the fixture UPDATE can itself
            # acquire the campaign row through the deferred access-manager retention trigger.
            with engine.begin() as holder:
                holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
                holder.execute(text(path.hold_sql), path.hold_params).one()
                gate.release()
                _observe_target_wait(
                    engine,
                    request,
                    request_pid=gate.pid,
                    holder_pid=holder_pid,
                    role_id=g.o1_role,
                    wait_for_caller_expiry=wait_for_caller_expiry,
                )
        except AssertionError as failure:
            failure.add_note(request.describe())
            raise
        return request.wait("after releasing the target row")


@pytest.mark.parametrize("name", _PATH_NAMES)
def test_a_caller_who_expires_during_the_lock_wait_is_refused_and_nothing_is_written(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    name: str,
) -> None:
    before = _snapshot(postgres_engine, g)
    owners_before = _owners(postgres_engine, g)

    response = _run_while_waiting(
        client_factory, postgres_engine, g, _paths(g)[name], wait_for_caller_expiry=True
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "campaign_owner_required", response.text
    assert _snapshot(postgres_engine, g) == before
    assert _owners(postgres_engine, g) == owners_before
    with postgres_engine.connect() as connection:
        assert g.player not in _live_owner_memberships(connection, g)


@pytest.mark.parametrize("name", _PATH_NAMES)
def test_a_caller_who_is_still_live_after_the_same_wait_completes(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    name: str,
) -> None:
    before = _snapshot(postgres_engine, g)

    response = _run_while_waiting(
        client_factory, postgres_engine, g, _paths(g)[name], wait_for_caller_expiry=False
    )

    assert response.status_code in (200, 201), response.text
    after = _snapshot(postgres_engine, g)
    # Adding a member audits the membership and its role separately; every other path audits once.
    assert after[2] == before[2] + (2 if name == "add_member" else 1)
    owners = _owners(postgres_engine, g)
    with postgres_engine.connect() as connection:
        new_member_owner = connection.execute(
            text("""
                SELECT cm.campaign_membership_id FROM security.campaign_memberships cm
                WHERE cm.campaign_id = :c AND cm.user_id = :u
            """),
            {"c": g.campaign_id, "u": g.new_user_id},
        ).scalar()
    if name == "add_member":
        assert new_member_owner in owners
    else:
        assert g.player in owners
    if name == "transfer":
        assert g.o1 not in owners and g.o2 in owners
    else:
        assert g.o1 in owners
    if name == "change":
        with postgres_engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT revoked_at IS NOT NULL FROM security.membership_roles WHERE membership_role_id = :r"
                    ),
                    {"r": g.player_role},
                ).scalar_one()
                is True
            )


def test_a_caller_who_expires_after_the_recipient_is_assigned_rolls_the_assignment_back(
    postgres_engine: Engine, g: Gate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first re-check passes. `assign_membership_role` then runs (and, in the real world,
    waits); the caller's assignment expires after it, so the re-check immediately before the
    revoke must refuse and the recipient's new assignment must not survive."""
    _set_o1_expiry(postgres_engine, g, seconds=_EXPIRES_IN_SECONDS)
    real_assign = memberships_module.assign_membership_role

    def assign_then_let_the_caller_expire(connection, **kwargs):  # type: ignore[no-untyped-def]
        result = real_assign(connection, **kwargs)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if connection.execute(
                text(
                    "SELECT clock_timestamp() > expires_at FROM security.membership_roles "
                    "WHERE membership_role_id = :r"
                ),
                {"r": g.o1_role},
            ).scalar_one():
                return result
            time.sleep(0.05)
        raise AssertionError("the assignment never expired")

    monkeypatch.setattr(
        memberships_module, "assign_membership_role", assign_then_let_the_caller_expire
    )
    before = _snapshot(postgres_engine, g)
    with pytest.raises(CampaignOwnerRequiredError), postgres_engine.begin() as connection:
        transfer_campaign_ownership(
            connection,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            target_campaign_membership_id=g.player,
            relinquish_own_ownership=True,
        )
    assert _snapshot(postgres_engine, g) == before
    assert _owners(postgres_engine, g) == {g.o1, g.o2}
