"""Tests for `dnd_ai.api.memberships` — Phase 10 workstream 20's command
endpoints over `dnd_ai.commands.memberships` (docs/PLAN.md Phase 10
"OIDC-backed login integration for dev, authenticated user mapping,
campaign invitations/memberships, campaign-scoped multi-role assignment,
capabilities, and access revocation"). Mirrors `tests/database/
test_api_quests.py`'s shape: `get_authenticated_user_id` is overridden
directly, since these tests exercise campaign-capability enforcement and
the commands' own HTTP wiring, not OIDC token verification.

Covers: access control (non-member 404, capless-member 403), membership
creation (success, duplicate-open-membership 409), role assignment
(campaign-scoped role, system-template role, a role scoped to a different
campaign rejected, a membership from a different campaign rejected,
duplicate active assignment 409), role revocation (success, idempotent
no-op retry, cross-campaign rejection, the access.manage retention
invariant on an *active* campaign), and idempotent replay for the two
create-shaped commands.
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        # "pending" sidesteps the active-campaign access-manager retention
        # invariant for most of these tests — see test_api_quests.py's
        # Fixture for the identical reasoning. A dedicated *active*
        # campaign below exercises the invariant directly.
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.other_campaign_id = make_campaign(
            connection, self.timeline_id, "Other Campaign", lifecycle_status_code="pending"
        )

        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )

        admin_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"admin_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, admin_role_id, access_manage_id)
        make_role_capability(connection, admin_role_id, view_capability_id)

        self.admin_user_id = make_user(connection, "Membership API Admin")
        self.admin_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.admin_user_id
        )
        make_membership_role(connection, self.admin_membership_id, admin_role_id)

        # A plain campaign-scoped role, usable only by self.campaign_id.
        self.player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        # A system-template role (campaign_id NULL) — usable by any campaign.
        self.system_role_id = make_role(
            connection, campaign_id=None, code=f"system_{uuid.uuid4().hex[:8]}"
        )
        # Scoped to the *other* campaign — not usable by self.campaign_id.
        self.foreign_role_id = make_role(
            connection, campaign_id=self.other_campaign_id, code=f"foreign_{uuid.uuid4().hex[:8]}"
        )

        # A user with no membership yet — the target of a create-membership call.
        self.new_user_id = make_user(connection, "Membership API New User")

        # An already-active member — the target of assign/revoke-role calls.
        self.existing_user_id = make_user(connection, "Membership API Existing Member")
        self.existing_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.existing_user_id
        )

        # A membership belonging only to the *other* campaign.
        foreign_membership_user_id = make_user(connection, "Membership API Foreign Member")
        self.foreign_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, foreign_membership_user_id
        )

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Membership API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Membership API Outsider")

        # --- A genuinely active campaign, to exercise the access.manage
        # retention invariant directly (it only applies to active
        # campaigns — see dnd_ai.commands.memberships.
        # revoke_membership_role's own docstring). ---
        self.active_campaign_id = make_campaign(
            connection, self.timeline_id, "Active Campaign", lifecycle_status_code="active"
        )
        active_owner_role_id = make_role(
            connection, campaign_id=self.active_campaign_id, code=f"owner_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, active_owner_role_id, access_manage_id)
        make_role_capability(connection, active_owner_role_id, view_capability_id)
        self.active_admin_user_id = make_user(connection, "Membership API Active Admin")
        self.active_admin_membership_id = make_campaign_membership(
            connection, self.active_campaign_id, self.active_admin_user_id
        )
        self.active_admin_membership_role_id = make_membership_role(
            connection, self.active_admin_membership_id, active_owner_role_id
        )


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"membership-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        # See tests/database/test_api_dungeon.py's identical cleanup
        # comment for why session_replication_role = replica and explicit,
        # dependency-ordered deletes are used here.
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        # system_role_id (campaign_id NULL) is a global lookup-shaped row,
        # not scoped by world/timeline like every other role here — deleted
        # explicitly by id, the same discipline other fixtures already
        # apply to global lookup rows (see tests/database/
        # test_api_characters.py's character_relationship_types cleanup).
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                ) OR role_id = :system_role
            """),
            {"t": fixture.timeline_id, "system_role": fixture.system_role_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.roles WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM security.roles WHERE role_id = :system_role"),
            {"system_role": fixture.system_role_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.idempotent_requests WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.campaign_memberships WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.admin_user_id,
                    fixture.new_user_id,
                    fixture.existing_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                    fixture.active_admin_user_id,
                ]
            },
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: user_id
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _memberships_url(f: Fixture, campaign_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/memberships"


def _roles_url(
    f: Fixture, membership_id: uuid.UUID | None = None, campaign_id: uuid.UUID | None = None
) -> str:
    return (
        f"/campaigns/{campaign_id or f.campaign_id}/memberships/"
        f"{membership_id or f.existing_membership_id}/roles"
    )


def _revoke_url(
    f: Fixture, membership_role_id: uuid.UUID, campaign_id: uuid.UUID | None = None
) -> str:
    return (
        f"/campaigns/{campaign_id or f.campaign_id}/memberships/roles/{membership_role_id}/revoke"
    )


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(_memberships_url(f), json={"user_id": str(f.new_user_id)})
    assert response.status_code == 404


def test_a_member_without_access_manage_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(_memberships_url(f), json={"user_id": str(f.new_user_id)})
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# create_campaign_membership
# ---------------------------------------------------------------------------


def test_creating_a_membership_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_memberships_url(f), json={"user_id": str(f.new_user_id)})
    assert response.status_code == 201, response.text
    membership_id = uuid.UUID(response.json()["campaign_membership_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT cm.user_id, cm.ended_at, ms.code
                FROM security.campaign_memberships cm
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                WHERE cm.campaign_membership_id = :m
            """),
            {"m": membership_id},
        ).one()
        assert row.user_id == f.new_user_id
        assert row.ended_at is None
        assert row.code == "active"


def test_creating_a_duplicate_open_membership_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_memberships_url(f), json={"user_id": str(f.existing_user_id)})
    assert response.status_code == 409, response.text


def test_a_sequential_replay_of_create_membership_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    key = f"create-membership-{uuid.uuid4().hex[:8]}"
    body = {"user_id": str(f.new_user_id)}
    with client_factory(f.admin_user_id) as client:
        first = client.post(_memberships_url(f), json=body, headers={"Idempotency-Key": key})
        second = client.post(_memberships_url(f), json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()


# ---------------------------------------------------------------------------
# assign_membership_role
# ---------------------------------------------------------------------------


def test_assigning_a_campaign_scoped_role_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_roles_url(f), json={"role_id": str(f.player_role_id)})
    assert response.status_code == 201, response.text
    membership_role_id = uuid.UUID(response.json()["membership_role_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT role_id, granted_by_membership_id, revoked_at "
                "FROM security.membership_roles WHERE membership_role_id = :mr"
            ),
            {"mr": membership_role_id},
        ).one()
        assert row.role_id == f.player_role_id
        assert row.granted_by_membership_id == f.admin_membership_id
        assert row.revoked_at is None


def test_assigning_a_system_template_role_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_roles_url(f), json={"role_id": str(f.system_role_id)})
    assert response.status_code == 201, response.text


def test_assigning_a_role_scoped_to_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_roles_url(f), json={"role_id": str(f.foreign_role_id)})
    assert response.status_code == 404, response.text


def test_assigning_a_role_to_a_membership_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _roles_url(f, membership_id=f.foreign_membership_id),
            json={"role_id": str(f.player_role_id)},
        )
    assert response.status_code == 404, response.text


def test_assigning_a_duplicate_active_role_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        first = client.post(_roles_url(f), json={"role_id": str(f.player_role_id)})
        second = client.post(_roles_url(f), json={"role_id": str(f.player_role_id)})
    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text


def test_a_sequential_replay_of_assign_role_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    key = f"assign-role-{uuid.uuid4().hex[:8]}"
    body = {"role_id": str(f.player_role_id)}
    with client_factory(f.admin_user_id) as client:
        first = client.post(_roles_url(f), json=body, headers={"Idempotency-Key": key})
        second = client.post(_roles_url(f), json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()


# ---------------------------------------------------------------------------
# revoke_membership_role
# ---------------------------------------------------------------------------


def test_revoking_a_role_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        assign = client.post(_roles_url(f), json={"role_id": str(f.player_role_id)})
        assert assign.status_code == 201, assign.text
        membership_role_id = assign.json()["membership_role_id"]

        response = client.post(_revoke_url(f, uuid.UUID(membership_role_id)))
    assert response.status_code == 204, response.text

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.membership_roles WHERE membership_role_id = :mr"),
            {"mr": uuid.UUID(membership_role_id)},
        ).scalar_one()
        assert revoked_at is not None


def test_revoking_an_already_revoked_role_is_a_no_op(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        assign = client.post(_roles_url(f), json={"role_id": str(f.player_role_id)})
        membership_role_id = uuid.UUID(assign.json()["membership_role_id"])

        first = client.post(_revoke_url(f, membership_role_id))
        second = client.post(_revoke_url(f, membership_role_id))
    assert first.status_code == 204, first.text
    assert second.status_code == 204, second.text


def test_revoking_a_role_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _revoke_url(f, f.active_admin_membership_role_id, campaign_id=f.campaign_id)
        )
    assert response.status_code == 404, response.text


def test_revoking_the_last_access_manager_role_on_an_active_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.active_admin_user_id) as client:
        response = client.post(
            _revoke_url(f, f.active_admin_membership_role_id, campaign_id=f.active_campaign_id)
        )
    assert response.status_code == 400, response.text

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.membership_roles WHERE membership_role_id = :mr"),
            {"mr": f.active_admin_membership_role_id},
        ).scalar_one()
        assert revoked_at is None
