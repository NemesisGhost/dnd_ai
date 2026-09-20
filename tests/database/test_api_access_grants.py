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
    make_character_relationship_type,
    make_entity,
    make_entity_type,
    make_event,
    make_knowledge_item,
    make_membership_role,
    make_quest,
    make_relationship_type_capability,
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
        # active, not the module's original "pending" default: checkpoint-4
        # correction added a campaign-active check to grant_character_
        # relationship/change_character_relationship, and admin_membership_id
        # below already gives this campaign a qualifying, non-expiring
        # access.manage holder, so activating it here satisfies the deferred
        # retention trigger at this setup transaction's own commit.
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="active"
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

        # --- Character-relationship-management checkpoint: membership/
        # character/relationship-type eligibility hardening, plus
        # change_character_relationship's own target fixtures. ---
        self.ended_member_user_id = make_user(connection, "Access Grant API Ended Member")
        self.ended_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.ended_member_user_id, ended=True
        )
        self.disabled_account_user_id = make_user(
            connection, "Access Grant API Disabled Account", status_code="inactive"
        )
        self.disabled_account_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.disabled_account_user_id
        )
        self.inactive_character_id = make_character(
            connection, self.world_id, name="Access Grant API Inactive Character"
        )
        connection.execute(
            text("""
                UPDATE core.entities SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived'
                )
                WHERE entity_id = :character
            """),
            {"character": self.inactive_character_id},
        )
        self.inactive_relationship_type_id = make_character_relationship_type(connection)
        connection.execute(
            text(
                "UPDATE security.character_relationship_types SET is_active = false "
                "WHERE character_relationship_type_id = :t"
            ),
            {"t": self.inactive_relationship_type_id},
        )
        self.primary_controller_type_id = lookup_id(
            connection,
            "security",
            "character_relationship_types",
            "character_relationship_type_id",
            "primary_controller",
        )
        self.portrayer_type_id = lookup_id(
            connection,
            "security",
            "character_relationship_types",
            "character_relationship_type_id",
            "portrayer",
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
        # security.character_relationship_types is a shared lookup table,
        # not scoped by world/campaign like the rows deleted above — the
        # fixture's own extra, deactivated type is deleted explicitly by id.
        cleanup.execute(
            text(
                "DELETE FROM security.character_relationship_types "
                "WHERE character_relationship_type_id = :t"
            ),
            {"t": fixture.inactive_relationship_type_id},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.admin_user_id,
                    fixture.target_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                    fixture.ended_member_user_id,
                    fixture.disabled_account_user_id,
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


def _change_relationship_url(
    f: Fixture, relationship_id: uuid.UUID, campaign_id: uuid.UUID | None = None
) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/character-relationships/{relationship_id}/change"


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
    assert response.status_code == 200, response.text
    assert response.json() == {"membership_character_relationship_id": relationship_id}

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
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text


def test_revoking_an_already_revoked_relationship_writes_no_second_audit_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])

        client.post(_revoke_relationship_url(f, relationship_id))
        client.post(_revoke_relationship_url(f, relationship_id))

    with postgres_engine.connect() as verify:
        audit_row_count = verify.execute(
            text(
                "SELECT count(*) FROM audit.change_log "
                "WHERE table_name = 'membership_character_relationships' "
                "AND record_id = :r AND change_action_id = ("
                "  SELECT change_action_id FROM audit.change_actions WHERE code = 'updated'"
                ")"
            ),
            {"r": relationship_id},
        ).scalar_one()
        assert audit_row_count == 1


def test_a_sequential_replay_of_revoke_relationship_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    key = f"revoke-relationship-{uuid.uuid4().hex[:8]}"
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
        relationship_id = grant.json()["membership_character_relationship_id"]

        first = client.post(
            _revoke_relationship_url(f, uuid.UUID(relationship_id)),
            headers={"Idempotency-Key": key},
        )
        second = client.post(
            _revoke_relationship_url(f, uuid.UUID(relationship_id)),
            headers={"Idempotency-Key": key},
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()


def test_revoking_a_relationship_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _revoke_relationship_url(f, uuid.uuid4(), campaign_id=f.other_campaign_id)
        )
    assert response.status_code == 404, response.text


