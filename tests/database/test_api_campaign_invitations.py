"""Tests for `dnd_ai.api.campaign_invitations` — the invitation
token/acceptance flow deferred at Phase 10 workstream 20, delivered here
(docs/PLAN.md Phase 10 "Still to come").

Covers: access control on `create_campaign_invitation` (non-member 404,
capless-member 403), idempotent replay of `create_campaign_invitation`,
and `accept_campaign_invitation`'s full acceptance surface — a fresh
invitee (new membership), a departed member (reactivation), an
already-open member (no-op reuse), a replay by the same accepting user
(idempotent), a wrong/nonexistent token, an expired invitation, a revoked
invitation, and an invitation already accepted by a different user.
"""

import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.commands.campaign_invitations import create_campaign_invitation
from dnd_ai.domain.access import FOUNDRY_SYSTEM_AUTH_METHOD, AuthenticatedPrincipal
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
        # invariant — see test_api_memberships.py's Fixture for the
        # identical reasoning; nothing here exercises that invariant.
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
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

        self.admin_user_id = make_user(connection, "Invitation API Admin")
        self.admin_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.admin_user_id
        )
        make_membership_role(connection, self.admin_membership_id, admin_role_id)

        self.capless_user_id = make_user(connection, "Invitation API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        self.outsider_user_id = make_user(connection, "Invitation API Outsider")

        self.fresh_invitee_user_id = make_user(connection, "Invitation API Fresh Invitee")

        self.departed_user_id = make_user(connection, "Invitation API Departed Member")
        self.departed_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.departed_user_id, ended=True
        )

        self.open_member_user_id = make_user(connection, "Invitation API Open Member")
        self.open_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.open_member_user_id
        )

        self.other_user_id = make_user(connection, "Invitation API Other User")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"invitation-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM security.campaign_invitations WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id = :c
                )
            """),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id = :c
                )
            """),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM security.roles WHERE campaign_id = :c"), {"c": fixture.campaign_id}
        )
        cleanup.execute(
            text("DELETE FROM security.idempotent_requests WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM security.campaign_memberships WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
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
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                    fixture.fresh_invitee_user_id,
                    fixture.departed_user_id,
                    fixture.open_member_user_id,
                    fixture.other_user_id,
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


def test_a_foundrysystem_credential_cannot_accept_an_invitation(
    postgres_engine: Engine, f: Fixture
) -> None:
    # dnd_ai.api.campaign_invitations' own module docstring:
    # accept_campaign_invitation_endpoint has no campaign_id to scope a
    # Foundry principal's world against, and is not part of the bounded
    # adapter-facing surface — require_human_user_id rejects a Foundry
    # credential outright, regardless of whether the linked user
    # (f.fresh_invitee_user_id) otherwise holds a valid token.
    token = _issue_token(postgres_engine, f)
    principal = AuthenticatedPrincipal(
        user_id=f.fresh_invitee_user_id,
        auth_method=FOUNDRY_SYSTEM_AUTH_METHOD,
        foundry_external_system_id=uuid.uuid4(),
        foundry_world_id=f.world_id,
    )
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    app.dependency_overrides[get_authenticated_user_id] = lambda: principal
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/campaign-invitations/accept", json={"token": token})
    assert response.status_code == 403


def _invitations_url(f: Fixture) -> str:
    return f"/campaigns/{f.campaign_id}/invitations"


def _issue_token(postgres_engine: Engine, f: Fixture, *, ttl: timedelta = timedelta(days=7)) -> str:
    """Issues an invitation directly through the command layer (bypassing
    HTTP) so tests can control `ttl`, which the API's request body
    deliberately does not expose (see dnd_ai.api.campaign_invitations'
    module docstring)."""
    with postgres_engine.begin() as connection:
        result = create_campaign_invitation(
            connection,
            campaign_id=f.campaign_id,
            invited_by_membership_id=f.admin_membership_id,
            ttl=ttl,
        )
    return result.token


# ---------------------------------------------------------------------------
# create_campaign_invitation access control + idempotency
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(_invitations_url(f), json={})
    assert response.status_code == 404


def test_a_member_without_access_manage_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(_invitations_url(f), json={})
    assert response.status_code == 403


def test_creating_an_invitation_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_invitations_url(f), json={"invited_email": "player@example.com"})
    assert response.status_code == 201, response.text
    payload = response.json()
    assert len(payload["token"]) > 20

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT campaign_id, invited_email, invited_by_membership_id, accepted_at,
                       revoked_at, expires_at > now() AS not_yet_expired
                FROM security.campaign_invitations WHERE campaign_invitation_id = :i
            """),
            {"i": uuid.UUID(payload["campaign_invitation_id"])},
        ).one()
        assert row.campaign_id == f.campaign_id
        assert row.invited_email == "player@example.com"
        assert row.invited_by_membership_id == f.admin_membership_id
        assert row.accepted_at is None
        assert row.revoked_at is None
        assert row.not_yet_expired is True

        audit_row = verify.execute(
            text("""
                SELECT entity_id, actor_user_id FROM audit.change_log
                WHERE schema_name = 'security' AND table_name = 'campaign_invitations'
                    AND record_id = :i
            """),
            {"i": uuid.UUID(payload["campaign_invitation_id"])},
        ).one()
        assert audit_row.entity_id is None
        assert audit_row.actor_user_id == f.admin_user_id


def test_a_sequential_replay_of_create_invitation_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    key = f"create-invitation-{uuid.uuid4().hex[:8]}"
    with client_factory(f.admin_user_id) as client:
        first = client.post(_invitations_url(f), json={}, headers={"Idempotency-Key": key})
        second = client.post(_invitations_url(f), json={}, headers={"Idempotency-Key": key})
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()


# ---------------------------------------------------------------------------
# accept_campaign_invitation
# ---------------------------------------------------------------------------


def test_accepting_an_invitation_for_a_fresh_user_creates_a_membership(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    token = _issue_token(postgres_engine, f)
    with client_factory(f.fresh_invitee_user_id) as client:
        response = client.post("/campaign-invitations/accept", json={"token": token})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["campaign_id"] == str(f.campaign_id)
    membership_id = uuid.UUID(payload["campaign_membership_id"])

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
        assert row.user_id == f.fresh_invitee_user_id
        assert row.ended_at is None
        assert row.code == "active"

        audit_row = verify.execute(
            text("""
                SELECT actor_user_id FROM audit.change_log
                WHERE schema_name = 'security' AND table_name = 'campaign_memberships'
                    AND record_id = :m
            """),
            {"m": membership_id},
        ).one()
        assert audit_row.actor_user_id == f.fresh_invitee_user_id


def test_accepting_an_invitation_reactivates_a_departed_membership(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    token = _issue_token(postgres_engine, f)
    with client_factory(f.departed_user_id) as client:
        response = client.post("/campaign-invitations/accept", json={"token": token})
    assert response.status_code == 200, response.text
    assert response.json()["campaign_membership_id"] == str(f.departed_membership_id)

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT ended_at, ms.code
                FROM security.campaign_memberships cm
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                WHERE cm.campaign_membership_id = :m
            """),
            {"m": f.departed_membership_id},
        ).one()
        assert row.ended_at is None
        assert row.code == "active"

        count = verify.execute(
            text(
                "SELECT count(*) FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u"
            ),
            {"c": f.campaign_id, "u": f.departed_user_id},
        ).scalar()
        assert count == 1


