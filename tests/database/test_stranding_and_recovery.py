"""Stranded worlds and campaigns, ownership transfer and recovery
(docs/adr/0020-scoped-system-world-and-campaign-roles.md, checkpoint SR-6; finding F5).

Disabling an account, or revoking system GM, can leave a world or campaign with
nobody who can manage it, and the database retention triggers cannot see that. The
disabling administrator is told the affected IDs; the recovery commands then restore
a manager, refusing a healthy aggregate and requiring a reason.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands.local_auth import NotPlatformAdministratorError
from dnd_ai.commands.recovery import (
    RecoveryNotNeededError,
    recover_campaign_access_manager,
    recover_world_ownership,
)
from dnd_ai.commands.world_access import TargetRequiresSystemGmError
from dnd_ai.domain.authoring import WorldAuthorityRequiredError  # noqa: F401
from dnd_ai.queries.stranded import stranded_campaign_ids_for_manager, stranded_world_ids_for_owner
from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup, add_member
from tests.factories import make_system_role_assignment

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def _admin(harness: AuthoringHarness) -> Actor:
    return harness.new_actor("Recovery Admin", system_roles=("admin",))


def _membership_id(connection: Connection, campaign_id: str, user_id: uuid.UUID) -> uuid.UUID:
    value = connection.execute(
        text(
            "SELECT campaign_membership_id FROM security.campaign_memberships "
            "WHERE campaign_id = :c AND user_id = :u AND ended_at IS NULL"
        ),
        {"c": campaign_id, "u": user_id},
    ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


# --- stranded reporting -------------------------------------------------------------------


def test_disabling_the_sole_owner_reports_the_world_and_the_campaign(
    s: ContentSetup, harness: AuthoringHarness
) -> None:
    admin = _admin(harness)
    response = admin.post(f"/admin/accounts/{s.gm.user_id}/disable", {})
    assert response.status_code == 200, response.text
    stranded = response.json()["stranded"]
    assert str(s.world_id) in stranded["world_ids"]
    assert s.cid in stranded["campaign_ids"]

    listed = admin.get("/admin/accounts", q="GM").json()["items"]
    mine = next(a for a in listed if a["user_id"] == str(s.gm.user_id))
    assert mine["stranded_world_count"] >= 1


def test_revoking_system_gm_reports_the_world_but_leaves_campaign_roles(
    s: ContentSetup, harness: AuthoringHarness, db_connection: Connection
) -> None:
    admin = _admin(harness)
    response = admin.post(f"/admin/accounts/{s.gm.user_id}/system-roles/gm/revoke", {})
    assert response.status_code == 200, response.text
    assert str(s.world_id) in response.json()["stranded_world_ids"]
    # Campaign scope is untouched: the same account still runs its campaign.
    assert s.gm.get(f"/campaigns/{s.cid}/clock").status_code == 200
    assert stranded_campaign_ids_for_manager(db_connection, user_id=s.gm.user_id) == []


def test_a_healthy_world_is_never_reported(s: ContentSetup, db_connection: Connection) -> None:
    assert stranded_world_ids_for_owner(db_connection, user_id=s.gm.user_id) == []


# --- world recovery ------------------------------------------------------------------------


def test_world_recovery_refuses_a_healthy_world_and_a_non_administrator(
    s: ContentSetup, harness: AuthoringHarness, db_connection: Connection
) -> None:
    admin = _admin(harness)
    heir = harness.new_actor("Heir", system_roles=("gm",))
    with pytest.raises(RecoveryNotNeededError):
        recover_world_ownership(
            db_connection,
            admin_user_id=admin.user_id,
            world_id=s.world_id,
            new_owner_user_id=heir.user_id,
            reason="not needed",
        )
    with pytest.raises(NotPlatformAdministratorError):
        recover_world_ownership(
            db_connection,
            admin_user_id=s.gm.user_id,
            world_id=s.world_id,
            new_owner_user_id=heir.user_id,
            reason="not an admin",
        )


def test_world_recovery_restores_ownership_for_a_gm_with_a_reason(
    s: ContentSetup, harness: AuthoringHarness, db_connection: Connection
) -> None:
    admin = _admin(harness)
    heir = harness.new_actor("Heir", system_roles=("gm",))
    plain = harness.new_actor("Plain")
    admin.post(f"/admin/accounts/{s.gm.user_id}/disable", {})

    with pytest.raises(ValueError):  # the reason is mandatory
        recover_world_ownership(
            db_connection,
            admin_user_id=admin.user_id,
            world_id=s.world_id,
            new_owner_user_id=heir.user_id,
            reason="   ",
        )
    with pytest.raises(TargetRequiresSystemGmError):
        recover_world_ownership(
            db_connection,
            admin_user_id=admin.user_id,
            world_id=s.world_id,
            new_owner_user_id=plain.user_id,
            reason="plain account",
        )
    result = recover_world_ownership(
        db_connection,
        admin_user_id=admin.user_id,
        world_id=s.world_id,
        new_owner_user_id=heir.user_id,
        reason="Previous owner left",
    )
    assert result.world_membership_id is not None
    assert stranded_world_ids_for_owner(db_connection, user_id=s.gm.user_id) == []
    assert heir.get(f"/worlds/{s.world_id}").status_code == 200
    # The previous owner's assignment and everything they authored is untouched.
    assert (
        db_connection.execute(
            text(
                "SELECT count(*) FROM security.world_memberships "
                "WHERE world_id = :w AND user_id = :u AND ended_at IS NULL"
            ),
            {"w": s.world_id, "u": s.gm.user_id},
        ).scalar_one()
        == 1
    )


def test_recovery_grants_the_administrator_nothing_to_read(
    s: ContentSetup, harness: AuthoringHarness
) -> None:
    admin = harness.new_actor("Super Admin", system_roles=("admin", "gm"))
    assert admin.get(f"/worlds/{s.world_id}").status_code == 404
    for path in ("clock", "sessions", "review-queue", "sources"):
        assert admin.get(f"/campaigns/{s.cid}/{path}").status_code == 404, path


# --- campaign recovery -----------------------------------------------------------------------


def test_campaign_recovery_needs_a_stranded_campaign_and_assigns_the_owner_role(
    s: ContentSetup, harness: AuthoringHarness, db_connection: Connection
) -> None:
    admin = _admin(harness)
    rescuer = harness.new_actor("Rescuer")
    with pytest.raises(RecoveryNotNeededError):
        recover_campaign_access_manager(
            db_connection,
            admin_user_id=admin.user_id,
            campaign_id=uuid.UUID(s.cid),
            new_user_id=rescuer.user_id,
            reason="healthy",
        )
    admin.post(f"/admin/accounts/{s.gm.user_id}/disable", {})
    result = recover_campaign_access_manager(
        db_connection,
        admin_user_id=admin.user_id,
        campaign_id=uuid.UUID(s.cid),
        new_user_id=rescuer.user_id,
        reason="GM left the group",
    )
    assert result.membership_role_id is not None
    assert stranded_campaign_ids_for_manager(db_connection, user_id=s.gm.user_id) == []
    assert rescuer.get(f"/campaigns/{s.cid}/settings").status_code == 200


# --- campaign ownership transfer -------------------------------------------------------------


def test_campaign_ownership_transfer_keeps_authorship_and_the_gm_role(
    s: ContentSetup, harness: AuthoringHarness, db_connection: Connection
) -> None:
    successor = harness.new_actor("Successor")
    add_member(db_connection, s.cid, successor.user_id, "gm")
    target = _membership_id(db_connection, s.cid, successor.user_id)
    session_before = s.gm.post(f"/campaigns/{s.cid}/sessions", {}, key=s.gm.fresh_key()).json()

    done = s.gm.post(
        f"/campaigns/{s.cid}/ownership-transfer",
        {"target_campaign_membership_id": str(target), "relinquish_own_ownership": True},
    )
    assert done.status_code == 200, done.text
    assert done.json() == {
        "target_campaign_membership_id": str(target),
        "assigned": True,
        "relinquished": True,
    }
    roles = {
        r.code
        for r in db_connection.execute(
            text("""
                SELECT r.code FROM security.membership_roles mr
                JOIN security.roles r ON r.role_id = mr.role_id
                WHERE mr.campaign_membership_id = :m AND mr.revoked_at IS NULL
            """),
            {"m": _membership_id(db_connection, s.cid, s.gm.user_id)},
        )
    }
    assert roles == {"gm"}
    # The previous owner can no longer administer access, but their authorship stays.
    assert s.gm.get(f"/campaigns/{s.cid}/settings").status_code == 403
    assert (
        db_connection.execute(
            text("SELECT created_by_user_id FROM campaign.sessions WHERE session_id = :s"),
            {"s": session_before["session_id"]},
        ).scalar_one()
        == s.gm.user_id
    )
    assert successor.get(f"/campaigns/{s.cid}/settings").status_code == 200
    # A repeat changes nothing and writes no second audit row.
    audits = db_connection.execute(
        text(
            "SELECT count(*) FROM audit.change_log WHERE command_name = 'transfer_campaign_ownership'"
        )
    ).scalar_one()
    again = successor.post(
        f"/campaigns/{s.cid}/ownership-transfer",
        {"target_campaign_membership_id": str(target), "relinquish_own_ownership": False},
    )
    assert again.json()["assigned"] is False
    assert (
        db_connection.execute(
            text(
                "SELECT count(*) FROM audit.change_log WHERE command_name = 'transfer_campaign_ownership'"
            )
        ).scalar_one()
        == audits
    )


def test_a_non_owner_cannot_transfer_campaign_ownership(
    s: ContentSetup, harness: AuthoringHarness, db_connection: Connection
) -> None:
    target = _membership_id(db_connection, s.cid, s.player.user_id)
    response = s.player.post(
        f"/campaigns/{s.cid}/ownership-transfer",
        {"target_campaign_membership_id": str(target), "relinquish_own_ownership": False},
    )
    assert response.status_code == 403


# --- campaign roles have no system-role gate (D11) -------------------------------------------------


def test_any_active_account_may_hold_a_campaign_gm_or_owner_role_without_system_gm(
    s: ContentSetup, harness: AuthoringHarness, db_connection: Connection
) -> None:
    plain = harness.new_actor("Plain Player Account")
    add_member(db_connection, s.cid, plain.user_id, "gm")
    target = _membership_id(db_connection, s.cid, plain.user_id)
    done = s.gm.post(
        f"/campaigns/{s.cid}/ownership-transfer",
        {"target_campaign_membership_id": str(target), "relinquish_own_ownership": False},
    )
    assert done.status_code == 200, done.text
    # ... and holding them confers no system capability.
    assert "world.create" not in plain.get("/auth/session").json()["global_capabilities"]
    make_system_role_assignment(db_connection, plain.user_id, "observer")