def test_a_granted_relationship_appears_on_bootstrap_and_a_revoked_one_disappears_and_loses_access(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Focused API mutation-to-bootstrap coverage for add/revoke (checkpoint-4
    correction), through the real HTTP endpoints end to end rather than
    direct command calls: granting via `POST .../character-relationships`
    must make the character a selectable perspective on the very next
    `GET /auth/session` (`selected_character_id` defaults to it, being the
    only one), and the character-detail endpoint (a real perspective-
    sensitive resource) must become readable; revoking via `POST .../revoke`
    must remove both on the next request of each — `dnd_ai.queries.bootstrap.
    get_session_bootstrap` re-resolves fresh every call, so no code change
    is needed for either direction to take effect immediately."""
    with postgres_engine.begin() as connection:
        view_summary_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_summary"
        )
        viewer_type_id = lookup_id(
            connection,
            "security",
            "character_relationship_types",
            "character_relationship_type_id",
            "viewer",
        )

        # target_membership_id otherwise holds no role at all — the
        # character-detail endpoint's own coarser base gate requires
        # campaign.view before its finer, character-scoped tier check ever
        # runs (dnd_ai.api.characters' own module docstring).
        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        viewer_role_id = make_role(
            connection, campaign_id=f.campaign_id, code=f"bootstrap_viewer_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, viewer_role_id, view_capability_id)
        make_membership_role(connection, f.target_membership_id, viewer_role_id)

    # security.character_relationship_type_capabilities has no seed file and
    # "viewer" is a shared lookup row (unlike the fixture's own extra,
    # per-test relationship types) — added/removed around the request
    # section below rather than left to the fixture's own teardown, so this
    # test never leaks a permanent capability mapping onto a row every other
    # test in the shared database also reads.
    try:
        with postgres_engine.begin() as connection:
            make_relationship_type_capability(
                connection, viewer_type_id, view_summary_capability_id
            )

        with client_factory(f.admin_user_id) as admin_client:
            grant = admin_client.post(
                _relationships_url(f),
                json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
            )
        assert grant.status_code == 201, grant.text
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])

        with client_factory(f.target_user_id) as target_client:
            session_after_grant = target_client.get("/auth/session")
            detail_after_grant = target_client.get(
                f"/campaigns/{f.campaign_id}/characters/{f.character_id}"
            )
        assert session_after_grant.status_code == 200, session_after_grant.text
        campaign_after_grant = next(
            c
            for c in session_after_grant.json()["campaigns"]
            if c["campaign_id"] == str(f.campaign_id)
        )
        perspective_ids = {
            p["character_id"] for p in campaign_after_grant["character_perspectives"]
        }
        assert str(f.character_id) in perspective_ids
        assert campaign_after_grant["selected_character_id"] == str(f.character_id)
        assert detail_after_grant.status_code == 200, detail_after_grant.text

        with client_factory(f.admin_user_id) as admin_client:
            revoke = admin_client.post(_revoke_relationship_url(f, relationship_id))
        assert revoke.status_code == 200, revoke.text

        with client_factory(f.target_user_id) as target_client:
            session_after_revoke = target_client.get("/auth/session")
            detail_after_revoke = target_client.get(
                f"/campaigns/{f.campaign_id}/characters/{f.character_id}"
            )
        assert session_after_revoke.status_code == 200, session_after_revoke.text
        campaign_after_revoke = next(
            c
            for c in session_after_revoke.json()["campaigns"]
            if c["campaign_id"] == str(f.campaign_id)
        )
        assert campaign_after_revoke["character_perspectives"] == []
        assert campaign_after_revoke["selected_character_id"] is None
        assert detail_after_revoke.status_code == 404, detail_after_revoke.text
    finally:
        with postgres_engine.begin() as cleanup:
            cleanup.execute(
                text(
                    "DELETE FROM security.character_relationship_type_capabilities "
                    "WHERE character_relationship_type_id = :t AND capability_id = :c"
                ),
                {"t": viewer_type_id, "c": view_summary_capability_id},
            )


# ---------------------------------------------------------------------------
# grant_character_relationship — membership/user/character/type eligibility
# hardening (character-relationship-management checkpoint)
# ---------------------------------------------------------------------------


def test_granting_a_relationship_on_an_ended_membership_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _relationships_url(f, membership_id=f.ended_membership_id),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
    assert response.status_code == 409, response.text


def test_granting_a_relationship_on_a_membership_with_a_disabled_account_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _relationships_url(f, membership_id=f.disabled_account_membership_id),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
    assert response.status_code == 409, response.text


def test_granting_a_relationship_to_an_inactive_character_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _relationships_url(f),
            json={
                "character_id": str(f.inactive_character_id),
                "relationship_type_code": "viewer",
            },
        )
    assert response.status_code == 404, response.text


def test_granting_a_relationship_with_an_inactive_type_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.connect() as verify:
        code = verify.execute(
            text(
                "SELECT code FROM security.character_relationship_types "
                "WHERE character_relationship_type_id = :t"
            ),
            {"t": f.inactive_relationship_type_id},
        ).scalar_one()
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": code},
        )
    assert response.status_code == 404, response.text


def test_granting_a_relationship_with_a_nonexistent_type_code_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _relationships_url(f),
            json={
                "character_id": str(f.character_id),
                "relationship_type_code": f"no-such-type-{uuid.uuid4().hex[:8]}",
            },
        )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# grant/change_character_relationship — campaign lifecycle hardening
# (checkpoint-4 correction)
# ---------------------------------------------------------------------------


def _deactivate_campaign(postgres_engine: Engine, campaign_id: uuid.UUID) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE campaign.campaigns
                SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'pending'
                )
                WHERE campaign_id = :c
            """),
            {"c": campaign_id},
        )


def _reactivate_campaign(postgres_engine: Engine, campaign_id: uuid.UUID) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE campaign.campaigns
                SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'
                )
                WHERE campaign_id = :c
            """),
            {"c": campaign_id},
        )


def test_granting_a_relationship_on_an_inactive_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Sequential ordering: the campaign is already inactive by the time
    the request reaches the command (as opposed to the concurrency-proof
    ordering in `test_character_relationship_concurrency.py`, where the
    grant commits first and the deactivation blocks behind it)."""
    _deactivate_campaign(postgres_engine, f.campaign_id)
    try:
        with client_factory(f.admin_user_id) as client:
            response = client.post(
                _relationships_url(f),
                json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
            )
        assert response.status_code == 409, response.text

        with postgres_engine.connect() as verify:
            relationship_count = verify.execute(
                text("""
                    SELECT count(*) FROM security.membership_character_relationships
                    WHERE campaign_membership_id = :m AND character_id = :c
                """),
                {"m": f.target_membership_id, "c": f.character_id},
            ).scalar_one()
            assert relationship_count == 0

            audit_row_count = verify.execute(
                text("""
                    SELECT count(*) FROM audit.change_log
                    WHERE table_name = 'membership_character_relationships'
                      AND world_id = :w
                """),
                {"w": f.world_id},
            ).scalar_one()
            assert audit_row_count == 0
    finally:
        _reactivate_campaign(postgres_engine, f.campaign_id)


