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
    oidc_principal,
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
        self.admin_membership_role_id = make_membership_role(
            connection, self.admin_membership_id, admin_role_id
        )

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
        # A dedicated pre-assigned role — the target of change-role calls
        # below. Deliberately *not* player_role_id: several pre-existing
        # assign-role tests independently assign player_role_id to this
        # same existing_membership_id, and a pre-assigned row here would
        # collide with those (ux_membership_roles_active).
        self.initial_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"initial_{uuid.uuid4().hex[:8]}"
        )
        self.existing_membership_role_id = make_membership_role(
            connection, self.existing_membership_id, self.initial_role_id
        )
        # A second, independent role usable by self.campaign_id — both the
        # change-role target and, assigned alongside initial_role_id on the
        # same membership, proof that changing one active role never
        # touches another the same membership independently holds.
        self.second_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"second_{uuid.uuid4().hex[:8]}"
        )

        # A membership belonging only to the *other* campaign.
        foreign_membership_user_id = make_user(connection, "Membership API Foreign Member")
        self.foreign_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, foreign_membership_user_id
        )

        # --- Active-state boundary fixtures (correction pass): each names
        # exactly one condition the documented eligibility check must
        # reject, isolated from every other condition. ---

        # An assignment whose expires_at is already in the past — still
        # revoked_at IS NULL, current role active, membership active; only
        # expiry makes it ineligible.
        self.expired_user_id = make_user(connection, "Membership API Expired Target")
        self.expired_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.expired_user_id
        )
        self.expired_membership_role_id = make_membership_role(
            connection, self.expired_membership_id, self.player_role_id
        )
        connection.execute(
            text(
                "UPDATE security.membership_roles "
                "SET granted_at = now() - interval '2 days', "
                "    expires_at = now() - interval '1 day' "
                "WHERE membership_role_id = :mr"
            ),
            {"mr": self.expired_membership_role_id},
        )

        # An assignment whose *current* role has since been deactivated.
        self.deactivatable_current_role_id = make_role(
            connection,
            campaign_id=self.campaign_id,
            code=f"deactivatable_current_{uuid.uuid4().hex[:8]}",
        )
        self.inactive_current_role_user_id = make_user(
            connection, "Membership API Inactive Current Role Target"
        )
        self.inactive_current_role_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.inactive_current_role_user_id
        )
        self.inactive_current_role_membership_role_id = make_membership_role(
            connection,
            self.inactive_current_role_membership_id,
            self.deactivatable_current_role_id,
        )
        connection.execute(
            text("UPDATE security.roles SET is_active = false WHERE role_id = :r"),
            {"r": self.deactivatable_current_role_id},
        )

        # A membership marked ended (ended_at set) but still carrying an
        # otherwise-current role assignment.
        self.ended_user_id = make_user(connection, "Membership API Ended Target")
        self.ended_membership_id = make_campaign_membership(
            connection,
            self.campaign_id,
            self.ended_user_id,
            status_code="departed",
            ended=True,
        )
        self.ended_membership_role_id = make_membership_role(
            connection, self.ended_membership_id, self.player_role_id
        )

        # A membership in a non-"active" status (suspended) but *not*
        # ended — isolates the status-code check from the ended_at check.
        self.suspended_user_id = make_user(connection, "Membership API Suspended Target")
        self.suspended_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.suspended_user_id, status_code="suspended"
        )
        self.suspended_membership_role_id = make_membership_role(
            connection, self.suspended_membership_id, self.player_role_id
        )

        # An inactive role — the *new_role_id* target of a rejection test.
        self.inactive_new_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"inactive_new_{uuid.uuid4().hex[:8]}"
        )
        connection.execute(
            text("UPDATE security.roles SET is_active = false WHERE role_id = :r"),
            {"r": self.inactive_new_role_id},
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
        self.active_owner_role_id = make_role(
            connection, campaign_id=self.active_campaign_id, code=f"owner_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, self.active_owner_role_id, access_manage_id)
        make_role_capability(connection, self.active_owner_role_id, view_capability_id)
        self.active_admin_user_id = make_user(connection, "Membership API Active Admin")
        self.active_admin_membership_id = make_campaign_membership(
            connection, self.active_campaign_id, self.active_admin_user_id
        )
        self.active_admin_membership_role_id = make_membership_role(
            connection, self.active_admin_membership_id, self.active_owner_role_id
        )
        # A second membership on the same active campaign, deliberately
        # left roleless here — active_admin_user_id is this campaign's
        # *sole* access.manage holder by default, matching every existing
        # last-manager test's assumption. A test that needs a second
        # manager (proving self-change is permitted when the caller is
        # *not* the last one) assigns active_owner_role_id to this
        # membership itself, locally — see
        # test_self_change_away_from_access_manage_succeeds_when_not_the_
        # last_manager below.
        self.active_second_admin_user_id = make_user(
            connection, "Membership API Active Second Admin"
        )
        self.active_second_admin_membership_id = make_campaign_membership(
            connection, self.active_campaign_id, self.active_second_admin_user_id
        )
        # A non-manager role usable by the active campaign — the target of
        # change-role calls that move a member away from access.manage.
        self.active_player_role_id = make_role(
            connection,
            campaign_id=self.active_campaign_id,
            code=f"active_player_{uuid.uuid4().hex[:8]}",
        )
        make_role_capability(connection, self.active_player_role_id, view_capability_id)


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
                    fixture.active_second_admin_user_id,
                    fixture.expired_user_id,
                    fixture.inactive_current_role_user_id,
                    fixture.ended_user_id,
                    fixture.suspended_user_id,
                ]
            },
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
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


