# ruff: noqa: F811 - the imported `g` and `client_factory` are pytest fixtures used by parameter name
"""DEF-011: an ownership transfer to a member whose built-in owner assignment has expired.

An expired assignment that was never revoked still occupies `ux_membership_roles_active` and grants
nothing. The transfer must close it and give the recipient a live assignment, or refuse; it must
never report the recipient as an existing owner and let the caller relinquish. Every scenario runs
in a campaign that also has a custom `access.manage` holder (`Gate.manager`), the case where the
commit-time retention rule would be satisfied even with no owner left.
"""

import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.memberships import MembershipNotActiveError, transfer_campaign_ownership
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    _live_owner_memberships,
    client_factory,
    g,
)
from tests.database.test_campaign_owner_lock_order import (  # noqa: F401 - autouse fixture
    _audit,
    _ended,
    _owners,
    _park_command,
    _post,
    _release_everything,
    _status,
    _urls,
    _wait_until_waiting,
)

pytestmark = pytest.mark.database


def _expire_unrevoked(connection: Connection, membership_role_id: uuid.UUID) -> None:
    """Leaves the row unrevoked but long expired (`expires_at` must stay after `granted_at`)."""
    connection.execute(
        text("""
            UPDATE security.membership_roles
            SET granted_at = now() - interval '2 hours', expires_at = now() - interval '1 hour'
            WHERE membership_role_id = :r
        """),
        {"r": membership_role_id},
    )


def _owner_rows(engine: Engine, g: Gate, membership: uuid.UUID) -> list[dict[str, object]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT membership_role_id, revoked_at IS NOT NULL AS revoked,
                       (expires_at IS NOT NULL AND expires_at <= now()) AS expired
                FROM security.membership_roles
                WHERE campaign_membership_id = :m AND role_id = :owner
                ORDER BY granted_at, membership_role_id
            """),
            {"m": membership, "owner": g.owner_role_id},
        ).mappings()
        return [dict(row) for row in rows]


def _transfer_audit(engine: Engine, g: Gate) -> list[dict[str, object]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT changed_fields FROM audit.change_log
                WHERE world_id = :w AND command_name = 'transfer_campaign_ownership'
            """),
            {"w": g.world_id},
        ).scalars()
        return [dict(row) for row in rows]


@pytest.fixture
def expired_o2(postgres_engine: Engine, g: Gate) -> uuid.UUID:
    """`o2`'s owner row, expired and unrevoked. Returns its id."""
    with postgres_engine.begin() as connection:
        _expire_unrevoked(connection, g.o2_role)
    with postgres_engine.connect() as connection:
        assert _live_owner_memberships(connection, g) >= {g.o1, g.o2}  # still "unrevoked"
    return g.o2_role


def test_a_relinquishing_transfer_replaces_the_recipients_expired_assignment(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    expired_o2: uuid.UUID,
) -> None:
    with client_factory(g.o1_user_id) as client:
        response = client.post(
            f"/campaigns/{g.campaign_id}/ownership-transfer",
            json={"target_campaign_membership_id": str(g.o2), "relinquish_own_ownership": True},
        )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "target_campaign_membership_id": str(g.o2),
        "assigned": True,
        "relinquished": True,
    }

    recipient = _owner_rows(postgres_engine, g, g.o2)
    assert len(recipient) == 2
    old, new = recipient
    assert old["membership_role_id"] == expired_o2 and old["revoked"] is True
    assert new["revoked"] is False and new["expired"] is False
    assert [row["revoked"] for row in _owner_rows(postgres_engine, g, g.o1)] == [True]
    with postgres_engine.connect() as connection:
        live = connection.execute(
            text("""
                SELECT campaign_membership_id FROM security.membership_roles mr
                WHERE mr.role_id = :owner AND mr.revoked_at IS NULL
                  AND (mr.expires_at IS NULL OR mr.expires_at > now())
                  AND mr.campaign_membership_id IN (
                      SELECT campaign_membership_id FROM security.campaign_memberships
                      WHERE campaign_id = :c)
            """),
            {"owner": g.owner_role_id, "c": g.campaign_id},
        ).scalars()
        assert set(live) == {g.o2}
    assert _transfer_audit(postgres_engine, g) == [
        {"assigned": True, "relinquished": True, "replaced_expired_assignment": True}
    ]


