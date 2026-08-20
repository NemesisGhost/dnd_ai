"""Tests for `dnd_ai.api.access_grants` — Phase 10 workstream 21's command
endpoints over `dnd_ai.commands.access_grants` (docs/PLAN.md Phase 10
"many-to-many user-character relationships and resource-access grants
sufficient for the vertical slice"). Mirrors `tests/database/
test_api_memberships.py`'s shape: `get_authenticated_user_id` is
overridden directly, since these tests exercise campaign-capability
enforcement and the commands' own HTTP wiring, not OIDC token
verification.

Covers: access control (non-member 404, capless-member 403), character-
relationship granting (success, duplicate-active-type 409, a foreign-world
character rejected, a foreign-campaign membership rejected), its temporal
bounds (workstream 25: timeline scoping and both open-ended and fully
bounded fictional-time ranges, an end without a start rejected, an end
before the start rejected, a foreign-world timeline/world-time rejected),
and revocation (success, idempotent no-op retry, cross-campaign
rejection); resource-grant creation via both grantee kinds (membership and
access group; neither/both supplied rejected by the database's own `CHECK`
constraint, a foreign-world character rejected, a foreign-campaign grantee
of either kind rejected, duplicate-active 409), all six target kinds
(workstream 25 added entity/knowledge-item/quest/session/event, with a
foreign-world quest and a foreign-campaign session/event each rejected),
and revocation (success, idempotent no-op retry, cross-campaign
rejection); idempotent replay for both create-shaped commands.
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
    make_access_group,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_entity,
    make_entity_type,
    make_event,
    make_knowledge_item,
    make_membership_role,
    make_quest,
    make_role,
    make_role_capability,
    make_session,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
    oidc_principal,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
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

        self.admin_user_id = make_user(connection, "Access Grant API Admin")
        self.admin_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.admin_user_id
        )
        make_membership_role(connection, self.admin_membership_id, admin_role_id)

        self.character_id = make_character(connection, self.world_id, name="Aria")

        # A second, unrelated world — its character proves the cross-world
        # ownership check.
        self.other_world_id = make_world(connection, slug=f"{slug}-other-world")
        self.other_world_character_id = make_character(connection, self.other_world_id)

        # The target of grant/create calls.
        self.target_user_id = make_user(connection, "Access Grant API Target Member")
        self.target_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.target_user_id
        )

        # A membership belonging only to the *other* campaign.
        foreign_user_id = make_user(connection, "Access Grant API Foreign Member")
        self.foreign_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, foreign_user_id
        )

        self.access_group_id = make_access_group(connection, self.campaign_id)
        self.foreign_access_group_id = make_access_group(connection, self.other_campaign_id)

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Access Grant API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Access Grant API Outsider")

        # --- Workstream 25: the five resource-grant target kinds beyond
        # character_id, plus the world-time/timeline fixtures for
        # grant_character_relationship's temporal-bound extension. ---
        entity_type_id = make_entity_type(connection, f"{slug.replace('-', '_')}_generic_entity")
        self.entity_id = make_entity(connection, self.world_id, entity_type_id)
        self.quest_id = make_quest(connection, self.world_id)
        self.foreign_world_quest_id = make_quest(connection, self.other_world_id)
        self.knowledge_item_id = make_knowledge_item(connection, self.world_id)
        self.session_id = make_session(connection, self.campaign_id, 1)
        self.foreign_campaign_session_id = make_session(connection, self.other_campaign_id, 1)

        self.world_time_id = make_world_time(connection, self.world_id, 1)
        self.later_world_time_id = make_world_time(connection, self.world_id, 2)
        self.foreign_world_time_id = make_world_time(connection, self.other_world_id, 1)
        self.foreign_timeline_id = make_timeline(
            connection, self.other_world_id, "Foreign Timeline"
        )

        self.event_id = make_event(
            connection,
            self.world_id,
            self.timeline_id,
            self.world_time_id,
            campaign_id=self.campaign_id,
        )
        # Same world (self.other_campaign_id shares self.timeline_id), but a
        # different campaign — proves the event-specific campaign check.
        self.foreign_campaign_event_id = make_event(
            connection,
            self.world_id,
            self.timeline_id,
            self.world_time_id,
            campaign_id=self.other_campaign_id,
        )


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"access-grant-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        # See tests/database/test_api_dungeon.py's identical cleanup
        # comment for why session_replication_role = replica and explicit,
        # dependency-ordered deletes are used here.
        for world_id in (fixture.world_id, fixture.other_world_id):
            cleanup.execute(
                text("""
                    DELETE FROM security.membership_character_relationships
                    WHERE campaign_membership_id IN (
                        SELECT campaign_membership_id FROM security.campaign_memberships
                        WHERE campaign_id IN (
                            SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                                SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                            )
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.resource_grants WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.access_group_memberships WHERE access_group_id IN (
                        SELECT access_group_id FROM security.access_groups WHERE campaign_id IN (
                            SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                                SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                            )
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.access_groups WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.membership_roles WHERE campaign_membership_id IN (
                        SELECT campaign_membership_id FROM security.campaign_memberships
                        WHERE campaign_id IN (
                            SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                                SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                            )
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.role_capabilities WHERE role_id IN (
                        SELECT role_id FROM security.roles WHERE campaign_id IN (
                            SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                                SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                            )
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.idempotent_requests WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.campaign_memberships WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM campaign.campaigns WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("DELETE FROM campaign.timelines WHERE world_id = :w"), {"w": world_id}
            )
            cleanup.execute(text("DELETE FROM core.entities WHERE world_id = :w"), {"w": world_id})
            cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world_id})
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.admin_user_id,
                    fixture.target_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
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


def _relationships_url(
    f: Fixture, membership_id: uuid.UUID | None = None, campaign_id: uuid.UUID | None = None
) -> str:
    return (
        f"/campaigns/{campaign_id or f.campaign_id}/memberships/"
        f"{membership_id or f.target_membership_id}/character-relationships"
    )


def _revoke_relationship_url(
    f: Fixture, relationship_id: uuid.UUID, campaign_id: uuid.UUID | None = None
) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/character-relationships/{relationship_id}/revoke"


def _resource_grants_url(f: Fixture, campaign_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/resource-grants"


def _revoke_grant_url(
    f: Fixture, resource_grant_id: uuid.UUID, campaign_id: uuid.UUID | None = None
) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/resource-grants/{resource_grant_id}/revoke"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
    assert response.status_code == 404


def test_a_member_without_access_manage_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# grant_character_relationship / revoke_character_relationship
# ---------------------------------------------------------------------------


def test_granting_a_character_relationship_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _relationships_url(f),
            json={
                "character_id": str(f.character_id),
                "relationship_type_code": "primary_controller",
            },
        )
    assert response.status_code == 201, response.text
    relationship_id = uuid.UUID(response.json()["membership_character_relationship_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT mcr.character_id, mcr.granted_by_membership_id, mcr.revoked_at,
                       crt.code
                FROM security.membership_character_relationships mcr
                JOIN security.character_relationship_types crt
                    ON crt.character_relationship_type_id = mcr.character_relationship_type_id
                WHERE mcr.membership_character_relationship_id = :r
            """),
            {"r": relationship_id},
        ).one()
        assert row.character_id == f.character_id
        assert row.granted_by_membership_id == f.admin_membership_id
        assert row.revoked_at is None
        assert row.code == "primary_controller"


def test_granting_a_duplicate_active_relationship_type_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    body = {"character_id": str(f.character_id), "relationship_type_code": "viewer"}
    with client_factory(f.admin_user_id) as client:
        first = client.post(_relationships_url(f), json=body)
        second = client.post(_relationships_url(f), json=body)
    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text


def test_granting_a_relationship_to_a_foreign_world_character_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _relationships_url(f),
            json={
                "character_id": str(f.other_world_character_id),
                "relationship_type_code": "viewer",
            },
        )
    assert response.status_code == 404, response.text


def test_granting_a_relationship_on_a_foreign_campaign_membership_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _relationships_url(f, membership_id=f.foreign_membership_id),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
    assert response.status_code == 404, response.text


def test_a_sequential_replay_of_grant_relationship_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    key = f"grant-relationship-{uuid.uuid4().hex[:8]}"
    body = {"character_id": str(f.character_id), "relationship_type_code": "viewer"}
    with client_factory(f.admin_user_id) as client:
        first = client.post(_relationships_url(f), json=body, headers={"Idempotency-Key": key})
        second = client.post(_relationships_url(f), json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()


# ---------------------------------------------------------------------------
# grant_character_relationship — temporal bounds (workstream 25)
# ---------------------------------------------------------------------------


def test_granting_a_timeline_scoped_relationship_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _relationships_url(f),
            json={
                "character_id": str(f.character_id),
                "relationship_type_code": "viewer",
                "timeline_id": str(f.timeline_id),
            },
        )
    assert response.status_code == 201, response.text
    with postgres_engine.connect() as verify:
        timeline_id = verify.execute(
            text(
                "SELECT timeline_id FROM security.membership_character_relationships "
                "WHERE membership_character_relationship_id = :r"
            ),
            {"r": uuid.UUID(response.json()["membership_character_relationship_id"])},
        ).scalar_one()
        assert timeline_id == f.timeline_id


def test_granting_a_relationship_with_a_foreign_world_timeline_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _relationships_url(f),
            json={
                "character_id": str(f.character_id),
                "relationship_type_code": "viewer",
                "timeline_id": str(f.foreign_timeline_id),
            },
        )
    assert response.status_code == 404, response.text


def test_granting_an_open_ended_bounded_relationship_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _relationships_url(f),
            json={
                "character_id": str(f.character_id),
                "relationship_type_code": "viewer",
                "effective_from_world_time_id": str(f.world_time_id),
            },
        )
    assert response.status_code == 201, response.text
    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT effective_from_world_time_id, effective_to_world_time_id,
                       lower(effective_period) AS lower_bound, upper_inf(effective_period) AS open
                FROM security.membership_character_relationships
                WHERE membership_character_relationship_id = :r
            """),
            {"r": uuid.UUID(response.json()["membership_character_relationship_id"])},
        ).one()
        assert row.effective_from_world_time_id == f.world_time_id
        assert row.effective_to_world_time_id is None
        assert row.open is True


def test_granting_a_fully_bounded_relationship_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _relationships_url(f),
            json={
                "character_id": str(f.character_id),
                "relationship_type_code": "viewer",
                "effective_from_world_time_id": str(f.world_time_id),
                "effective_to_world_time_id": str(f.later_world_time_id),
            },
        )
    assert response.status_code == 201, response.text
    with postgres_engine.connect() as verify:
        upper_inf = verify.execute(
            text(
                "SELECT upper_inf(effective_period) FROM "
                "security.membership_character_relationships "
                "WHERE membership_character_relationship_id = :r"
            ),
            {"r": uuid.UUID(response.json()["membership_character_relationship_id"])},
        ).scalar_one()
        assert upper_inf is False