def test_accepting_an_invitation_for_an_already_open_member_reuses_the_membership(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    token = _issue_token(postgres_engine, f)
    with client_factory(f.open_member_user_id) as client:
        response = client.post("/campaign-invitations/accept", json={"token": token})
    assert response.status_code == 200, response.text
    assert response.json()["campaign_membership_id"] == str(f.open_membership_id)

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text(
                "SELECT count(*) FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u"
            ),
            {"c": f.campaign_id, "u": f.open_member_user_id},
        ).scalar()
        assert count == 1


def test_replaying_an_accept_by_the_same_user_is_idempotent(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    token = _issue_token(postgres_engine, f)
    with client_factory(f.fresh_invitee_user_id) as client:
        first = client.post("/campaign-invitations/accept", json={"token": token})
        second = client.post("/campaign-invitations/accept", json={"token": token})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()


def test_accepting_a_nonexistent_token_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.fresh_invitee_user_id) as client:
        response = client.post("/campaign-invitations/accept", json={"token": "not-a-real-token"})
    assert response.status_code == 404, response.text


def test_accepting_an_expired_invitation_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    token = _issue_token(postgres_engine, f, ttl=timedelta(seconds=-1))
    with client_factory(f.fresh_invitee_user_id) as client:
        response = client.post("/campaign-invitations/accept", json={"token": token})
    assert response.status_code == 404, response.text

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text(
                "SELECT count(*) FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u"
            ),
            {"c": f.campaign_id, "u": f.fresh_invitee_user_id},
        ).scalar()
        assert count == 0


def test_accepting_a_revoked_invitation_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    token = _issue_token(postgres_engine, f)
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.campaign_invitations SET revoked_at = now()
                WHERE campaign_id = :c AND accepted_at IS NULL
            """),
            {"c": f.campaign_id},
        )

    with client_factory(f.fresh_invitee_user_id) as client:
        response = client.post("/campaign-invitations/accept", json={"token": token})
    assert response.status_code == 404, response.text


def test_accepting_an_invitation_already_accepted_by_a_different_user_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    token = _issue_token(postgres_engine, f)
    with client_factory(f.fresh_invitee_user_id) as client:
        first = client.post("/campaign-invitations/accept", json={"token": token})
    assert first.status_code == 200, first.text

    with client_factory(f.other_user_id) as client:
        second = client.post("/campaign-invitations/accept", json={"token": token})
    assert second.status_code == 404, second.text
