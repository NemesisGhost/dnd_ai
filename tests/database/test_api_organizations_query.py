"""Tests for `dnd_ai.api.relationships`'s organization read endpoint —
Phase 10 workstream 19's query over `dnd_ai.queries.organization.
get_organization_view` (docs/PLAN.md Phase 10 "query services for the
effective dungeon, character, quest, relationship, inventory, encounter,
and knowledge state required by the vertical slice"), a sibling to
workstream 15's relationship read over the other half of `dnd_ai.api.
relationships`' command domain. Mirrors `tests/database/
test_api_dungeon.py`'s shape: `get_authenticated_user_id` is overridden
directly, since these tests exercise campaign-capability enforcement and
the public/internal description split, not OIDC token verification.

Covers: access control (non-member 404, capless-member 403), that
`public_description` and `status_code` are always returned to any
authorized caller while `internal_description` is returned only to a
caller holding `canon.edit` (and `None`, not merely withheld, otherwise),
the default when no `campaign.organization_state` row exists, and
cross-world/nonexistent-organization rejection.
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
    make_organization,
    make_organization_state,
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
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )

        self.organization_id = make_organization(
            connection,
            self.world_id,
            organization_type_code="guild",
            name="Thieves Guild",
            public_description="A merchants' guild.",
            internal_description="Actually a front for smuggling.",
        )
        make_organization_state(connection, self.timeline_id, self.organization_id)

        self.no_state_organization_id = make_organization(
            connection, self.world_id, name="Forgotten Order", public_description="Ancient lore."
        )

        # A second, unrelated world — its organization proves the
        # cross-world ownership check.
        self.other_world_id = make_world(connection, slug=f"{slug}-other-world")
        self.other_world_organization_id = make_organization(connection, self.other_world_id)

        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )

        self.gm_user_id = make_user(connection, "Organization Query GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, view_capability_id)
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        self.player_user_id = make_user(connection, "Organization Query Player")
        player_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.player_user_id
        )
        player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, player_role_id, view_capability_id)
        make_membership_role(connection, player_membership_id, player_role_id)

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Organization Query Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Organization Query Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"organization-query-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        # See tests/database/test_api_dungeon.py's identical cleanup
        # comment for why session_replication_role = replica and explicit,
        # dependency-ordered deletes are used here.
        for world_id in (fixture.world_id, fixture.other_world_id):
            cleanup.execute(
                text("""
                    DELETE FROM security.membership_roles WHERE role_id IN (
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
                    fixture.gm_user_id,
                    fixture.player_user_id,
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
        app.dependency_overrides[get_authenticated_user_id] = lambda: user_id
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _organization_url(f: Fixture, organization_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{f.campaign_id}/organizations/{organization_id or f.organization_id}"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_organization_url(f))
    assert response.status_code == 404


def test_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_organization_url(f))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# public_description vs. internal_description
# ---------------------------------------------------------------------------


def test_a_gm_sees_the_internal_description(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_organization_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["public_description"] == "A merchants' guild."
    assert body["internal_description"] == "Actually a front for smuggling."
    assert body["status_code"] == "active"


def test_a_player_never_sees_the_internal_description(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_organization_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["public_description"] == "A merchants' guild."
    assert body["internal_description"] is None
    assert body["status_code"] == "active"


def test_status_code_is_none_when_no_state_row_exists(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_organization_url(f, f.no_state_organization_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status_code"] is None


# ---------------------------------------------------------------------------
# Cross-world ownership and existence
# ---------------------------------------------------------------------------


def test_an_organization_in_a_different_world_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_organization_url(f, f.other_world_organization_id))
    assert response.status_code == 404


def test_a_nonexistent_organization_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_organization_url(f, uuid.uuid4()))
    assert response.status_code == 404