def test_a_grant_rejected_for_campaign_inactivity_does_not_durably_complete_its_idempotency_key(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The whole request runs in one transaction (`dnd_ai.api.deps.
    get_connection`) — `CampaignNotActiveError` rolls it back, including
    `begin_idempotent_request`'s own reservation row, so the *same* key
    reused once the campaign is active again must run the real command
    rather than replay a cached rejection or a cached success it never
    earned."""
    key = f"grant-relationship-campaign-inactive-{uuid.uuid4().hex[:8]}"
    body = {"character_id": str(f.character_id), "relationship_type_code": "viewer"}
    _deactivate_campaign(postgres_engine, f.campaign_id)
    try:
        with client_factory(f.admin_user_id) as client:
            rejected = client.post(
                _relationships_url(f), json=body, headers={"Idempotency-Key": key}
            )
        assert rejected.status_code == 409, rejected.text
    finally:
        _reactivate_campaign(postgres_engine, f.campaign_id)

    with client_factory(f.admin_user_id) as client:
        retried = client.post(_relationships_url(f), json=body, headers={"Idempotency-Key": key})
    assert retried.status_code == 201, retried.text

    with postgres_engine.connect() as verify:
        relationship_count = verify.execute(
            text("""
                SELECT count(*) FROM security.membership_character_relationships
                WHERE campaign_membership_id = :m AND character_id = :c AND revoked_at IS NULL
            """),
            {"m": f.target_membership_id, "c": f.character_id},
        ).scalar_one()
        assert relationship_count == 1


def test_changing_a_relationship_on_an_inactive_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
        assert grant.status_code == 201, grant.text
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])

    _deactivate_campaign(postgres_engine, f.campaign_id)
    try:
        with client_factory(f.admin_user_id) as client:
            response = client.post(
                _change_relationship_url(f, relationship_id),
                json={"new_relationship_type_id": str(f.portrayer_type_id)},
            )
        assert response.status_code == 409, response.text

        with postgres_engine.connect() as verify:
            row = verify.execute(
                text("""
                    SELECT mcr.revoked_at, crt.code
                    FROM security.membership_character_relationships mcr
                    JOIN security.character_relationship_types crt
                        ON crt.character_relationship_type_id = mcr.character_relationship_type_id
                    WHERE mcr.membership_character_relationship_id = :r
                """),
                {"r": relationship_id},
            ).one()
            assert row.revoked_at is None
            assert row.code == "viewer"

            audit_row_count = verify.execute(
                text("""
                    SELECT count(*) FROM audit.change_log
                    WHERE table_name = 'membership_character_relationships'
                      AND change_action_id = (
                          SELECT change_action_id FROM audit.change_actions WHERE code = 'updated'
                      )
                      AND world_id = :w
                """),
                {"w": f.world_id},
            ).scalar_one()
            assert audit_row_count == 0
    finally:
        _reactivate_campaign(postgres_engine, f.campaign_id)


def test_revoking_a_relationship_on_an_inactive_campaign_still_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """`revoke_character_relationship` deliberately does not check campaign
    lifecycle status — revoking access must stay available for cleanup even
    against an inactive campaign (see `dnd_ai.commands.access_grants`'s own
    module docstring, "Checkpoint-4 correction")."""
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
        assert grant.status_code == 201, grant.text
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])

    _deactivate_campaign(postgres_engine, f.campaign_id)
    try:
        with client_factory(f.admin_user_id) as client:
            response = client.post(_revoke_relationship_url(f, relationship_id))
        assert response.status_code == 200, response.text

        with postgres_engine.connect() as verify:
            revoked_at = verify.execute(
                text(
                    "SELECT revoked_at FROM security.membership_character_relationships "
                    "WHERE membership_character_relationship_id = :r"
                ),
                {"r": relationship_id},
            ).scalar_one()
            assert revoked_at is not None
    finally:
        _reactivate_campaign(postgres_engine, f.campaign_id)


# ---------------------------------------------------------------------------
# change_character_relationship
# ---------------------------------------------------------------------------


def test_changing_a_character_relationship_type_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
        assert grant.status_code == 201, grant.text
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])

        response = client.post(
            _change_relationship_url(f, relationship_id),
            json={"new_relationship_type_id": str(f.portrayer_type_id)},
        )
    assert response.status_code == 201, response.text
    new_relationship_id = uuid.UUID(response.json()["membership_character_relationship_id"])
    assert new_relationship_id != relationship_id

    with postgres_engine.connect() as verify:
        old_row = verify.execute(
            text(
                "SELECT revoked_at FROM security.membership_character_relationships "
                "WHERE membership_character_relationship_id = :r"
            ),
            {"r": relationship_id},
        ).one()
        assert old_row.revoked_at is not None

        new_row = verify.execute(
            text("""
                SELECT mcr.character_id, mcr.campaign_membership_id, mcr.revoked_at, crt.code
                FROM security.membership_character_relationships mcr
                JOIN security.character_relationship_types crt
                    ON crt.character_relationship_type_id = mcr.character_relationship_type_id
                WHERE mcr.membership_character_relationship_id = :r
            """),
            {"r": new_relationship_id},
        ).one()
        assert new_row.character_id == f.character_id
        assert new_row.campaign_membership_id == f.target_membership_id
        assert new_row.revoked_at is None
        assert new_row.code == "portrayer"


def test_changing_a_relationship_to_its_own_current_type_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={
                "character_id": str(f.character_id),
                "relationship_type_code": "primary_controller",
            },
        )
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])

        response = client.post(
            _change_relationship_url(f, relationship_id),
            json={"new_relationship_type_id": str(f.primary_controller_type_id)},
        )
    assert response.status_code == 422, response.text


def test_changing_a_revoked_relationship_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])
        revoke = client.post(_revoke_relationship_url(f, relationship_id))
        assert revoke.status_code == 200, revoke.text

        response = client.post(
            _change_relationship_url(f, relationship_id),
            json={"new_relationship_type_id": str(f.portrayer_type_id)},
        )
    assert response.status_code == 409, response.text


def test_changing_a_fictional_time_bounded_relationship_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Checkpoint-4 correction: a fully fictional-time-bounded relationship
    (both `effective_from_world_time_id`/`effective_to_world_time_id` set)
    is a closed historical interval, never currently active — `dnd_ai.
    commands.access_grants.change_character_relationship`'s own eligibility
    check must reject it exactly like an already-revoked row, via the same
    `CharacterRelationshipNotActiveError` (409)."""
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={
                "character_id": str(f.character_id),
                "relationship_type_code": "viewer",
                "effective_from_world_time_id": str(f.world_time_id),
                "effective_to_world_time_id": str(f.later_world_time_id),
            },
        )
        assert grant.status_code == 201, grant.text
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])

        response = client.post(
            _change_relationship_url(f, relationship_id),
            json={"new_relationship_type_id": str(f.portrayer_type_id)},
        )
    assert response.status_code == 409, response.text

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT revoked_at FROM security.membership_character_relationships "
                "WHERE membership_character_relationship_id = :r"
            ),
            {"r": relationship_id},
        ).scalar_one()
        assert row is None


