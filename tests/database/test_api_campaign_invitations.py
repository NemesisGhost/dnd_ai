"""Tests for `dnd_ai.api.campaign_invitations` — the invitation
token/acceptance flow deferred at Phase 10 workstream 20, delivered here
(docs/PLAN.md Phase 10 "Still to come").

Covers: access control on `create_campaign_invitation` (non-member 404,
capless-member 403), idempotent replay of `create_campaign_invitation`,
and `accept_campaign_invitation`'s full acceptance surface — a fresh
invitee (new membership), a departed member (reactivation), an
already-open member (no-op reuse), a replay by the same accepting user
(idempotent), a wrong/nonexistent token, an expired invitation, a revoked
invitation, and an invitation already accepted by a different user. Also
covers (checkpoint-4 correction, extended by checkpoint 5) that ending a
membership through `end_campaign_membership` revokes its character
relationships *and* resource grants before reactivating it here — proving
neither silently regains effect through this acceptance flow's own
"reopen the same row in place" reactivation path.
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
from dnd_ai.api.local_auth import (
    get_login_account_rate_limiter,
    get_login_ip_rate_limiter,
    get_token_consumption_rate_limiter,
)
from dnd_ai.commands.campaign_invitations import create_campaign_invitation
from dnd_ai.commands.local_auth import _activate_local_account_impl, _create_local_account_impl
from dnd_ai.commands.memberships import end_campaign_membership
from dnd_ai.domain.access import (
    FOUNDRY_SYSTEM_AUTH_METHOD,
    AuthenticatedPrincipal,
    resolve_access_context,
)
from dnd_ai.domain.rate_limit import RateLimiter
from tests.factories import (
    lookup_id,
    make_access_group,
    make_access_group_membership,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_character_relationship_type,
    make_membership_character_relationship,
    make_membership_role,
    make_platform_administrator,
    make_relationship_type_capability,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
    oidc_principal,
)

pytestmark = pytest.mark.database

_DEV_ORIGIN = "http://localhost:5173"
_LOCAL_MANAGER_PASSWORD = "a genuinely random passphrase 1"


def _generous_rate_limiter() -> RateLimiter:
    return RateLimiter(max_attempts=10_000, window=timedelta(minutes=15))


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

        self.admin_user_id = make_user(connection, "Invitation API Admin")
        self.admin_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.admin_user_id
        )
        make_membership_role(connection, self.admin_membership_id, admin_role_id)

        other_admin_role_id = make_role(
            connection,
            campaign_id=self.other_campaign_id,
            code=f"other_admin_{uuid.uuid4().hex[:8]}",
        )
        make_role_capability(connection, other_admin_role_id, access_manage_id)
        make_role_capability(connection, other_admin_role_id, view_capability_id)
        self.other_admin_user_id = make_user(connection, "Invitation API Other Admin")
        self.other_admin_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, self.other_admin_user_id
        )
        make_membership_role(connection, self.other_admin_membership_id, other_admin_role_id)

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

        self.platform_admin_user_id = make_platform_administrator(connection)
        issued_local_manager = _create_local_account_impl(
            connection,
            created_by_user_id=self.platform_admin_user_id,
            login_name=f"invitation.local.manager.{uuid.uuid4().hex[:8]}",
            display_name="Invitation Local Manager",
        )
        self.local_manager_user_id = issued_local_manager.user_id
        self.local_manager_login_name = issued_local_manager.login_name
        _activate_local_account_impl(
            connection,
            raw_activation_token=issued_local_manager.raw_token,
            raw_password=_LOCAL_MANAGER_PASSWORD,
        )
        self.local_manager_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.local_manager_user_id
        )
        make_membership_role(connection, self.local_manager_membership_id, admin_role_id)

        # --- checkpoint-4 correction: end_campaign_membership must revoke
        # every unrevoked character relationship a membership holds, so a
        # later reactivation through this very acceptance flow never
        # silently restores the old character perspective/capability. ---
        view_summary_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_summary"
        )
        self.relationship_character_id = make_character(
            connection, self.world_id, name="Invitation API Relationship Character"
        )
        self.relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(
            connection, self.relationship_type_id, view_summary_capability_id
        )
        self.pre_reactivation_relationship_user_id = make_user(
            connection, "Invitation API Relationship Member"
        )
        self.pre_reactivation_relationship_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.pre_reactivation_relationship_user_id
        )
        self.pre_reactivation_relationship_id = make_membership_character_relationship(
            connection,
            self.pre_reactivation_relationship_membership_id,
            self.relationship_character_id,
            self.relationship_type_id,
        )

        # --- checkpoint 5: end_campaign_membership must also revoke every
        # unrevoked resource grant a membership holds, the identical
        # silent-reactivation gap closed above for character relationships.
        # Reuses the same membership/character as the relationship above —
        # one membership demonstrating both revocation halves at once. ---
        self.pre_reactivation_grant_id = make_resource_grant(
            connection,
            self.campaign_id,
            view_summary_capability_id,
            grantee_campaign_membership_id=self.pre_reactivation_relationship_membership_id,
            character_id=self.relationship_character_id,
        )

        # --- checkpoint-5 correction: the identical silent-reactivation gap
        # existed for security.access_group_memberships — end_campaign_
        # membership previously left a membership's group links untouched,
        # so resolve_access_context's own group-membership subquery kept
        # treating a departed member as still belonging to the group, and a
        # later reactivation through this exact acceptance flow would
        # silently restore every group-derived resource grant. A dedicated
        # membership/group/grant, separate from the relationship/direct-
        # grant scenario above, keeps that scenario's own assertions from
        # entangling with this one. ---
        self.pre_reactivation_access_group_user_id = make_user(
            connection, "Invitation API Access Group Member"
        )
        self.pre_reactivation_access_group_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.pre_reactivation_access_group_user_id
        )
        self.pre_reactivation_access_group_id = make_access_group(
            connection, self.campaign_id, name=f"Invitation API Group {uuid.uuid4().hex[:8]}"
        )
        self.pre_reactivation_access_group_membership_row_id = make_access_group_membership(
            connection,
            self.pre_reactivation_access_group_id,
            self.pre_reactivation_access_group_membership_id,
        )
        self.pre_reactivation_access_group_grant_id = make_resource_grant(
            connection,
            self.campaign_id,
            view_summary_capability_id,
            grantee_access_group_id=self.pre_reactivation_access_group_id,
            character_id=self.relationship_character_id,
        )


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"invitation-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM security.campaign_invitations WHERE campaign_id = ANY(:campaigns)"),
            {"campaigns": [fixture.campaign_id, fixture.other_campaign_id]},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_character_relationships
                WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id = ANY(:campaigns)
                )
            """),
            {"campaigns": [fixture.campaign_id, fixture.other_campaign_id]},
        )
        cleanup.execute(
            text("DELETE FROM security.resource_grants WHERE campaign_id = ANY(:campaigns)"),
            {"campaigns": [fixture.campaign_id, fixture.other_campaign_id]},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.character_relationship_type_capabilities "
                "WHERE character_relationship_type_id = :t"
            ),
            {"t": fixture.relationship_type_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.character_relationship_types "
                "WHERE character_relationship_type_id = :t"
            ),
            {"t": fixture.relationship_type_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id = ANY(:campaigns)
                )
            """),
            {"campaigns": [fixture.campaign_id, fixture.other_campaign_id]},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id = ANY(:campaigns)
                )
            """),
            {"campaigns": [fixture.campaign_id, fixture.other_campaign_id]},
        )
        cleanup.execute(
            text("DELETE FROM security.roles WHERE campaign_id = ANY(:campaigns)"),
            {"campaigns": [fixture.campaign_id, fixture.other_campaign_id]},
        )
        cleanup.execute(
            text("DELETE FROM security.idempotent_requests WHERE campaign_id = ANY(:campaigns)"),
            {"campaigns": [fixture.campaign_id, fixture.other_campaign_id]},
        )
        cleanup.execute(
            text("DELETE FROM security.campaign_memberships WHERE campaign_id = ANY(:campaigns)"),
            {"campaigns": [fixture.campaign_id, fixture.other_campaign_id]},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE campaign_id = ANY(:campaigns)"),
            {"campaigns": [fixture.campaign_id, fixture.other_campaign_id]},
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
                    fixture.other_admin_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                    fixture.fresh_invitee_user_id,
                    fixture.departed_user_id,
                    fixture.open_member_user_id,
                    fixture.other_user_id,
                    fixture.platform_admin_user_id,
                    fixture.local_manager_user_id,
                    fixture.pre_reactivation_relationship_user_id,
                    fixture.pre_reactivation_access_group_user_id,
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


@pytest.fixture
def browser_client_factory(postgres_engine: Engine) -> Callable[[], TestClient]:
    def _make() -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_login_ip_rate_limiter] = _generous_rate_limiter
        app.dependency_overrides[get_login_account_rate_limiter] = _generous_rate_limiter
        app.dependency_overrides[get_token_consumption_rate_limiter] = _generous_rate_limiter
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


