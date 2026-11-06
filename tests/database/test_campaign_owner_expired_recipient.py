# ruff: noqa: F811 - the imported `g` and `client_factory` are pytest fixtures used by parameter name
"""DEF-011: an ownership transfer to a member whose built-in owner assignment has expired.

An expired assignment that was never revoked still occupies `ux_membership_roles_active` and grants
nothing. The transfer must close it and give the recipient a live assignment, or refuse; it must
never report the recipient as an existing owner and let the caller relinquish. Every scenario runs
in a campaign that also has a custom `access.manage` holder (`Gate.manager`), the case where the
commit-time retention rule would be satisfied even with no owner left.
"""

import time
import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.memberships import (
    MembershipNotActiveError,
    end_campaign_membership,
    revoke_membership_role,
    transfer_campaign_ownership,
)
from dnd_ai.domain.access import find_live_builtin_owner_assignment
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    _live_owner_memberships,
    client_factory,
    g,
)
from tests.database.test_campaign_owner_lock_order import (  # noqa: F401 - autouse fixture
    _WAIT_SECONDS,
    _audit,
    _ended,
    _Hold,
    _owners,
    _park_command,
    _post,
    _release_everything,
    _Request,
    _status,
    _urls,
    _wait_until_waiting,
)
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_user,
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


# --- review probes: the recipient check is the shared live-owner definition, read late -----------


def _live_owners(engine: Engine, g: Gate) -> set[uuid.UUID]:
    """Memberships of the campaign that are live built-in owners by the shared definition
    (`find_live_builtin_owner_assignment`), not merely holders of an unrevoked row."""
    with engine.connect() as connection:
        memberships = list(
            connection.execute(
                text(
                    "SELECT campaign_membership_id FROM security.campaign_memberships "
                    "WHERE campaign_id = :c"
                ),
                {"c": g.campaign_id},
            ).scalars()
        )
        return {
            membership
            for membership in memberships
            if find_live_builtin_owner_assignment(
                connection, campaign_id=g.campaign_id, campaign_membership_id=membership
            )
            is not None
        }


def _row_state(engine: Engine, membership_role_id: uuid.UUID) -> tuple[bool, bool]:
    """(revoked, expired now) for one assignment row."""
    with engine.connect() as connection:
        row = connection.execute(
            text("""
                SELECT revoked_at IS NOT NULL,
                       expires_at IS NOT NULL AND expires_at <= clock_timestamp()
                FROM security.membership_roles WHERE membership_role_id = :r
            """),
            {"r": membership_role_id},
        ).one()
    return (bool(row[0]), bool(row[1]))


def _wait_until_expired(engine: Engine, membership_role_id: uuid.UUID) -> None:
    """Polls the database clock (not a fixed sleep) until the row's `expires_at` has passed."""
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        if _row_state(engine, membership_role_id)[1]:
            return
        time.sleep(0.05)
    raise AssertionError("the assignment did not expire in time")


def _hold_membership(engine: Engine, membership: uuid.UUID) -> _Hold:
    return _Hold(
        engine,
        "SELECT 1 FROM security.campaign_memberships WHERE campaign_membership_id = :m FOR SHARE",
        {"m": membership},
    )


def _transfer_to(
    client_factory: Callable[[uuid.UUID], TestClient], g: Gate, target: uuid.UUID
) -> _Request:
    return _post(
        client_factory,
        g.o1_user_id,
        _urls(g)["transfer"],
        {"target_campaign_membership_id": str(target), "relinquish_own_ownership": True},
    )


def test_a_recipient_assignment_that_expires_while_the_transfer_waits_refuses_it(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    """Probe 1. The recipient's owner row is live when the transfer starts and expires while the
    transfer waits for the recipient's membership lock. Replacing it would mean locking a role row
    after the membership, against the reviewed order, so the transfer is refused and the caller
    keeps ownership. Before the fix the check used the transaction-start `now()`, saw the row as
    live, reported `assigned: false` and relinquished."""
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.membership_roles
                SET granted_at = clock_timestamp() - interval '1 hour',
                    expires_at = clock_timestamp() + interval '3 seconds'
                WHERE membership_role_id = :r
            """),
            {"r": g.o2_role},
        )
    hold = _hold_membership(postgres_engine, g.o2)
    transfer = _transfer_to(client_factory, g, g.o2)
    _wait_until_waiting(postgres_engine, 1)
    assert _row_state(postgres_engine, g.o2_role) == (False, False), "set-up too slow"
    _wait_until_expired(postgres_engine, g.o2_role)
    hold.release()
    response = transfer.join()

    assert _status(response) == 409, response.text  # type: ignore[attr-defined]
    assert response.json()["error"]["code"] == "ownership_transfer_recipient_changed"  # type: ignore[attr-defined]
    assert _live_owners(postgres_engine, g) == {g.o1}
    assert _row_state(postgres_engine, g.o1_role) == (False, False)
    assert _row_state(postgres_engine, g.o2_role) == (False, True)  # untouched, still unrevoked
    assert _transfer_audit(postgres_engine, g) == []


def test_a_recipient_with_an_owner_row_but_an_inactive_account_is_refused(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    """Probe 2. An unrevoked, unexpired owner row on an inactive account is not a live owner. The
    transfer must try to assign, which refuses the account, instead of reporting an existing owner
    and relinquishing."""
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.users SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'inactive')
                WHERE user_id = :u
            """),
            {"u": g.o2_user_id},
        )
    response = _transfer_to(client_factory, g, g.o2).join()

    assert _status(response) == 409, response.text  # type: ignore[attr-defined]
    assert response.json()["error"]["code"] == "conflict"  # type: ignore[attr-defined]
    assert _live_owners(postgres_engine, g) == {g.o1}
    assert _row_state(postgres_engine, g.o1_role) == (False, False)
    assert _row_state(postgres_engine, g.o2_role) == (False, False)
    assert _transfer_audit(postgres_engine, g) == []