def _change_url(
    f: Fixture, membership_role_id: uuid.UUID, campaign_id: uuid.UUID | None = None
) -> str:
    return (
        f"/campaigns/{campaign_id or f.campaign_id}/memberships/roles/{membership_role_id}/change"
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


# ---------------------------------------------------------------------------
# change_membership_role (Phase 13E-B checkpoint 1)
# ---------------------------------------------------------------------------


def test_changing_a_role_succeeds_and_preserves_temporal_history(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_url(f, f.existing_membership_role_id),
            json={"new_role_id": str(f.second_role_id)},
        )
    assert response.status_code == 201, response.text
    new_membership_role_id = uuid.UUID(response.json()["membership_role_id"])
    assert new_membership_role_id != f.existing_membership_role_id

    with postgres_engine.connect() as verify:
        old_row = verify.execute(
            text(
                "SELECT role_id, revoked_at FROM security.membership_roles "
                "WHERE membership_role_id = :mr"
            ),
            {"mr": f.existing_membership_role_id},
        ).one()
        assert old_row.role_id == f.initial_role_id
        assert old_row.revoked_at is not None

        new_row = verify.execute(
            text(
                "SELECT campaign_membership_id, role_id, granted_by_membership_id, revoked_at "
                "FROM security.membership_roles WHERE membership_role_id = :mr"
            ),
            {"mr": new_membership_role_id},
        ).one()
        assert new_row.campaign_membership_id == f.existing_membership_id
        assert new_row.role_id == f.second_role_id
        assert new_row.granted_by_membership_id == f.admin_membership_id
        assert new_row.revoked_at is None


def test_changing_one_role_preserves_another_active_role_on_the_same_membership(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        other_membership_role_id = make_membership_role(
            connection, f.existing_membership_id, f.system_role_id
        )

    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_url(f, f.existing_membership_role_id),
            json={"new_role_id": str(f.second_role_id)},
        )
    assert response.status_code == 201, response.text

    with postgres_engine.connect() as verify:
        untouched_revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.membership_roles WHERE membership_role_id = :mr"),
            {"mr": other_membership_role_id},
        ).scalar_one()
        assert untouched_revoked_at is None


def test_changing_a_role_to_the_same_role_it_already_holds_elsewhere_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        make_membership_role(connection, f.existing_membership_id, f.second_role_id)

    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_url(f, f.existing_membership_role_id),
            json={"new_role_id": str(f.second_role_id)},
        )
    assert response.status_code == 409, response.text


def test_changing_a_role_scoped_to_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_url(f, f.existing_membership_role_id),
            json={"new_role_id": str(f.foreign_role_id)},
        )
    assert response.status_code == 404, response.text