def test_changing_a_relationship_after_its_account_is_disabled_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Checkpoint-4 review correction: `change_character_relationship`
    previously did not recheck the owning membership's account lifecycle at
    all, unlike `grant_character_relationship`. It must reject a target
    relationship whose owning account has since gone platform-inactive,
    folded into the same `CharacterRelationshipNotActiveError` (409) this
    function already raises for every other "no longer eligible" cause —
    and reactivating the account afterward must not silently expose the
    attempted (rejected) type change."""
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
        assert grant.status_code == 201, grant.text
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])

    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.users SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'inactive'
                ) WHERE user_id = :u
            """),
            {"u": f.target_user_id},
        )

    try:
        with client_factory(f.admin_user_id) as client:
            response = client.post(
                _change_relationship_url(f, relationship_id),
                json={"new_relationship_type_id": str(f.portrayer_type_id)},
            )
        assert response.status_code == 409, response.text

        with postgres_engine.connect() as verify:
            row = verify.execute(
                text("""
                    SELECT mcr.revoked_at, crt.code
                    FROM security.membership_character_relationships mcr
                    JOIN security.character_relationship_types crt
                        ON crt.character_relationship_type_id = mcr.character_relationship_type_id
                    WHERE mcr.membership_character_relationship_id = :r
                """),
                {"r": relationship_id},
            ).one()
            assert row.revoked_at is None
            assert row.code == "viewer"

            audit_row_count = verify.execute(
                text("""
                    SELECT count(*) FROM audit.change_log
                    WHERE table_name = 'membership_character_relationships'
                      AND change_action_id = (
                          SELECT change_action_id FROM audit.change_actions WHERE code = 'updated'
                      )
                      AND world_id = :w
                """),
                {"w": f.world_id},
            ).scalar_one()
            assert audit_row_count == 0
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE security.users SET lifecycle_status_id = (
                        SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'
                    ) WHERE user_id = :u
                """),
                {"u": f.target_user_id},
            )

    with postgres_engine.connect() as verify:
        code = verify.execute(
            text("""
                SELECT crt.code
                FROM security.membership_character_relationships mcr
                JOIN security.character_relationship_types crt
                    ON crt.character_relationship_type_id = mcr.character_relationship_type_id
                WHERE mcr.membership_character_relationship_id = :r
            """),
            {"r": relationship_id},
        ).scalar_one()
        assert code == "viewer"


def test_a_change_rejected_for_account_disablement_does_not_durably_complete_its_idempotency_key(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
        assert grant.status_code == 201, grant.text
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])

    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.users SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'inactive'
                ) WHERE user_id = :u
            """),
            {"u": f.target_user_id},
        )

    key = f"change-relationship-account-inactive-{uuid.uuid4().hex[:8]}"
    body = {"new_relationship_type_id": str(f.portrayer_type_id)}
    try:
        with client_factory(f.admin_user_id) as client:
            rejected = client.post(
                _change_relationship_url(f, relationship_id),
                json=body,
                headers={"Idempotency-Key": key},
            )
        assert rejected.status_code == 409, rejected.text
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE security.users SET lifecycle_status_id = (
                        SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'
                    ) WHERE user_id = :u
                """),
                {"u": f.target_user_id},
            )

    with client_factory(f.admin_user_id) as client:
        retried = client.post(
            _change_relationship_url(f, relationship_id),
            json=body,
            headers={"Idempotency-Key": key},
        )
    assert retried.status_code == 201, retried.text

    with postgres_engine.connect() as verify:
        code = verify.execute(
            text("""
                SELECT crt.code
                FROM security.membership_character_relationships mcr
                JOIN security.character_relationship_types crt
                    ON crt.character_relationship_type_id = mcr.character_relationship_type_id
                WHERE mcr.membership_character_relationship_id = :r
            """),
            {"r": uuid.UUID(retried.json()["membership_character_relationship_id"])},
        ).scalar_one()
        assert code == "portrayer"


def test_changing_a_relationship_after_its_character_is_deactivated_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Checkpoint-4 review correction: `change_character_relationship`
    previously did not recheck the relationship's own existing character at
    all, unlike `grant_character_relationship`. It must reject a target
    relationship whose character has since been deactivated/archived,
    folded into the same `CharacterRelationshipNotActiveError` (409) —
    and reactivating the character afterward must not silently expose the
    attempted (rejected) type change."""
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
        assert grant.status_code == 201, grant.text
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])

    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE core.entities SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived'
                ) WHERE entity_id = :c
            """),
            {"c": f.character_id},
        )

    try:
        with client_factory(f.admin_user_id) as client:
            response = client.post(
                _change_relationship_url(f, relationship_id),
                json={"new_relationship_type_id": str(f.portrayer_type_id)},
            )
        assert response.status_code == 409, response.text

        with postgres_engine.connect() as verify:
            row = verify.execute(
                text("""
                    SELECT mcr.revoked_at, crt.code
                    FROM security.membership_character_relationships mcr
                    JOIN security.character_relationship_types crt
                        ON crt.character_relationship_type_id = mcr.character_relationship_type_id
                    WHERE mcr.membership_character_relationship_id = :r
                """),
                {"r": relationship_id},
            ).one()
            assert row.revoked_at is None
            assert row.code == "viewer"

            audit_row_count = verify.execute(
                text("""
                    SELECT count(*) FROM audit.change_log
                    WHERE table_name = 'membership_character_relationships'
                      AND change_action_id = (
                          SELECT change_action_id FROM audit.change_actions WHERE code = 'updated'
                      )
                      AND world_id = :w
                """),
                {"w": f.world_id},
            ).scalar_one()
            assert audit_row_count == 0
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE core.entities SET lifecycle_status_id = (
                        SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'
                    ) WHERE entity_id = :c
                """),
                {"c": f.character_id},
            )

    with postgres_engine.connect() as verify:
        code = verify.execute(
            text("""
                SELECT crt.code
                FROM security.membership_character_relationships mcr
                JOIN security.character_relationship_types crt
                    ON crt.character_relationship_type_id = mcr.character_relationship_type_id
                WHERE mcr.membership_character_relationship_id = :r
            """),
            {"r": relationship_id},
        ).scalar_one()
        assert code == "viewer"


