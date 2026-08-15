"""Tests for `dnd_ai.api.dungeon` — Phase 10 workstream 12's query endpoint
over `dnd_ai.queries.dungeon.get_dungeon_area_view` (docs/PLAN.md Phase 10
"query services for the effective dungeon, ... state required by the
vertical slice"). Mirrors `tests/database/test_api_quests.py`'s shape:
`get_authenticated_user_id` is overridden directly, since these tests
exercise campaign-capability enforcement, party-scoped audience filtering,
and cross-world ownership — not OIDC token verification, already covered
by `tests/database/test_api_auth.py`.

Covers: access control (non-member/capless-member), GM vs. player audience
filtering (a GM sees every structural child regardless of `is_hidden`; a
player sees a hidden child only once their party has discovered it, and
otherwise not at all — not merely flagged, per docs/PLAN.md §25 step 15's
"cannot be inferred through counts... or errors"), the `party_id`/
`campaign_id` cross-campaign rejection `dnd_ai.commands._shared.
validate_campaign_party` now shares with `dnd_ai.api.quests`, and the
cross-world "does this area belong to my campaign" rejection unique to
this query (no `campaign_id` column exists on any dungeon-domain table, so
world agreement is what stands in for it, mirroring `dnd_ai.api.
integration`'s identical reasoning for `map_external_identifier`).
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
    make_area_connection,
    make_area_feature,
    make_area_hazard,
    make_area_interactable,
    make_campaign,
    make_campaign_membership,
    make_campaign_party,
    make_dungeon,
    make_dungeon_area,
    make_knowledge_item,
    make_membership_role,
    make_party,
    make_party_discovery,
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
        # invariant (revision 080) — these tests grant campaign.view/
        # canon.edit, not access.manage, and don't otherwise care about
        # campaign lifecycle (same reasoning test_api_quests.py's Fixture
        # documents).
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.other_campaign_id = make_campaign(
            connection, self.timeline_id, "Other Campaign", lifecycle_status_code="pending"
        )

        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_a_id = make_dungeon_area(connection, self.dungeon_id, name="Area A")
        self.area_b_id = make_dungeon_area(connection, self.dungeon_id, name="Area B")

        self.visible_feature_id = make_area_feature(connection, self.area_a_id, is_hidden=False)
        self.hidden_feature_id = make_area_feature(connection, self.area_a_id, is_hidden=True)
        self.hidden_feature_knowledge_id = make_knowledge_item(
            connection,
            self.world_id,
            statement="A statue hides a switch.",
            subject_area_feature_id=self.hidden_feature_id,
        )

        self.visible_hazard_id = make_area_hazard(connection, self.area_a_id, is_hidden=False)
        self.hidden_hazard_id = make_area_hazard(connection, self.area_a_id, is_hidden=True)
        make_knowledge_item(
            connection,
            self.world_id,
            statement="A pressure plate trap is set here.",
            subject_area_hazard_id=self.hidden_hazard_id,
        )

        self.visible_interactable_id = make_area_interactable(
            connection, self.area_a_id, is_hidden=False
        )
        self.hidden_interactable_id = make_area_interactable(
            connection, self.area_a_id, is_hidden=True
        )
        make_knowledge_item(
            connection,
            self.world_id,
            statement="A hidden lever is set into the wall.",
            subject_area_interactable_id=self.hidden_interactable_id,
        )

        self.visible_connection_id = make_area_connection(
            connection, self.area_a_id, self.area_b_id, is_hidden=False
        )
        self.hidden_connection_id = make_area_connection(
            connection, self.area_a_id, self.area_b_id, is_hidden=True
        )
        make_knowledge_item(
            connection,
            self.world_id,
            statement="A secret door connects these rooms.",
            subject_area_connection_id=self.hidden_connection_id,
        )

        self.party_id = make_party(connection, self.world_id, name="The Company")
        make_campaign_party(connection, self.campaign_id, self.party_id)
        # Discovers only the hidden feature — proves filtering is per
        # structural child, not an all-or-nothing party flag.
        make_party_discovery(
            connection,
            self.timeline_id,
            self.hidden_feature_knowledge_id,
            party_id=self.party_id,
        )

        # Associated only with the *other* campaign — same world/timeline,
        # so campaign.enforce_campaign_party_world() alone lets it through.
        # Proves party_id is checked against campaign_id specifically.
        self.foreign_party_id = make_party(connection, self.world_id, name="Foreign Party")
        make_campaign_party(connection, self.other_campaign_id, self.foreign_party_id)

        # A second, unrelated world — its dungeon area proves the
        # cross-world ownership check (no campaign_id column exists on any
        # dungeon-domain table, so world agreement stands in for it).
        self.other_world_id = make_world(connection, slug=f"{slug}-other-world")
        other_dungeon_id = make_dungeon(connection, self.other_world_id)
        self.other_world_area_id = make_dungeon_area(connection, other_dungeon_id)

        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )

        self.gm_user_id = make_user(connection, "Dungeon API GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, view_capability_id)
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        self.player_user_id = make_user(connection, "Dungeon API Player")
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
        self.capless_user_id = make_user(connection, "Dungeon API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Dungeon API Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"dungeon-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        # See tests/database/test_api_quests.py's identical cleanup comment:
        # session_replication_role = replica disables the cascades the
        # later DELETE FROM core.entities/core.worlds statements would
        # otherwise apply, and revision 080's DEFERRABLE constraint
        # triggers on several security.* tables can fail a later, unrelated
        # test in the same pytest session if left behind. Deleted
        # explicitly here, in dependency order, scoped to this fixture's
        # two worlds.
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
                    DELETE FROM knowledge.party_discoveries WHERE knowledge_item_id IN (
                        SELECT knowledge_item_id FROM knowledge.knowledge_items ki
                        JOIN core.entities e ON e.entity_id = ki.knowledge_item_id
                        WHERE e.world_id = :w
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM campaign.campaign_parties WHERE campaign_id IN (
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
                text("DELETE FROM campaign.parties WHERE world_id = :w"), {"w": world_id}
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


def _area_url(f: Fixture, area_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{f.campaign_id}/dungeon-areas/{area_id or f.area_a_id}"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_area_url(f))
    assert response.status_code == 404


def test_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_area_url(f))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Audience filtering
# ---------------------------------------------------------------------------


def test_a_gm_sees_every_structural_child_including_hidden_ones(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_area_url(f))
    assert response.status_code == 200, response.text
    body = response.json()

    assert {feat["area_feature_id"] for feat in body["features"]} == {
        str(f.visible_feature_id),
        str(f.hidden_feature_id),
    }
    assert {haz["area_hazard_id"] for haz in body["hazards"]} == {
        str(f.visible_hazard_id),
        str(f.hidden_hazard_id),
    }
    assert {ia["area_interactable_id"] for ia in body["interactables"]} == {
        str(f.visible_interactable_id),
        str(f.hidden_interactable_id),
    }
    assert {c["area_connection_id"] for c in body["connections"]} == {
        str(f.visible_connection_id),
        str(f.hidden_connection_id),
    }


def test_a_player_with_no_party_sees_only_non_hidden_content(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_area_url(f))
    assert response.status_code == 200, response.text
    body = response.json()

    assert {feat["area_feature_id"] for feat in body["features"]} == {str(f.visible_feature_id)}
    assert {haz["area_hazard_id"] for haz in body["hazards"]} == {str(f.visible_hazard_id)}
    assert {ia["area_interactable_id"] for ia in body["interactables"]} == {
        str(f.visible_interactable_id)
    }
    assert {c["area_connection_id"] for c in body["connections"]} == {str(f.visible_connection_id)}


def test_a_player_with_a_party_sees_only_what_that_party_discovered(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_area_url(f), params={"party_id": str(f.party_id)})
    assert response.status_code == 200, response.text
    body = response.json()

    # The party discovered only the hidden feature — the hidden hazard,
    # interactable, and connection remain excluded entirely, not merely
    # flagged (docs/PLAN.md §25 step 15's non-disclosure rule).
    assert {feat["area_feature_id"] for feat in body["features"]} == {
        str(f.visible_feature_id),
        str(f.hidden_feature_id),
    }
    discovered_feature = next(
        feat for feat in body["features"] if feat["area_feature_id"] == str(f.hidden_feature_id)
    )
    assert discovered_feature["is_hidden"] is True

    assert {haz["area_hazard_id"] for haz in body["hazards"]} == {str(f.visible_hazard_id)}
    assert {ia["area_interactable_id"] for ia in body["interactables"]} == {
        str(f.visible_interactable_id)
    }
    assert {c["area_connection_id"] for c in body["connections"]} == {str(f.visible_connection_id)}


def test_connection_direction_is_reported_relative_to_the_queried_area(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_area_url(f))
    assert response.status_code == 200, response.text
    body = response.json()

    visible = next(
        c for c in body["connections"] if c["area_connection_id"] == str(f.visible_connection_id)
    )
    assert visible["direction"] == "outgoing"
    assert visible["other_dungeon_area_id"] == str(f.area_b_id)


def test_location_state_defaults_when_no_state_row_exists(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_area_url(f))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_searched"] is False
    assert body["is_destroyed"] is False
    assert body["alarm_level"] == 0
    assert body["condition_notes"] is None


# ---------------------------------------------------------------------------
# Party/campaign and world/campaign scope
# (dnd_ai.commands._shared.validate_campaign_party,
#  dnd_ai.queries.dungeon.DungeonAreaNotFoundError)
# ---------------------------------------------------------------------------


def test_a_party_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_area_url(f), params={"party_id": str(f.foreign_party_id)})
    assert response.status_code == 404


def test_an_area_in_a_different_world_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_area_url(f, f.other_world_area_id))
    assert response.status_code == 404


def test_a_nonexistent_area_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_area_url(f, uuid.uuid4()))
    assert response.status_code == 404