def test_changing_to_an_unknown_role_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_url(f, f.existing_membership_role_id),
            json={"new_role_id": str(uuid.uuid4())},
        )
    assert response.status_code == 404, response.text


def test_changing_a_role_assignment_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_url(f, f.active_admin_membership_role_id, campaign_id=f.campaign_id),
            json={"new_role_id": str(f.player_role_id)},
        )
    assert response.status_code == 404, response.text


def test_changing_an_already_revoked_role_assignment_is_a_conflict(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        revoke = client.post(_revoke_url(f, f.existing_membership_role_id))
        assert revoke.status_code == 204, revoke.text

        response = client.post(
            _change_url(f, f.existing_membership_role_id),
            json={"new_role_id": str(f.second_role_id)},
        )
    assert response.status_code == 409, response.text


# ---------------------------------------------------------------------------
# Active-state boundary (correction pass): expired assignment, ended/
# non-active membership, inactive current/new role, all non-disclosing.
# ---------------------------------------------------------------------------


def test_changing_an_expired_role_assignment_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_url(f, f.expired_membership_role_id),
            json={"new_role_id": str(f.second_role_id)},
        )
    assert response.status_code == 409, response.text

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.membership_roles WHERE membership_role_id = :mr"),
            {"mr": f.expired_membership_role_id},
        ).scalar_one()
        assert revoked_at is None


def test_changing_an_assignment_whose_current_role_is_inactive_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_url(f, f.inactive_current_role_membership_role_id),
            json={"new_role_id": str(f.second_role_id)},
        )
    assert response.status_code == 409, response.text

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.membership_roles WHERE membership_role_id = :mr"),
            {"mr": f.inactive_current_role_membership_role_id},
        ).scalar_one()
        assert revoked_at is None


def test_changing_a_role_on_an_ended_membership_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_url(f, f.ended_membership_role_id),
            json={"new_role_id": str(f.second_role_id)},
        )
    assert response.status_code == 409, response.text

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.membership_roles WHERE membership_role_id = :mr"),
            {"mr": f.ended_membership_role_id},
        ).scalar_one()
        assert revoked_at is None