def test_a_non_relinquishing_transfer_also_replaces_the_expired_assignment(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    expired_o2: uuid.UUID,
) -> None:
    with client_factory(g.o1_user_id) as client:
        response = client.post(
            f"/campaigns/{g.campaign_id}/ownership-transfer",
            json={"target_campaign_membership_id": str(g.o2)},
        )
    assert response.status_code == 200, response.text
    assert response.json()["assigned"] is True
    assert response.json()["relinquished"] is False
    assert [row["revoked"] for row in _owner_rows(postgres_engine, g, g.o2)] == [True, False]
    assert [row["revoked"] for row in _owner_rows(postgres_engine, g, g.o1)] == [False]
    assert _transfer_audit(postgres_engine, g) == [
        {"assigned": True, "relinquished": False, "replaced_expired_assignment": True}
    ]


def test_repeating_the_transfer_after_the_replacement_changes_nothing(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    expired_o2: uuid.UUID,
) -> None:
    url = f"/campaigns/{g.campaign_id}/ownership-transfer"
    body = {"target_campaign_membership_id": str(g.o2), "relinquish_own_ownership": True}
    with client_factory(g.o1_user_id) as client:
        first = client.post(url, json=body)
        rows_after_first = _owner_rows(postgres_engine, g, g.o2)
        audit_after_first = _transfer_audit(postgres_engine, g)
        second = client.post(url, json=body)
    assert first.status_code == 200
    # The caller is no longer an owner, so the repeat is refused by the D3 gate, not applied twice.
    assert second.status_code == 403, second.text
    assert _owner_rows(postgres_engine, g, g.o2) == rows_after_first
    assert _transfer_audit(postgres_engine, g) == audit_after_first
    assert len(audit_after_first) == 1


def test_a_transfer_to_a_live_owner_keeps_the_existing_assignment(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    before = _owner_rows(postgres_engine, g, g.o2)
    with client_factory(g.o1_user_id) as client:
        response = client.post(
            f"/campaigns/{g.campaign_id}/ownership-transfer",
            json={"target_campaign_membership_id": str(g.o2), "relinquish_own_ownership": True},
        )
    assert response.status_code == 200, response.text
    assert response.json()["assigned"] is False
    assert response.json()["relinquished"] is True
    assert _owner_rows(postgres_engine, g, g.o2) == before
    assert _transfer_audit(postgres_engine, g) == [
        {"assigned": False, "relinquished": True, "replaced_expired_assignment": False}
    ]


def test_an_ineligible_recipient_with_an_expired_row_is_refused_and_nothing_is_kept(
    postgres_engine: Engine, g: Gate, expired_o2: uuid.UUID
) -> None:
    """The recipient's membership has ended, so no live assignment can be established. The refusal
    is atomic: the caller keeps ownership and the expired row is not half-revoked."""
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.campaign_memberships SET ended_at = now() "
                "WHERE campaign_membership_id = :m"
            ),
            {"m": g.o2},
        )
    before = _owner_rows(postgres_engine, g, g.o2)
    with pytest.raises(MembershipNotActiveError), postgres_engine.begin() as connection:
        transfer_campaign_ownership(
            connection,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            target_campaign_membership_id=g.o2,
            relinquish_own_ownership=True,
        )
    assert _owner_rows(postgres_engine, g, g.o2) == before
    assert [row["revoked"] for row in _owner_rows(postgres_engine, g, g.o1)] == [False]
    assert _transfer_audit(postgres_engine, g) == []


def test_ending_the_recipient_first_refuses_the_transfer_without_a_deadlock(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    expired_o2: uuid.UUID,
) -> None:
    """The end locks the recipient's role rows (the expired one included) before the membership.
    The transfer takes the same rows in the same order, so it waits on the role row, not the
    membership, and then finds a recipient who is gone."""
    from dnd_ai.commands.memberships import end_campaign_membership

    urls = _urls(g)
    ending = _park_command(
        postgres_engine,
        lambda c: end_campaign_membership(
            c,
            campaign_membership_id=g.o2,
            campaign_id=g.campaign_id,
            ended_by_membership_id=g.manager,
        ),
    )
    assert ending.error is None
    transfer = _post(
        client_factory,
        g.o1_user_id,
        urls["transfer"],
        {"target_campaign_membership_id": str(g.o2), "relinquish_own_ownership": True},
    )
    _wait_until_waiting(postgres_engine, 1)
    ending.end(commit=True)
    response = transfer.join()
    assert _status(response) == 409, response.text  # type: ignore[attr-defined]

    assert _owners(postgres_engine, g) == {g.o1}
    assert _ended(postgres_engine, g) == {g.o2}
    assert _audit(postgres_engine, g).get("transfer_campaign_ownership") is None
    assert _transfer_audit(postgres_engine, g) == []
