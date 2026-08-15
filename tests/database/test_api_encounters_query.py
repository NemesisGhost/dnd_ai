"""Tests for `dnd_ai.api.encounters`'s read endpoint — Phase 10 workstream
17's query over `dnd_ai.queries.encounter.get_encounter_view` (docs/
PLAN.md Phase 10 "query services for the effective dungeon, character,
quest, relationship, inventory, encounter, and knowledge state required by
the vertical slice"). Mirrors `tests/database/test_api_dungeon.py`'s
shape: `get_authenticated_user_id` is overridden directly, since these
tests exercise campaign-capability enforcement and cross-campaign
ownership, not OIDC token verification.

Covers: access control (non-member 404, capless-member 403), that a
`campaign.view` caller sees the full participant/round/turn/combat-action
record with no audience filtering at all (unlike every other Phase 10
query), and cross-campaign rejection (`narrative.encounters.campaign_id`
is a direct column, unlike the world-scoped domains every earlier query
workstream checked).
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
    make_action,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_combat_action,
    make_encounter,
    make_encounter_participant,
    make_encounter_round,
    make_encounter_turn,
    make_interaction,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.other_campaign_id = make_campaign(
            connection, self.timeline_id, "Other Campaign", lifecycle_status_code="pending"
        )

        self.character_a_id = make_character(connection, self.world_id, name="Aria")
        self.character_b_id = make_character(connection, self.world_id, name="Goblin")

        self.encounter_id = make_encounter(
            connection,
            self.timeline_id,
            self.world_time_id,
            campaign_id=self.campaign_id,
            status="active",
            current_round=1,
        )
        self.participant_a_id = make_encounter_participant(
            connection, self.encounter_id, self.character_a_id, side="party", initiative=15
        )
        self.participant_b_id = make_encounter_participant(
            connection,
            self.encounter_id,
            self.character_b_id,
            side="enemy",
            initiative=10,
            outcome="defeated",
        )
        round_1_id = make_encounter_round(connection, self.encounter_id, 1)

        interaction_id = make_interaction(connection, self.timeline_id, self.world_time_id)
        action_id = make_action(connection, interaction_id, self.character_a_id)
        combat_action_id = make_combat_action(
            connection, action_id, action_kind="attack", hit=True, damage_amount=8
        )
        self.turn_id = make_encounter_turn(
            connection,
            round_1_id,
            self.participant_a_id,
            0,
            combat_action_id=combat_action_id,
            notes="A solid hit.",
        )

        # An encounter belonging only to the *other* campaign on the same
        # timeline — proves campaign_id is checked specifically, not just
        # timeline/world agreement.
        self.foreign_encounter_id = make_encounter(
            connection, self.timeline_id, self.world_time_id, campaign_id=self.other_campaign_id
        )

        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )

        self.player_user_id = make_user(connection, "Encounter Query Player")
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
        self.capless_user_id = make_user(connection, "Encounter Query Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Encounter Query Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"encounter-query-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        # See tests/database/test_api_dungeon.py's identical cleanup
        # comment for why session_replication_role = replica and explicit,
        # dependency-ordered deletes are used here.
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.roles WHERE campaign_id IN "
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
            text("DELETE FROM campaign.timelines WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {"users": [fixture.player_user_id, fixture.capless_user_id, fixture.outsider_user_id]},
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: user_id
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _encounter_url(
    f: Fixture, campaign_id: uuid.UUID | None = None, encounter_id: uuid.UUID | None = None
) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/encounters/{encounter_id or f.encounter_id}"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_encounter_url(f))
    assert response.status_code == 404


def test_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_encounter_url(f))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Full, unfiltered detail
# ---------------------------------------------------------------------------


def test_a_campaign_view_holder_sees_the_full_encounter_record(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_encounter_url(f))
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "active"
    assert body["current_round"] == 1
    assert {p["participant_entity_id"] for p in body["participants"]} == {
        str(f.character_a_id),
        str(f.character_b_id),
    }
    defeated = next(
        p for p in body["participants"] if p["participant_entity_id"] == str(f.character_b_id)
    )
    assert defeated["outcome"] == "defeated"
    assert defeated["side"] == "enemy"

    assert len(body["rounds"]) == 1
    round_1 = body["rounds"][0]
    assert round_1["round_number"] == 1
    assert len(round_1["turns"]) == 1
    turn = round_1["turns"][0]
    assert turn["encounter_turn_id"] == str(f.turn_id)
    assert turn["notes"] == "A solid hit."
    assert turn["combat_action"]["action_kind"] == "attack"
    assert turn["combat_action"]["hit"] is True
    assert turn["combat_action"]["damage_amount"] == 8


# ---------------------------------------------------------------------------
# Cross-campaign ownership
# ---------------------------------------------------------------------------


def test_an_encounter_belonging_to_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_encounter_url(f, encounter_id=f.foreign_encounter_id))
    assert response.status_code == 404


def test_a_nonexistent_encounter_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_encounter_url(f, encounter_id=uuid.uuid4()))
    assert response.status_code == 404