def test_changing_a_role_on_a_non_active_membership_status_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Isolates the membership-status-code check from ended_at: `suspended_
    membership_id` is open (`ended_at IS NULL`) but its status is
    `suspended`, not `active`."""
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_url(f, f.suspended_membership_role_id),
            json={"new_role_id": str(f.second_role_id)},
        )
    assert response.status_code == 409, response.text

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.membership_roles WHERE membership_role_id = :mr"),
            {"mr": f.suspended_membership_role_id},
        ).scalar_one()
        assert revoked_at is None


def test_changing_to_an_inactive_new_role_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_url(f, f.existing_membership_role_id),
            json={"new_role_id": str(f.inactive_new_role_id)},
        )
    assert response.status_code == 404, response.text

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.membership_roles WHERE membership_role_id = :mr"),
            {"mr": f.existing_membership_role_id},
        ).scalar_one()
        assert revoked_at is None


# ---------------------------------------------------------------------------
# Same-role no-op (correction pass): rejected before any write, and never
# lets an Idempotency-Key be durably consumed by the no-op.
# ---------------------------------------------------------------------------


def test_changing_to_the_current_role_is_rejected_as_a_no_op(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_url(f, f.existing_membership_role_id),
            json={"new_role_id": str(f.initial_role_id)},
        )
    assert response.status_code == 422, response.text

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT role_id, revoked_at FROM security.membership_roles "
                "WHERE membership_role_id = :mr"
            ),
            {"mr": f.existing_membership_role_id},
        ).one()
        assert row.role_id == f.initial_role_id
        assert row.revoked_at is None
        row_count = verify.execute(
            text(
                "SELECT count(*) FROM security.membership_roles WHERE campaign_membership_id = :m"
            ),
            {"m": f.existing_membership_id},
        ).scalar_one()
        assert row_count == 1


def test_a_no_op_change_does_not_persist_an_idempotency_reservation(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """A no-op attempt under an `Idempotency-Key` must never durably reserve
    that key — the whole request's transaction, including the reservation
    INSERT, rolls back together with the rejected command (`dnd_ai.api.deps.
    get_connection`). Reusing the same key for a genuinely different
    (non-no-op) request must therefore still run the real command, not
    replay a cached no-op "success"."""
    key = f"no-op-change-{uuid.uuid4().hex[:8]}"
    with client_factory(f.admin_user_id) as client:
        no_op = client.post(
            _change_url(f, f.existing_membership_role_id),
            json={"new_role_id": str(f.initial_role_id)},
            headers={"Idempotency-Key": key},
        )
        assert no_op.status_code == 422, no_op.text

        with postgres_engine.connect() as verify:
            reservation_count = verify.execute(
                text(
                    "SELECT count(*) FROM security.idempotent_requests WHERE idempotency_key = :key"
                ),
                {"key": key},
            ).scalar_one()
            assert reservation_count == 0

        real_change = client.post(
            _change_url(f, f.existing_membership_role_id),
            json={"new_role_id": str(f.second_role_id)},
            headers={"Idempotency-Key": key},
        )
    assert real_change.status_code == 201, real_change.text


# ---------------------------------------------------------------------------
# Rollback (correction pass): every rejection leaves no partial write, no
# audit entry, and no idempotency reservation behind.
# ---------------------------------------------------------------------------


def test_a_rejected_change_leaves_no_audit_entry_or_idempotency_reservation(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"rejected-change-{uuid.uuid4().hex[:8]}"
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_url(f, f.expired_membership_role_id),
            json={"new_role_id": str(f.second_role_id)},
            headers={"Idempotency-Key": key},
        )
    assert response.status_code == 409, response.text

    with postgres_engine.connect() as verify:
        reservation_count = verify.execute(
            text("SELECT count(*) FROM security.idempotent_requests WHERE idempotency_key = :key"),
            {"key": key},
        ).scalar_one()
        assert reservation_count == 0

        audit_count = verify.execute(
            text(
                "SELECT count(*) FROM audit.change_log "
                "WHERE table_name = 'membership_roles' AND record_id = :mr"
            ),
            {"mr": f.expired_membership_role_id},
        ).scalar_one()
        assert audit_count == 0

        row_count = verify.execute(
            text(
                "SELECT count(*) FROM security.membership_roles WHERE campaign_membership_id = :m"
            ),
            {"m": f.expired_membership_id},
        ).scalar_one()
        assert row_count == 1


def test_a_member_without_access_manage_cannot_change_a_role(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(
            _change_url(f, f.existing_membership_role_id),
            json={"new_role_id": str(f.second_role_id)},
        )
    assert response.status_code == 403, response.text


def test_a_non_member_cannot_change_a_role(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(
            _change_url(f, f.existing_membership_role_id),
            json={"new_role_id": str(f.second_role_id)},
        )
    assert response.status_code == 404, response.text


def test_a_sequential_replay_of_change_role_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"change-role-{uuid.uuid4().hex[:8]}"
    body = {"new_role_id": str(f.second_role_id)}
    with client_factory(f.admin_user_id) as client:
        first = client.post(
            _change_url(f, f.existing_membership_role_id),
            json=body,
            headers={"Idempotency-Key": key},
        )
        second = client.post(
            _change_url(f, f.existing_membership_role_id),
            json=body,
            headers={"Idempotency-Key": key},
        )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()

    with postgres_engine.connect() as verify:
        # Exactly one new row was created — the replay did not re-run the
        # command a second time.
        count = verify.execute(
            text(
                "SELECT count(*) FROM security.membership_roles "
                "WHERE campaign_membership_id = :m AND role_id = :r AND revoked_at IS NULL"
            ),
            {"m": f.existing_membership_id, "r": f.second_role_id},
        ).scalar_one()
        assert count == 1


def test_changing_the_last_access_manager_role_on_an_active_campaign_to_a_non_manager_role_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Mirrors `test_revoking_the_last_access_manager_role_on_an_active_
    campaign_is_rejected` — the identical retention invariant, evaluated
    after the change (revoke-old + assign-new) rather than after a bare
    revoke. `active_admin_user_id` is `active_campaign_id`'s sole
    `access.manage` holder by fixture default (`active_second_admin_
    membership_id` is left roleless unless a test assigns it one — see
    `test_self_change_away_from_access_manage_succeeds_when_not_the_last_
    manager` below), so changing it away from the manager role would leave
    the active campaign with none."""
    with client_factory(f.active_admin_user_id) as client:
        response = client.post(
            _change_url(f, f.active_admin_membership_role_id, campaign_id=f.active_campaign_id),
            json={"new_role_id": str(f.active_player_role_id)},
        )
    assert response.status_code == 400, response.text

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.membership_roles WHERE membership_role_id = :mr"),
            {"mr": f.active_admin_membership_role_id},
        ).scalar_one()
        assert revoked_at is None
        new_role_count = verify.execute(
            text(
                "SELECT count(*) FROM security.membership_roles "
                "WHERE campaign_membership_id = :m AND role_id = :r"
            ),
            {"m": f.active_admin_membership_id, "r": f.active_player_role_id},
        ).scalar_one()
        assert new_role_count == 0