def test_a_change_rejected_for_character_deactivation_does_not_durably_complete_its_idempotency_key(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
        assert grant.status_code == 201, grant.text
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])

    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE core.entities SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived'
                ) WHERE entity_id = :c
            """),
            {"c": f.character_id},
        )

    key = f"change-relationship-character-inactive-{uuid.uuid4().hex[:8]}"
    body = {"new_relationship_type_id": str(f.portrayer_type_id)}
    try:
        with client_factory(f.admin_user_id) as client:
            rejected = client.post(
                _change_relationship_url(f, relationship_id),
                json=body,
                headers={"Idempotency-Key": key},
            )
        assert rejected.status_code == 409, rejected.text
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE core.entities SET lifecycle_status_id = (
                        SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'
                    ) WHERE entity_id = :c
                """),
                {"c": f.character_id},
            )

    with client_factory(f.admin_user_id) as client:
        retried = client.post(
            _change_relationship_url(f, relationship_id),
            json=body,
            headers={"Idempotency-Key": key},
        )
    assert retried.status_code == 201, retried.text

    with postgres_engine.connect() as verify:
        code = verify.execute(
            text("""
                SELECT crt.code
                FROM security.membership_character_relationships mcr
                JOIN security.character_relationship_types crt
                    ON crt.character_relationship_type_id = mcr.character_relationship_type_id
                WHERE mcr.membership_character_relationship_id = :r
            """),
            {"r": uuid.UUID(retried.json()["membership_character_relationship_id"])},
        ).scalar_one()
        assert code == "portrayer"


def test_changing_a_relationship_to_an_inactive_type_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])

        response = client.post(
            _change_relationship_url(f, relationship_id),
            json={"new_relationship_type_id": str(f.inactive_relationship_type_id)},
        )
    assert response.status_code == 404, response.text