def _revoke_invitation_url(
    f: Fixture, invitation_id: uuid.UUID, *, campaign_id: uuid.UUID | None = None
) -> str:
    active_campaign_id = f.campaign_id if campaign_id is None else campaign_id
    return f"/campaigns/{active_campaign_id}/invitations/{invitation_id}/revoke"


def _login_local_manager(client: TestClient, f: Fixture) -> str:
    response = client.post(
        "/auth/login",
        json={"login_name": f.local_manager_login_name, "password": _LOCAL_MANAGER_PASSWORD},
        headers={"Origin": _DEV_ORIGIN},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


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
    raw_token = payload["token"]
    assert len(raw_token) > 20

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT campaign_id, invited_email, invited_by_membership_id, invitation_token_hash,
                       accepted_at,
                       revoked_at, expires_at > now() AS not_yet_expired
                FROM security.campaign_invitations WHERE campaign_invitation_id = :i
            """),
            {"i": uuid.UUID(payload["campaign_invitation_id"])},
        ).one()
        assert row.campaign_id == f.campaign_id
        assert row.invited_email == "player@example.com"
        assert row.invited_by_membership_id == f.admin_membership_id
        assert row.invitation_token_hash != raw_token
        assert len(row.invitation_token_hash) == 64
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
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"create-invitation-{uuid.uuid4().hex[:8]}"
    with client_factory(f.admin_user_id) as client:
        first = client.post(_invitations_url(f), json={}, headers={"Idempotency-Key": key})
        second = client.post(_invitations_url(f), json={}, headers={"Idempotency-Key": key})
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    first_payload = first.json()
    second_payload = second.json()
    assert second_payload == {
        "campaign_invitation_id": first_payload["campaign_invitation_id"],
        "token": None,
    }

    raw_token = first_payload["token"]
    invitation_id = uuid.UUID(first_payload["campaign_invitation_id"])
    with postgres_engine.connect() as verify:
        row = (
            verify.execute(
                text("""
                    SELECT response_status_code, response_body::text AS response_body
                    FROM security.idempotent_requests
                    WHERE campaign_id = :campaign AND idempotency_key = :key
                """),
                {"campaign": f.campaign_id, "key": key},
            )
            .mappings()
            .one()
        )
        assert row["response_status_code"] == 201
        response_body = str(row["response_body"])
        assert raw_token not in response_body
        assert '"token"' not in response_body
        assert str(invitation_id) in response_body


def test_create_invitation_idempotency_state_never_persists_the_raw_token(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"create-invitation-state-{uuid.uuid4().hex[:8]}"
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _invitations_url(f),
            json={"invited_email": "player@example.com"},
            headers={"Idempotency-Key": key},
        )
    assert response.status_code == 201, response.text
    payload = response.json()
    raw_token = payload["token"]

    with postgres_engine.connect() as verify:
        durable_state = (
            verify.execute(
                text("""
                    SELECT response_body::text AS response_body
                    FROM security.idempotent_requests
                    WHERE campaign_id = :campaign AND idempotency_key = :key
                """),
                {"campaign": f.campaign_id, "key": key},
            )
            .mappings()
            .one()
        )
        serialized = str(durable_state["response_body"])
        assert raw_token not in serialized
        assert '"token"' not in serialized


def test_a_lost_response_replay_returns_no_token_and_does_not_create_a_second_invitation(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"create-invitation-lost-response-{uuid.uuid4().hex[:8]}"
    with client_factory(f.admin_user_id) as client:
        first = client.post(
            _invitations_url(f),
            json={"invited_email": "player@example.com"},
            headers={"Idempotency-Key": key},
        )
        second = client.post(
            _invitations_url(f),
            json={"invited_email": "player@example.com"},
            headers={"Idempotency-Key": key},
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload["token"] is not None
    assert second_payload == {
        "campaign_invitation_id": first_payload["campaign_invitation_id"],
        "token": None,
    }

    with postgres_engine.connect() as verify:
        invitation_count = verify.execute(
            text(
                "SELECT count(*) FROM security.campaign_invitations "
                "WHERE campaign_id = :campaign AND invited_email = :email"
            ),
            {"campaign": f.campaign_id, "email": "player@example.com"},
        ).scalar_one()
        assert invitation_count == 1


def test_listing_pending_invitations_returns_only_outstanding_rows_in_deterministic_order(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        first_pending_id = create_campaign_invitation(
            connection,
            campaign_id=f.campaign_id,
            invited_by_membership_id=f.admin_membership_id,
            invited_email="first@example.com",
        ).campaign_invitation_id
        second_pending_id = create_campaign_invitation(
            connection,
            campaign_id=f.campaign_id,
            invited_by_membership_id=f.admin_membership_id,
        ).campaign_invitation_id
        accepted_id = create_campaign_invitation(
            connection,
            campaign_id=f.campaign_id,
            invited_by_membership_id=f.admin_membership_id,
            invited_email="accepted@example.com",
        ).campaign_invitation_id
        revoked_id = create_campaign_invitation(
            connection,
            campaign_id=f.campaign_id,
            invited_by_membership_id=f.admin_membership_id,
            invited_email="revoked@example.com",
        ).campaign_invitation_id
        expired_id = create_campaign_invitation(
            connection,
            campaign_id=f.campaign_id,
            invited_by_membership_id=f.admin_membership_id,
            invited_email="expired@example.com",
            ttl=timedelta(seconds=-1),
        ).campaign_invitation_id
        other_campaign_id = create_campaign_invitation(
            connection,
            campaign_id=f.other_campaign_id,
            invited_by_membership_id=f.other_admin_membership_id,
            invited_email="other@example.com",
        ).campaign_invitation_id

        connection.execute(
            text(
                "UPDATE security.campaign_invitations SET created_at = now() - interval '2 days' "
                "WHERE campaign_invitation_id = :i"
            ),
            {"i": first_pending_id},
        )
        connection.execute(
            text(
                "UPDATE security.campaign_invitations SET created_at = now() - interval '1 day' "
                "WHERE campaign_invitation_id = :i"
            ),
            {"i": second_pending_id},
        )
        connection.execute(
            text(
                "UPDATE security.campaign_invitations "
                "SET accepted_by_user_id = :user, accepted_at = now() "
                "WHERE campaign_invitation_id = :i"
            ),
            {"user": f.fresh_invitee_user_id, "i": accepted_id},
        )
        connection.execute(
            text(
                "UPDATE security.campaign_invitations SET revoked_at = now() "
                "WHERE campaign_invitation_id = :i"
            ),
            {"i": revoked_id},
        )

    with client_factory(f.admin_user_id) as client:
        response = client.get(_invitations_url(f))
    assert response.status_code == 200, response.text
    body = response.json()

    assert [item["campaign_invitation_id"] for item in body["invitations"]] == [
        str(first_pending_id),
        str(second_pending_id),
    ]
    assert body["invitations"][0]["invited_email"] == "first@example.com"
    assert body["invitations"][1]["invited_email"] is None
    assert all(
        item["invited_by_display_name"] == "Invitation API Admin" for item in body["invitations"]
    )

    serialized = str(body)
    assert str(accepted_id) not in serialized
    assert str(revoked_id) not in serialized
    assert str(expired_id) not in serialized
    assert str(other_campaign_id) not in serialized
    assert "token" not in serialized.lower()
    assert "hash" not in serialized.lower()
    assert "accepted_by_user_id" not in serialized


def test_listing_pending_invitations_can_return_an_empty_list(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_invitations_url(f))
    assert response.status_code == 200, response.text
    assert response.json() == {"invitations": []}


def test_listing_pending_invitations_requires_access_manage(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_invitations_url(f))
    assert response.status_code == 403


def test_listing_pending_invitations_is_non_disclosing_for_non_members(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_invitations_url(f))
    assert response.status_code == 404


def test_revoking_an_invitation_succeeds_and_writes_one_redacted_audit_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        created = client.post(_invitations_url(f), json={"invited_email": "player@example.com"})
        assert created.status_code == 201, created.text
        payload = created.json()
        invitation_id = uuid.UUID(payload["campaign_invitation_id"])
        raw_token = payload["token"]

        response = client.post(_revoke_invitation_url(f, invitation_id))
    assert response.status_code == 200, response.text
    assert response.json() == {"campaign_invitation_id": str(invitation_id)}

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text(
                "SELECT revoked_at FROM security.campaign_invitations "
                "WHERE campaign_invitation_id = :i"
            ),
            {"i": invitation_id},
        ).scalar_one()
        assert revoked_at is not None

        audit_rows = (
            verify.execute(
                text("""
                    SELECT changed_fields, previous_status, new_status, reason
                    FROM audit.change_log
                    WHERE table_name = 'campaign_invitations'
                      AND record_id = :i
                      AND command_name = 'revoke_campaign_invitation'
                """),
                {"i": invitation_id},
            )
            .mappings()
            .all()
        )
        assert len(audit_rows) == 1
        serialized = str(dict(audit_rows[0]))
        assert raw_token not in serialized
        assert "player@example.com" not in serialized
        assert "token_hash" not in serialized


def test_revoking_an_already_revoked_invitation_is_a_no_op_without_duplicate_audit(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        invitation_id = create_campaign_invitation(
            connection,
            campaign_id=f.campaign_id,
            invited_by_membership_id=f.admin_membership_id,
        ).campaign_invitation_id

    with client_factory(f.admin_user_id) as client:
        first = client.post(_revoke_invitation_url(f, invitation_id))
        second = client.post(_revoke_invitation_url(f, invitation_id))
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()

    with postgres_engine.connect() as verify:
        audit_count = verify.execute(
            text(
                "SELECT count(*) FROM audit.change_log "
                "WHERE table_name = 'campaign_invitations' "
                "AND record_id = :i AND command_name = 'revoke_campaign_invitation'"
            ),
            {"i": invitation_id},
        ).scalar_one()
        assert audit_count == 1


def test_revoking_an_accepted_invitation_is_rejected_as_a_fixed_conflict(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    token = _issue_token(postgres_engine, f)
    with client_factory(f.fresh_invitee_user_id) as invitee_client:
        accepted = invitee_client.post("/campaign-invitations/accept", json={"token": token})
    assert accepted.status_code == 200, accepted.text

    with postgres_engine.connect() as verify:
        invitation_id = verify.execute(
            text(
                "SELECT campaign_invitation_id FROM security.campaign_invitations "
                "WHERE campaign_id = :c AND accepted_by_user_id = :u"
            ),
            {"c": f.campaign_id, "u": f.fresh_invitee_user_id},
        ).scalar_one()

    with client_factory(f.admin_user_id) as client:
        response = client.post(_revoke_invitation_url(f, invitation_id))
    assert response.status_code == 409, response.text


def test_revoking_an_expired_invitation_is_rejected_as_a_fixed_conflict(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        invitation_id = create_campaign_invitation(
            connection,
            campaign_id=f.campaign_id,
            invited_by_membership_id=f.admin_membership_id,
            ttl=timedelta(seconds=-1),
        ).campaign_invitation_id

    with client_factory(f.admin_user_id) as client:
        response = client.post(_revoke_invitation_url(f, invitation_id))
    assert response.status_code == 409, response.text


def test_revoking_a_missing_invitation_is_non_disclosing_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_revoke_invitation_url(f, uuid.uuid4()))
    assert response.status_code == 404


def test_revoking_an_invitation_from_a_different_campaign_is_non_disclosing_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        invitation_id = create_campaign_invitation(
            connection,
            campaign_id=f.other_campaign_id,
            invited_by_membership_id=f.other_admin_membership_id,
        ).campaign_invitation_id

    with client_factory(f.admin_user_id) as client:
        response = client.post(_revoke_invitation_url(f, invitation_id))
    assert response.status_code == 404, response.text


def test_revoking_an_invitation_requires_access_manage(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        invitation_id = create_campaign_invitation(
            connection,
            campaign_id=f.campaign_id,
            invited_by_membership_id=f.admin_membership_id,
        ).campaign_invitation_id

    with client_factory(f.capless_user_id) as client:
        response = client.post(_revoke_invitation_url(f, invitation_id))
    assert response.status_code == 403


def test_a_sequential_replay_of_revoke_invitation_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"revoke-invitation-{uuid.uuid4().hex[:8]}"
    with postgres_engine.begin() as connection:
        invitation_id = create_campaign_invitation(
            connection,
            campaign_id=f.campaign_id,
            invited_by_membership_id=f.admin_membership_id,
        ).campaign_invitation_id

    with client_factory(f.admin_user_id) as client:
        first = client.post(
            _revoke_invitation_url(f, invitation_id), headers={"Idempotency-Key": key}
        )
        second = client.post(
            _revoke_invitation_url(f, invitation_id), headers={"Idempotency-Key": key}
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()

    with postgres_engine.connect() as verify:
        audit_count = verify.execute(
            text(
                "SELECT count(*) FROM audit.change_log "
                "WHERE table_name = 'campaign_invitations' "
                "AND record_id = :i AND command_name = 'revoke_campaign_invitation'"
            ),
            {"i": invitation_id},
        ).scalar_one()
        assert audit_count == 1


def test_rejected_revoke_does_not_leave_a_completed_idempotency_reservation(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"revoke-invitation-conflict-{uuid.uuid4().hex[:8]}"
    with postgres_engine.begin() as connection:
        invitation_id = create_campaign_invitation(
            connection,
            campaign_id=f.campaign_id,
            invited_by_membership_id=f.admin_membership_id,
            ttl=timedelta(seconds=-1),
        ).campaign_invitation_id

    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _revoke_invitation_url(f, invitation_id), headers={"Idempotency-Key": key}
        )
    assert response.status_code == 409, response.text

    with postgres_engine.connect() as verify:
        reservation_count = verify.execute(
            text("SELECT count(*) FROM security.idempotent_requests WHERE idempotency_key = :key"),
            {"key": key},
        ).scalar_one()
        assert reservation_count == 0


def test_browser_session_revoke_without_csrf_header_is_rejected(
    browser_client_factory: Callable[[], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        invitation_id = create_campaign_invitation(
            connection,
            campaign_id=f.campaign_id,
            invited_by_membership_id=f.admin_membership_id,
        ).campaign_invitation_id

    with browser_client_factory() as client:
        _login_local_manager(client, f)
        response = client.post(
            _revoke_invitation_url(f, invitation_id),
            headers={"Origin": _DEV_ORIGIN},
        )
    assert response.status_code == 403, response.text


def test_browser_session_revoke_without_origin_is_rejected(
    browser_client_factory: Callable[[], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        invitation_id = create_campaign_invitation(
            connection,
            campaign_id=f.campaign_id,
            invited_by_membership_id=f.admin_membership_id,
        ).campaign_invitation_id

    with browser_client_factory() as client:
        csrf_token = _login_local_manager(client, f)
        response = client.post(
            _revoke_invitation_url(f, invitation_id),
            headers={"X-CSRF-Token": csrf_token},
        )
    assert response.status_code == 403, response.text


def test_browser_session_revoke_from_a_disallowed_origin_is_rejected(
    browser_client_factory: Callable[[], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        invitation_id = create_campaign_invitation(
            connection,
            campaign_id=f.campaign_id,
            invited_by_membership_id=f.admin_membership_id,
        ).campaign_invitation_id

    with browser_client_factory() as client:
        csrf_token = _login_local_manager(client, f)
        response = client.post(
            _revoke_invitation_url(f, invitation_id),
            headers={
                "Origin": "https://evil.example.com",
                "X-CSRF-Token": csrf_token,
            },
        )
    assert response.status_code == 403, response.text


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


def test_ending_a_membership_then_reaccepting_an_invitation_does_not_restore_its_old_character_relationship(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Checkpoint-4 correction: `_activate_or_create_membership` (this
    acceptance flow's own reactivation path) reopens the *same* `campaign_
    membership_id` row rather than inserting a fresh one — before this
    correction, `end_campaign_membership` left `security.membership_
    character_relationships` rows untouched, so reopening the membership
    silently restored whatever character capability the departed member
    held before, with no new grant and no new audit entry to explain why.
    Ending the membership through the real command must revoke that
    relationship first, and reactivating it here must not bring the old
    relationship back.

    Checkpoint 5 extends this same test to `security.resource_grants`: the
    identical silent-reactivation gap existed there too — `f.pre_
    reactivation_grant_id` belongs to the same membership and must be
    revoked by the same `end_campaign_membership()` call, and must not
    regain effect on reactivation either."""
    with postgres_engine.begin() as connection:
        end_result = end_campaign_membership(
            connection,
            campaign_membership_id=f.pre_reactivation_relationship_membership_id,
            campaign_id=f.campaign_id,
            ended_by_membership_id=f.admin_membership_id,
        )
    assert end_result.ended is True
    assert end_result.revoked_membership_character_relationship_ids == (
        f.pre_reactivation_relationship_id,
    )
    assert end_result.revoked_resource_grant_ids == (f.pre_reactivation_grant_id,)

    token = _issue_token(postgres_engine, f)
    with client_factory(f.pre_reactivation_relationship_user_id) as client:
        response = client.post("/campaign-invitations/accept", json={"token": token})
    assert response.status_code == 200, response.text
    assert response.json()["campaign_membership_id"] == str(
        f.pre_reactivation_relationship_membership_id
    )

    with postgres_engine.connect() as verify:
        membership_row = verify.execute(
            text("""
                SELECT ended_at, ms.code
                FROM security.campaign_memberships cm
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                WHERE cm.campaign_membership_id = :m
            """),
            {"m": f.pre_reactivation_relationship_membership_id},
        ).one()
        assert membership_row.ended_at is None
        assert membership_row.code == "active"

        relationship_revoked_at = verify.execute(
            text(
                "SELECT revoked_at FROM security.membership_character_relationships "
                "WHERE membership_character_relationship_id = :r"
            ),
            {"r": f.pre_reactivation_relationship_id},
        ).scalar_one()
        assert relationship_revoked_at is not None

        grant_revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.resource_grants WHERE resource_grant_id = :g"),
            {"g": f.pre_reactivation_grant_id},
        ).scalar_one()
        assert grant_revoked_at is not None

    with postgres_engine.connect() as verify:
        access = resolve_access_context(
            verify, user_id=f.pre_reactivation_relationship_user_id, campaign_id=f.campaign_id
        )
    assert access is not None
    assert f.relationship_character_id not in access.character_capabilities
    assert access.grant_effects == {}