def test_self_change_away_from_access_manage_succeeds_when_not_the_last_manager(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Assigns `active_owner_role_id` to `active_second_admin_membership_id`
    first, so `active_admin_user_id` is no longer the campaign's sole
    manager — then `active_admin_user_id` changing their own role away from
    access.manage is permitted. Self-change is not blanket-restricted, only
    the retention invariant is enforced (see the rejection counterpart
    above, where no second manager exists)."""
    with postgres_engine.begin() as connection:
        make_membership_role(
            connection, f.active_second_admin_membership_id, f.active_owner_role_id
        )

    with client_factory(f.active_admin_user_id) as client:
        response = client.post(
            _change_url(f, f.active_admin_membership_role_id, campaign_id=f.active_campaign_id),
            json={"new_role_id": str(f.active_player_role_id)},
        )
    assert response.status_code == 201, response.text

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.membership_roles WHERE membership_role_id = :mr"),
            {"mr": f.active_admin_membership_role_id},
        ).scalar_one()
        assert revoked_at is not None


def test_self_change_is_permitted_on_a_non_active_campaign_even_dropping_the_sole_manager(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """`f.campaign_id` is `pending`, not `active` — the retention invariant
    only applies to active campaigns (matching `revoke_membership_role`'s
    own documented scope), so `admin_user_id`, its sole access.manage
    holder, may change their own role away from it here."""
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_url(f, f.admin_membership_role_id),
            json={"new_role_id": str(f.second_role_id)},
        )
    assert response.status_code == 201, response.text

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.membership_roles WHERE membership_role_id = :mr"),
            {"mr": f.admin_membership_role_id},
        ).scalar_one()
        assert revoked_at is not None


def test_audit_change_log_records_the_role_transition_without_secrets(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_url(f, f.existing_membership_role_id),
            json={"new_role_id": str(f.second_role_id)},
        )
    assert response.status_code == 201, response.text
    new_membership_role_id = uuid.UUID(response.json()["membership_role_id"])

    with postgres_engine.connect() as verify:
        row = (
            verify.execute(
                text("""
                SELECT ca.code AS action_code, cl.table_name, cl.record_id, cl.actor_user_id,
                       cl.previous_status, cl.new_status, cl.changed_fields
                FROM audit.change_log cl
                JOIN audit.change_actions ca ON ca.change_action_id = cl.change_action_id
                WHERE cl.table_name = 'membership_roles' AND cl.record_id = :record
                ORDER BY cl.recorded_at DESC
                LIMIT 1
            """),
                {"record": new_membership_role_id},
            )
            .mappings()
            .one()
        )
        assert row["action_code"] == "updated"
        assert row["actor_user_id"] == f.admin_user_id
        assert row["previous_status"] is not None
        assert row["new_status"] is not None
        assert row["previous_status"] != row["new_status"]
        assert str(f.existing_membership_role_id) in str(row["changed_fields"])
        # No secret-shaped content ever reaches this record.
        serialized = str(row)
        assert "password" not in serialized.lower()
        assert "csrf" not in serialized.lower()
        assert "token" not in serialized.lower()