def test_granting_a_relationship_with_an_end_but_no_start_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _relationships_url(f),
            json={
                "character_id": str(f.character_id),
                "relationship_type_code": "viewer",
                "effective_to_world_time_id": str(f.later_world_time_id),
            },
        )
    assert response.status_code == 400, response.text


def test_granting_a_relationship_with_an_end_before_the_start_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _relationships_url(f),
            json={
                "character_id": str(f.character_id),
                "relationship_type_code": "viewer",
                "effective_from_world_time_id": str(f.later_world_time_id),
                "effective_to_world_time_id": str(f.world_time_id),
            },
        )
    assert response.status_code == 400, response.text


def test_granting_a_relationship_with_a_foreign_world_time_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _relationships_url(f),
            json={
                "character_id": str(f.character_id),
                "relationship_type_code": "viewer",
                "effective_from_world_time_id": str(f.foreign_world_time_id),
            },
        )
    assert response.status_code == 404, response.text


def test_revoking_a_character_relationship_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
        assert grant.status_code == 201, grant.text
        relationship_id = grant.json()["membership_character_relationship_id"]

        response = client.post(_revoke_relationship_url(f, uuid.UUID(relationship_id)))
    assert response.status_code == 204, response.text

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text(
                "SELECT revoked_at FROM security.membership_character_relationships "
                "WHERE membership_character_relationship_id = :r"
            ),
            {"r": uuid.UUID(relationship_id)},
        ).scalar_one()
        assert revoked_at is not None