def test_changing_a_relationship_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _change_relationship_url(f, uuid.uuid4(), campaign_id=f.other_campaign_id),
            json={"new_relationship_type_id": str(f.portrayer_type_id)},
        )
    assert response.status_code == 404, response.text


def test_a_sequential_replay_of_change_relationship_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    key = f"change-relationship-{uuid.uuid4().hex[:8]}"
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])

        first = client.post(
            _change_relationship_url(f, relationship_id),
            json={"new_relationship_type_id": str(f.portrayer_type_id)},
            headers={"Idempotency-Key": key},
        )
        second = client.post(
            _change_relationship_url(f, relationship_id),
            json={"new_relationship_type_id": str(f.portrayer_type_id)},
            headers={"Idempotency-Key": key},
        )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()


def test_a_member_without_access_manage_gets_forbidden_for_change(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _relationships_url(f),
            json={"character_id": str(f.character_id), "relationship_type_code": "viewer"},
        )
        relationship_id = uuid.UUID(grant.json()["membership_character_relationship_id"])

    with client_factory(f.capless_user_id) as client:
        response = client.post(
            _change_relationship_url(f, relationship_id),
            json={"new_relationship_type_id": str(f.portrayer_type_id)},
        )
    assert response.status_code == 403


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
                "capability_code": "campaign.view",
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
                "capability_code": "campaign.view",
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
                "capability_code": "campaign.view",
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
                "capability_code": "campaign.view",
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
                "capability_code": "campaign.view",
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
    assert response.status_code == 200, response.text

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
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text


def test_revoking_a_resource_grant_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_revoke_grant_url(f, uuid.uuid4(), campaign_id=f.other_campaign_id))
    assert response.status_code == 404, response.text


def test_a_sequential_replay_of_revoke_resource_grant_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """Checkpoint 5: `revoke_resource_grant_endpoint` now accepts an
    `Idempotency-Key`, mirroring `revoke_character_relationship_endpoint`'s
    identical hardening."""
    key = f"revoke-grant-{uuid.uuid4().hex[:8]}"
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

        first = client.post(
            _revoke_grant_url(f, resource_grant_id), headers={"Idempotency-Key": key}
        )
        second = client.post(
            _revoke_grant_url(f, resource_grant_id), headers={"Idempotency-Key": key}
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()


def test_revoking_an_already_revoked_resource_grant_writes_no_second_audit_row(
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
        resource_grant_id = uuid.UUID(grant.json()["resource_grant_id"])

        client.post(_revoke_grant_url(f, resource_grant_id))
        client.post(_revoke_grant_url(f, resource_grant_id))

    with postgres_engine.connect() as verify:
        audit_row_count = verify.execute(
            text(
                "SELECT count(*) FROM audit.change_log "
                "WHERE table_name = 'resource_grants' "
                "AND record_id = :g AND change_action_id = ("
                "  SELECT change_action_id FROM audit.change_actions WHERE code = 'updated'"
                ")"
            ),
            {"g": resource_grant_id},
        ).scalar_one()
        assert audit_row_count == 1


# ---------------------------------------------------------------------------
# create_resource_grant / revoke_resource_grant — audit content (checkpoint-5
# correction)
# ---------------------------------------------------------------------------


def test_creating_a_resource_grant_for_a_membership_grantee_records_bounded_audit_content(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Checkpoint-5 correction: the create-grant audit row previously
    carried no `changed_fields` at all — `record_id` alone told a reviewer
    that some grant was created, not what it was. Now records which kind of
    grantee (a member, here), the exact typed target, the capability code,
    and the `allow`/`deny` effect — never the free-form `reason` text."""
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_full",
                "effect": "allow",
                "grantee_campaign_membership_id": str(f.target_membership_id),
                "reason": "do not store this free-form text in the audit row",
            },
        )
    assert response.status_code == 201, response.text
    resource_grant_id = uuid.UUID(response.json()["resource_grant_id"])

    with postgres_engine.connect() as verify:
        audit_row = (
            verify.execute(
                text("""
                    SELECT changed_fields FROM audit.change_log
                    WHERE table_name = 'resource_grants' AND record_id = :g
                """),
                {"g": resource_grant_id},
            )
            .mappings()
            .one()
        )
    assert audit_row["changed_fields"] == {
        "grantee_campaign_membership_id": str(f.target_membership_id),
        "grantee_access_group_id": None,
        "target_kind": "character_id",
        "target_id": str(f.character_id),
        "capability_code": "character.view_full",
        "effect": "allow",
    }
    assert "do not store this free-form text in the audit row" not in str(audit_row)


def test_creating_a_resource_grant_for_an_access_group_grantee_records_bounded_audit_content(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "effect": "deny",
                "grantee_access_group_id": str(f.access_group_id),
            },
        )
    assert response.status_code == 201, response.text
    resource_grant_id = uuid.UUID(response.json()["resource_grant_id"])

    with postgres_engine.connect() as verify:
        audit_row = (
            verify.execute(
                text("""
                    SELECT changed_fields FROM audit.change_log
                    WHERE table_name = 'resource_grants' AND record_id = :g
                """),
                {"g": resource_grant_id},
            )
            .mappings()
            .one()
        )
    assert audit_row["changed_fields"] == {
        "grantee_campaign_membership_id": None,
        "grantee_access_group_id": str(f.access_group_id),
        "target_kind": "character_id",
        "target_id": str(f.character_id),
        "capability_code": "character.view_summary",
        "effect": "deny",
    }


def test_revoking_a_resource_grant_records_bounded_audit_content_read_from_the_locked_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The revoke request itself only ever supplies `resource_grant_id` —
    `revoke_resource_grant()` reads the grantee/target/capability/effect
    values recorded here from the locked grant row it already reads to
    decide `revoked`, never re-derived from caller input."""
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_full",
                "effect": "allow",
                "grantee_campaign_membership_id": str(f.target_membership_id),
                "reason": "do not store this free-form text in the audit row either",
            },
        )
        resource_grant_id = uuid.UUID(grant.json()["resource_grant_id"])

        response = client.post(_revoke_grant_url(f, resource_grant_id))
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        audit_row = (
            verify.execute(
                text("""
                    SELECT changed_fields FROM audit.change_log
                    WHERE table_name = 'resource_grants' AND record_id = :g
                      AND change_action_id = (
                          SELECT change_action_id FROM audit.change_actions WHERE code = 'updated'
                      )
                """),
                {"g": resource_grant_id},
            )
            .mappings()
            .one()
        )
    assert audit_row["changed_fields"] == {
        "grantee_campaign_membership_id": str(f.target_membership_id),
        "grantee_access_group_id": None,
        "target_kind": "character_id",
        "target_id": str(f.character_id),
        "capability_code": "character.view_full",
        "effect": "allow",
    }
    assert "do not store this free-form text in the audit row either" not in str(audit_row)


def test_revoking_a_deny_effect_resource_grant_records_deny_in_its_audit_content(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "effect": "deny",
                "grantee_access_group_id": str(f.access_group_id),
            },
        )
        resource_grant_id = uuid.UUID(grant.json()["resource_grant_id"])

        response = client.post(_revoke_grant_url(f, resource_grant_id))
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        audit_row = (
            verify.execute(
                text("""
                    SELECT changed_fields FROM audit.change_log
                    WHERE table_name = 'resource_grants' AND record_id = :g
                      AND change_action_id = (
                          SELECT change_action_id FROM audit.change_actions WHERE code = 'updated'
                      )
                """),
                {"g": resource_grant_id},
            )
            .mappings()
            .one()
        )
    assert audit_row["changed_fields"] == {
        "grantee_campaign_membership_id": None,
        "grantee_access_group_id": str(f.access_group_id),
        "target_kind": "character_id",
        "target_id": str(f.character_id),
        "capability_code": "character.view_summary",
        "effect": "deny",
    }


