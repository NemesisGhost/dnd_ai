# ruff: noqa: F811 - the imported `g` and `client_factory` are pytest fixtures used by parameter name
"""DEF-013: a caller whose built-in owner assignment expires while a gated command waits on a lock.

The D3 gate judges the caller when the command starts and locks the assignment, but a finite
`expires_at` still passes while the command waits on its other locks. Each gated command now judges
the caller again, at a fresh database instant, after its last lock wait and before its first
protected write (design §3, "Time boundary"). A caller who expired meanwhile gets 403
`campaign_owner_required` with nothing written and no audit row; one who is still live completes.

Deterministic: the test holds the row the command waits for, waits on the database clock until the
caller's assignment has expired, and only then releases the command. The other order, expiry
between the first re-check and the transfer's revoke, is made by delaying `assign_membership_role`.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
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
from tests.database.test_campaign_owner_lock_order import (  # noqa: F401 - autouse fixture
    _Hold,
    _owners,
    _post,
    _release_everything,
    _status,
    _urls,
    _wait_until_waiting,
)

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


def _set_o1_expiry(engine: Engine, g: Gate, *, seconds: int | None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.membership_roles
                SET expires_at = CASE WHEN CAST(:s AS int) IS NULL THEN NULL
                                      ELSE clock_timestamp() + make_interval(secs => :s) END
                WHERE membership_role_id = :r
            """),
            {"s": seconds, "r": g.o1_role},
        )


def _wait_for_expiry(engine: Engine, membership_role_id: uuid.UUID) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            if connection.execute(
                text(
                    "SELECT clock_timestamp() > expires_at FROM security.membership_roles "
                    "WHERE membership_role_id = :r"
                ),
                {"r": membership_role_id},
            ).scalar_one():
                return
        time.sleep(0.05)
    raise AssertionError("the assignment never expired")


def _run_while_waiting(
    client_factory: Callable[[uuid.UUID], TestClient],
    engine: Engine,
    g: Gate,
    path: _Path,
    *,
    wait_for_caller_expiry: bool,
) -> object:
    """Starts the o1 request, parks it on the row it needs, optionally lets o1's assignment
    expire, then releases it and returns the response."""
    hold = _Hold(engine, path.hold_sql, path.hold_params)
    request = _post(client_factory, g.o1_user_id, path.url, path.body)
    _wait_until_waiting(engine, 1)
    if wait_for_caller_expiry:
        _wait_for_expiry(engine, g.o1_role)
    hold.release()
    return request.join()


@pytest.mark.parametrize("name", _PATH_NAMES)
def test_a_caller_who_expires_during_the_lock_wait_is_refused_and_nothing_is_written(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    name: str,
) -> None:
    _set_o1_expiry(postgres_engine, g, seconds=_EXPIRES_IN_SECONDS)
    before = _snapshot(postgres_engine, g)
    owners_before = _owners(postgres_engine, g)

    response = _run_while_waiting(
        client_factory, postgres_engine, g, _paths(g)[name], wait_for_caller_expiry=True
    )

    assert _status(response) == 403, response.text  # type: ignore[attr-defined]
    assert "campaign_owner_required" in response.text  # type: ignore[attr-defined]
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
    _set_o1_expiry(postgres_engine, g, seconds=3600)
    before = _snapshot(postgres_engine, g)

    response = _run_while_waiting(
        client_factory, postgres_engine, g, _paths(g)[name], wait_for_caller_expiry=False
    )

    assert _status(response) in (200, 201), response.text  # type: ignore[attr-defined]
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