def test_revoking_an_already_revoked_relationship_is_a_no_op(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])

        first = client.post(_revoke_relationship_url(f, relationship_id))
        second = client.post(_revoke_relationship_url(f, relationship_id))
    assert first.status_code == 204, first.text
    assert second.status_code == 204, second.text


def test_revoking_a_relationship_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _revoke_relationship_url(f, uuid.uuid4(), campaign_id=f.other_campaign_id)
        )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# create_resource_grant / revoke_resource_grant
# ---------------------------------------------------------------------------


def test_creating_a_resource_grant_for_a_membership_grantee_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_full",
                "effect": "allow",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 201, response.text
    resource_grant_id = uuid.UUID(response.json()["resource_grant_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT rg.grantee_campaign_membership_id, rg.character_id, rg.effect,
                       c.code AS capability_code, rg.revoked_at
                FROM security.resource_grants rg
                JOIN security.capabilities c ON c.capability_id = rg.capability_id
                WHERE rg.resource_grant_id = :g
            """),
            {"g": resource_grant_id},
        ).one()
        assert row.grantee_campaign_membership_id == f.target_membership_id
        assert row.character_id == f.character_id
        assert row.effect == "allow"
        assert row.capability_code == "character.view_full"
        assert row.revoked_at is None


def test_creating_a_resource_grant_for_an_access_group_grantee_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "grantee_access_group_id": str(f.access_group_id),
            },
        )
    assert response.status_code == 201, response.text


def test_creating_a_resource_grant_with_both_grantees_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.target_membership_id),
                "grantee_access_group_id": str(f.access_group_id),
            },
        )
    assert response.status_code == 400, response.text


def test_creating_a_resource_grant_with_no_grantee_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={"character_id": str(f.character_id), "capability_code": "character.view_summary"},
        )
    assert response.status_code == 400, response.text


def test_creating_a_resource_grant_for_a_foreign_world_character_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.other_world_character_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 404, response.text


def test_creating_a_resource_grant_for_a_foreign_campaign_membership_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.foreign_membership_id),
            },
        )
    assert response.status_code == 404, response.text


def test_creating_a_resource_grant_for_a_foreign_campaign_access_group_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "grantee_access_group_id": str(f.foreign_access_group_id),
            },
        )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# create_resource_grant — the remaining five target kinds (workstream 25)
# ---------------------------------------------------------------------------


def test_creating_a_resource_grant_targeting_an_entity_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "entity_id": str(f.entity_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 201, response.text
    with postgres_engine.connect() as verify:
        entity_id = verify.execute(
            text("SELECT entity_id FROM security.resource_grants WHERE resource_grant_id = :g"),
            {"g": uuid.UUID(response.json()["resource_grant_id"])},
        ).scalar_one()
        assert entity_id == f.entity_id


def test_creating_a_resource_grant_targeting_a_knowledge_item_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "knowledge_item_id": str(f.knowledge_item_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 201, response.text


def test_creating_a_resource_grant_targeting_a_quest_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "quest_id": str(f.quest_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 201, response.text


def test_creating_a_resource_grant_targeting_a_foreign_world_quest_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "quest_id": str(f.foreign_world_quest_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 404, response.text


def test_creating_a_resource_grant_targeting_a_session_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "session_id": str(f.session_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 201, response.text


def test_creating_a_resource_grant_targeting_a_foreign_campaign_session_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "session_id": str(f.foreign_campaign_session_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 404, response.text


def test_creating_a_resource_grant_targeting_an_event_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "event_id": str(f.event_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 201, response.text


def test_creating_a_resource_grant_targeting_a_foreign_campaign_event_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "event_id": str(f.foreign_campaign_event_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 404, response.text


def test_creating_a_duplicate_active_resource_grant_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    body = {
        "character_id": str(f.character_id),
        "capability_code": "character.view_summary",
        "grantee_campaign_membership_id": str(f.target_membership_id),
    }
    with client_factory(f.admin_user_id) as client:
        first = client.post(_resource_grants_url(f), json=body)
        second = client.post(_resource_grants_url(f), json=body)
    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text


def test_a_sequential_replay_of_create_resource_grant_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    key = f"create-grant-{uuid.uuid4().hex[:8]}"
    body = {
        "character_id": str(f.character_id),
        "capability_code": "character.view_summary",
        "grantee_campaign_membership_id": str(f.target_membership_id),
    }
    with client_factory(f.admin_user_id) as client:
        first = client.post(_resource_grants_url(f), json=body, headers={"Idempotency-Key": key})
        second = client.post(_resource_grants_url(f), json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()


def test_revoking_a_resource_grant_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
        assert grant.status_code == 201, grant.text
        resource_grant_id = grant.json()["resource_grant_id"]

        response = client.post(_revoke_grant_url(f, uuid.UUID(resource_grant_id)))
    assert response.status_code == 204, response.text

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.resource_grants WHERE resource_grant_id = :g"),
            {"g": uuid.UUID(resource_grant_id)},
        ).scalar_one()
        assert revoked_at is not None


def test_revoking_an_already_revoked_resource_grant_is_a_no_op(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
        resource_grant_id = uuid.UUID(grant.json()["resource_grant_id"])

        first = client.post(_revoke_grant_url(f, resource_grant_id))
        second = client.post(_revoke_grant_url(f, resource_grant_id))
    assert first.status_code == 204, first.text
    assert second.status_code == 204, second.text


def test_revoking_a_resource_grant_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_revoke_grant_url(f, uuid.uuid4(), campaign_id=f.other_campaign_id))
    assert response.status_code == 404, response.text