def test_a_recipient_whose_owner_row_belongs_to_another_campaign_is_refused(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    """Probe 3. The target membership owns a different campaign and is not a member here. The
    transfer is refused as not found, and the caller, left as the only built-in owner (the custom
    manager alone would satisfy the retention rule), keeps ownership."""
    with postgres_engine.begin() as connection:
        revoke_membership_role(connection, membership_role_id=g.o2_role, campaign_id=g.campaign_id)
        other_campaign = make_campaign(
            connection, g.timeline_id, "Other Campaign", lifecycle_status_code="active"
        )
        outsider_user = make_user(connection, "Owner Elsewhere")
        outsider = make_campaign_membership(connection, other_campaign, outsider_user)
        outsider_role = make_membership_role(connection, outsider, g.owner_role_id)
    response = _transfer_to(client_factory, g, outsider).join()

    assert _status(response) == 404, response.text  # type: ignore[attr-defined]
    assert _live_owners(postgres_engine, g) == {g.o1}
    assert _row_state(postgres_engine, g.o1_role) == (False, False)
    assert _row_state(postgres_engine, outsider_role) == (False, False)
    assert _transfer_audit(postgres_engine, g) == []


def test_a_recipient_revocation_committed_during_the_wait_is_seen_and_replaced(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    """A revocation of the recipient's owner row that commits while the transfer waits for the
    recipient's membership is read by the check after the wait: the recipient gets a fresh live
    row and only then does the caller relinquish."""
    hold = _hold_membership(postgres_engine, g.o2)
    transfer = _transfer_to(client_factory, g, g.o2)
    _wait_until_waiting(postgres_engine, 1)
    with postgres_engine.begin() as connection:
        revoke_membership_role(connection, membership_role_id=g.o2_role, campaign_id=g.campaign_id)
    hold.release()
    response = transfer.join()

    assert _status(response) == 200, response.text  # type: ignore[attr-defined]
    assert response.json() == {  # type: ignore[attr-defined]
        "target_campaign_membership_id": str(g.o2),
        "assigned": True,
        "relinquished": True,
    }
    assert _live_owners(postgres_engine, g) == {g.o2}
    assert _row_state(postgres_engine, g.o2_role) == (True, False)
    assert _transfer_audit(postgres_engine, g) == [
        {"assigned": True, "relinquished": True, "replaced_expired_assignment": False}
    ]


def test_a_recipient_revocation_in_flight_cannot_commit_before_the_transfer(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    """The transfer holds the campaign row from before its recipient check until it commits. A
    revocation of the recipient takes that row at commit (the retention trigger), so it cannot
    commit between the check and the caller's relinquishment: it waits, then applies after the
    handoff, which is the serial order. That a later revocation may remove the last built-in owner
    while a custom manager remains is outside DEF-011 (design §3, "Left out on purpose")."""
    transferring = _park_command(
        postgres_engine,
        lambda c: transfer_campaign_ownership(
            c,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            target_campaign_membership_id=g.o2,
            relinquish_own_ownership=True,
        ),
    )
    assert transferring.error is None
    revoke = _post(
        client_factory,
        g.manager_user_id,
        f"/campaigns/{g.campaign_id}/memberships/roles/{g.o2_role}/revoke",
        {},
    )
    _wait_until_waiting(postgres_engine, 1)
    assert not revoke.done, "the revocation must wait for the transfer to commit"
    assert _live_owners(postgres_engine, g) == {g.o1, g.o2}
    transferring.end(commit=True)
    assert _status(revoke.join()) == 200

    assert _row_state(postgres_engine, g.o1_role) == (True, False)
    assert _row_state(postgres_engine, g.o2_role) == (True, False)
    assert _audit(postgres_engine, g).get("revoke_membership_role") == 1


def test_ending_a_live_owner_recipient_first_refuses_the_transfer(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    """The recipient is already an owner. Its membership end commits while the transfer waits for
    that membership, so the check after the wait finds no live owner, the assignment refuses the
    ended membership and the caller keeps ownership."""
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
    transfer = _transfer_to(client_factory, g, g.o2)
    _wait_until_waiting(postgres_engine, 1)
    ending.end(commit=True)
    response = transfer.join()

    assert _status(response) == 409, response.text  # type: ignore[attr-defined]
    assert _live_owners(postgres_engine, g) == {g.o1}
    assert _ended(postgres_engine, g) == {g.o2}
    assert _transfer_audit(postgres_engine, g) == []
