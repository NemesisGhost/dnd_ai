"""Tests for `dnd_ai.api.relationships`'s read endpoint — Phase 10
workstream 15's query over `dnd_ai.queries.relationship.
get_relationship_view` (docs/PLAN.md Phase 10 "query services for the
effective dungeon, character, quest, relationship, ... state required by
the vertical slice"). Mirrors `tests/database/test_api_dungeon.py`'s
shape: `get_authenticated_user_id` is overridden directly, since these
tests exercise campaign-capability enforcement and the shared-vs-
subjective state split, not OIDC token verification.

Covers: access control (non-member 404, capless-member 403), that
participants and the shared, objective relationship state are always
returned to any authorized caller, that subjective per-participant state
(affinity/trust/private interpretation) is returned only to a caller
holding `canon.edit` and otherwise omitted entirely (not merely withheld
after being fetched), and cross-world/nonexistent-relationship rejection.
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
    make_character,
    make_membership_role,
    make_relationship,
    make_relationship_participant,
    make_relationship_state,
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
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )

        self.relationship_id = make_relationship(
            connection, self.world_id, relationship_type_code="alliance"
        )
        self.entity_a_id = make_character(connection, self.world_id, name="Aria")
        self.entity_b_id = make_character(connection, self.world_id, name="Borin")
        make_relationship_participant(
            connection, self.relationship_id, self.entity_a_id, role_code="subject"
        )
        make_relationship_participant(
            connection, self.relationship_id, self.entity_b_id, role_code="object"
        )

        make_relationship_state(
            connection, self.timeline_id, self.relationship_id, status_code="active", affinity=10
        )
        make_relationship_state(
            connection,
            self.timeline_id,
            self.relationship_id,
            perspective_holder_entity_id=self.entity_a_id,
            status_code="active",
            affinity=50,
            private_interpretation="secretly resents them",
        )
        make_relationship_state(
            connection,
            self.timeline_id,
            self.relationship_id,
            perspective_holder_entity_id=self.entity_b_id,
            status_code="estranged",
            affinity=-20,
        )

        # A second, unrelated world — its relationship proves the
        # cross-world ownership check (world.relationships carries no
        # campaign_id at all, so world agreement stands in for it).
        self.other_world_id = make_world(connection, slug=f"{slug}-other-world")
        self.other_world_relationship_id = make_relationship(connection, self.other_world_id)

        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )

        self.gm_user_id = make_user(connection, "Relationship Query GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, view_capability_id)
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        self.player_user_id = make_user(connection, "Relationship Query Player")
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
        self.capless_user_id = make_user(connection, "Relationship Query Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Relationship Query Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"relationship-query-{uuid.uuid4().hex[:8]}")
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
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _relationship_url(f: Fixture, relationship_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{f.campaign_id}/relationships/{relationship_id or f.relationship_id}"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_relationship_url(f))
    assert response.status_code == 404


def test_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_relationship_url(f))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Shared-vs-subjective state split
# ---------------------------------------------------------------------------


def test_a_gm_sees_shared_and_every_participants_subjective_state(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_relationship_url(f))
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["relationship_type_code"] == "alliance"
    assert {p["entity_id"] for p in body["participants"]} == {
        str(f.entity_a_id),
        str(f.entity_b_id),
    }
    assert body["shared_state"]["status_code"] == "active"
    assert body["shared_state"]["affinity"] == 10
    assert body["shared_state"]["perspective_holder_entity_id"] is None

    subjective_by_holder = {s["perspective_holder_entity_id"]: s for s in body["subjective_states"]}
    assert set(subjective_by_holder) == {str(f.entity_a_id), str(f.entity_b_id)}
    assert subjective_by_holder[str(f.entity_a_id)]["affinity"] == 50
    assert (
        subjective_by_holder[str(f.entity_a_id)]["private_interpretation"]
        == "secretly resents them"
    )
    assert subjective_by_holder[str(f.entity_b_id)]["status_code"] == "estranged"


def test_a_player_sees_shared_state_and_participants_but_no_subjective_states(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_relationship_url(f))
    assert response.status_code == 200, response.text
    body = response.json()

    assert {p["entity_id"] for p in body["participants"]} == {
        str(f.entity_a_id),
        str(f.entity_b_id),
    }
    assert body["shared_state"]["status_code"] == "active"
    assert body["shared_state"]["affinity"] == 10
    assert body["subjective_states"] == []


# ---------------------------------------------------------------------------
# Cross-world ownership and existence
# ---------------------------------------------------------------------------


def test_a_relationship_in_a_different_world_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_relationship_url(f, f.other_world_relationship_id))
    assert response.status_code == 404


def test_a_nonexistent_relationship_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_relationship_url(f, uuid.uuid4()))
    assert response.status_code == 404