def test_ending_a_membership_then_reaccepting_an_invitation_does_not_restore_its_old_access_group_membership(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Checkpoint-5 correction: `end_campaign_membership` previously closed
    a membership's own direct resource grants but left its `security.
    access_group_memberships` rows untouched — since `_activate_or_create_
    membership` (this acceptance flow's own reactivation path) reopens the
    *same* `campaign_membership_id` row rather than inserting a fresh one,
    a departed member's stale group membership (and every resource grant
    made to that group) would silently regain effect the moment they
    rejoined, with no new grant and no new audit entry to explain why. Full
    scenario: the group grant is effective before the membership ends,
    ineffective (and the group link closed) once it does, still ineffective
    after a real reactivation through this acceptance flow, and restored
    only by an explicit new `access_group_memberships` row — never by
    reactivation alone."""
    with postgres_engine.connect() as verify:
        before_access = resolve_access_context(
            verify,
            user_id=f.pre_reactivation_access_group_user_id,
            campaign_id=f.campaign_id,
        )
    assert before_access is not None
    assert before_access.grant_effects == {
        ("character_id", f.relationship_character_id): {"character.view_summary": "allow"},
    }

    # Ended through the real HTTP route (unlike the relationship/direct-
    # grant scenario above, which exercises end_campaign_membership() at
    # the command layer) so this test can also assert real audit content —
    # dnd_ai.api.memberships.end_campaign_membership_endpoint is what
    # actually writes the audit.change_log row this test checks below.
    with client_factory(f.admin_user_id) as client:
        end_response = client.post(
            f"/campaigns/{f.campaign_id}/memberships/"
            f"{f.pre_reactivation_access_group_membership_id}/end"
        )
    assert end_response.status_code == 200, end_response.text

    with postgres_engine.connect() as verify:
        group_membership_row = verify.execute(
            text(
                "SELECT removed_at FROM security.access_group_memberships "
                "WHERE access_group_membership_id = :g"
            ),
            {"g": f.pre_reactivation_access_group_membership_row_id},
        ).one()
        assert group_membership_row.removed_at is not None

        # The group's own grant row is untouched — it must remain effective
        # for any other member of the same group.
        group_grant_revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.resource_grants WHERE resource_grant_id = :g"),
            {"g": f.pre_reactivation_access_group_grant_id},
        ).scalar_one()
        assert group_grant_revoked_at is None

        access_after_end = resolve_access_context(
            verify,
            user_id=f.pre_reactivation_access_group_user_id,
            campaign_id=f.campaign_id,
        )
    assert access_after_end is None  # the membership itself is ended.

    token = _issue_token(postgres_engine, f)
    with client_factory(f.pre_reactivation_access_group_user_id) as client:
        response = client.post("/campaign-invitations/accept", json={"token": token})
    assert response.status_code == 200, response.text
    assert response.json()["campaign_membership_id"] == str(
        f.pre_reactivation_access_group_membership_id
    )

    with postgres_engine.connect() as verify:
        membership_row = verify.execute(
            text("""
                SELECT ended_at, ms.code
                FROM security.campaign_memberships cm
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                WHERE cm.campaign_membership_id = :m
            """),
            {"m": f.pre_reactivation_access_group_membership_id},
        ).one()
        assert membership_row.ended_at is None
        assert membership_row.code == "active"

        # The group link stays historically closed — reactivating the
        # membership never reopens it.
        group_membership_row = verify.execute(
            text(
                "SELECT removed_at FROM security.access_group_memberships "
                "WHERE access_group_membership_id = :g"
            ),
            {"g": f.pre_reactivation_access_group_membership_row_id},
        ).one()
        assert group_membership_row.removed_at is not None

        audit_row = (
            verify.execute(
                text("""
                    SELECT changed_fields FROM audit.change_log
                    WHERE table_name = 'campaign_memberships'
                      AND record_id = :m
                      AND command_name = 'end_campaign_membership'
                """),
                {"m": f.pre_reactivation_access_group_membership_id},
            )
            .mappings()
            .one()
        )
        assert str(f.pre_reactivation_access_group_membership_row_id) in str(
            audit_row["changed_fields"]
        )

    with postgres_engine.connect() as verify:
        access_after_reactivation = resolve_access_context(
            verify,
            user_id=f.pre_reactivation_access_group_user_id,
            campaign_id=f.campaign_id,
        )
    assert access_after_reactivation is not None
    assert access_after_reactivation.grant_effects == {}

    # Restoration requires an explicit new access_group_memberships row —
    # never a side effect of reactivation alone.
    with postgres_engine.begin() as connection:
        make_access_group_membership(
            connection,
            f.pre_reactivation_access_group_id,
            f.pre_reactivation_access_group_membership_id,
        )

    with postgres_engine.connect() as verify:
        access_after_new_assignment = resolve_access_context(
            verify,
            user_id=f.pre_reactivation_access_group_user_id,
            campaign_id=f.campaign_id,
        )
    assert access_after_new_assignment is not None
    assert access_after_new_assignment.grant_effects == {
        ("character_id", f.relationship_character_id): {"character.view_summary": "allow"},
    }


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