def test_a_no_op_revoke_of_an_already_revoked_resource_grant_records_no_audit_content(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The documented no-op case (`RevokeResourceGrantResult.revoked =
    False`) must never write a second `audit.change_log` row at all — see
    `test_revoking_an_already_revoked_resource_grant_writes_no_second_audit_
    row` above — so there is no second `changed_fields` payload to check
    here; this test instead confirms the *first* (real) revocation's audit
    content is unaffected by the harmless no-op retry that follows it."""
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
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    with postgres_engine.connect() as verify:
        audit_rows = (
            verify.execute(
                text("""
                    SELECT changed_fields FROM audit.change_log
                    WHERE table_name = 'resource_grants' AND record_id = :g
                      AND change_action_id = (
                          SELECT change_action_id FROM audit.change_actions WHERE code = 'updated'
                      )
                """),
                {"g": resource_grant_id},
            )
            .mappings()
            .all()
        )
    assert len(audit_rows) == 1
    assert audit_rows[0]["changed_fields"] == {
        "grantee_campaign_membership_id": str(f.target_membership_id),
        "grantee_access_group_id": None,
        "target_kind": "character_id",
        "target_id": str(f.character_id),
        "capability_code": "character.view_summary",
        "effect": "allow",
    }


# ---------------------------------------------------------------------------
# create_resource_grant — target-eligibility hardening (checkpoint 5)
# ---------------------------------------------------------------------------


def test_creating_a_resource_grant_on_an_ended_membership_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.ended_membership_id),
            },
        )
    assert response.status_code == 409, response.text


def test_creating_a_resource_grant_on_a_membership_with_a_disabled_account_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.disabled_account_membership_id),
            },
        )
    assert response.status_code == 409, response.text

    with postgres_engine.connect() as verify:
        grant_count = verify.execute(
            text(
                "SELECT count(*) FROM security.resource_grants "
                "WHERE grantee_campaign_membership_id = :m"
            ),
            {"m": f.disabled_account_membership_id},
        ).scalar_one()
        assert grant_count == 0


def test_creating_a_resource_grant_on_an_inactive_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Sequential ordering: the campaign is already inactive by the time
    the request reaches the command — mirroring `test_granting_a_
    relationship_on_an_inactive_campaign_is_rejected`'s identical shape."""
    _deactivate_campaign(postgres_engine, f.campaign_id)
    try:
        with client_factory(f.admin_user_id) as client:
            response = client.post(
                _resource_grants_url(f),
                json={
                    "character_id": str(f.character_id),
                    "capability_code": "character.view_summary",
                    "grantee_campaign_membership_id": str(f.target_membership_id),
                },
            )
        assert response.status_code == 409, response.text

        with postgres_engine.connect() as verify:
            grant_count = verify.execute(
                text("SELECT count(*) FROM security.resource_grants WHERE campaign_id = :c"),
                {"c": f.campaign_id},
            ).scalar_one()
            assert grant_count == 0
    finally:
        _reactivate_campaign(postgres_engine, f.campaign_id)


def test_a_resource_grant_rejected_for_campaign_inactivity_does_not_durably_complete_its_idempotency_key(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Mirrors `test_a_grant_rejected_for_campaign_inactivity_does_not_
    durably_complete_its_idempotency_key`'s identical reasoning: the whole
    request runs in one transaction, so `CampaignNotActiveError` rolls back
    the `begin_idempotent_request` reservation along with everything else —
    the same key, reused once the campaign is active again, must run the
    real command rather than replay a cached rejection."""
    key = f"create-grant-campaign-inactive-{uuid.uuid4().hex[:8]}"
    body = {
        "character_id": str(f.character_id),
        "capability_code": "character.view_summary",
        "grantee_campaign_membership_id": str(f.target_membership_id),
    }
    _deactivate_campaign(postgres_engine, f.campaign_id)
    try:
        with client_factory(f.admin_user_id) as client:
            rejected = client.post(
                _resource_grants_url(f), json=body, headers={"Idempotency-Key": key}
            )
        assert rejected.status_code == 409, rejected.text
    finally:
        _reactivate_campaign(postgres_engine, f.campaign_id)

    with client_factory(f.admin_user_id) as client:
        retried = client.post(_resource_grants_url(f), json=body, headers={"Idempotency-Key": key})
    assert retried.status_code == 201, retried.text


def test_creating_a_resource_grant_targeting_an_inactive_character_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.inactive_character_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 404, response.text


def test_creating_a_resource_grant_targeting_an_ended_session_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The one resource-grant target kind that is not a `core.entities` row
    — `campaign.sessions` carries its own `lifecycle_status_id` instead,
    checked separately by `_validate_resource_grant_target()`."""
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE campaign.sessions SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived'
                ) WHERE session_id = :s
            """),
            {"s": f.session_id},
        )
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "session_id": str(f.session_id),
                "capability_code": "campaign.view",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# create_resource_grant — delegation policy (checkpoint 5)
# ---------------------------------------------------------------------------


def test_creating_a_resource_grant_with_a_capability_incompatible_with_its_target_kind_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """`character.control` is a real, active capability — just never a
    valid pairing with a `quest_id` target under `dnd_ai.domain.access.
    RESOURCE_GRANT_CAPABILITY_CATALOG` (only `campaign.view`/`canon.edit`
    are). Folded into the same 404 as a nonexistent/deactivated code — a
    caller can never tell "incompatible" from either of those."""
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "quest_id": str(f.quest_id),
                "capability_code": "character.control",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 404, response.text

    with client_factory(f.admin_user_id) as client:
        # The identical capability succeeds against the target kind it
        # actually belongs to, proving the rejection above is about the
        # pairing, not the capability code itself.
        control_response = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.control",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert control_response.status_code == 201, control_response.text


def test_creating_a_resource_grant_of_character_discover_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """`character.discover` (checkpoint-5 correction) is deliberately
    excluded from `RESOURCE_GRANT_CAPABILITY_CATALOG`'s `character_id`
    entry even though it is otherwise a `character.*` code, matching the
    same 404 every other nonexistent/deactivated/incompatible capability
    code gets — see that catalog's own docstring for why: its baseline
    reader (`dnd_ai.api.world_explorer.resolve_world_character_visibility`)
    passes no resource target at all, so a resource-scoped grant of it can
    never move that check."""
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.discover",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 404, response.text


def test_creating_a_resource_grant_with_a_nonexistent_capability_code_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": f"no-such-capability-{uuid.uuid4().hex[:8]}",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 404, response.text


def test_creating_a_resource_grant_with_a_deactivated_capability_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """`character.view_summary` is a real, currently-catalogued
    `character_id`-target capability, temporarily deactivated for the
    duration of this test and restored afterward — this codebase's tests
    run single-worker/sequential (no parallel test execution), the same
    property `_deactivate_campaign`/the account-disablement tests above
    already rely on to safely mutate shared rows for one test's duration."""
    with postgres_engine.begin() as connection:
        connection.execute(
            text("UPDATE security.capabilities SET is_active = false WHERE code = :c"),
            {"c": "character.view_summary"},
        )
    try:
        with client_factory(f.admin_user_id) as client:
            response = client.post(
                _resource_grants_url(f),
                json={
                    "character_id": str(f.character_id),
                    "capability_code": "character.view_summary",
                    "grantee_campaign_membership_id": str(f.target_membership_id),
                },
            )
        assert response.status_code == 404, response.text
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text("UPDATE security.capabilities SET is_active = true WHERE code = :c"),
                {"c": "character.view_summary"},
            )


@pytest.mark.parametrize(
    "capability_code", ["access.manage", "import.approve", "rules_source.manage"]
)
def test_creating_a_resource_grant_with_an_administrative_capability_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, capability_code: str
) -> None:
    """`dnd_ai.domain.access.RESOURCE_GRANT_CAPABILITY_CATALOG` excludes
    these three from every resource-grant target kind entirely — delegating
    platform/campaign administration through a resource grant is disallowed
    as policy, not merely because it happens to be inert against every real
    `has_capability(...)` call site today."""
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _resource_grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": capability_code,
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
    assert response.status_code == 404, response.text
