"""Draft/published separation in the World Explorer (Phase 14, D6).

Lifecycle-managed definitions that are not published never reach a caller
without `canon.edit`, in any list, search, detail, relationship, or participant
projection; archived and superseded definitions stay *referenceable* from
history but out of browse lists; a GM can preview drafts and archived records,
and a player's identical flags are silently ignored.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.builders import make_authored_campaign, make_authored_world
from tests.factories import (
    make_event,
    make_location,
    make_organization,
    make_relationship,
    make_relationship_participant,
    make_religion,
    make_world_time,
    status_id,
)

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


class Setup:
    def __init__(self, harness: AuthoringHarness, connection: Connection) -> None:
        self.connection = connection
        self.gm: Actor = harness.new_actor("GM")
        self.player: Actor = harness.new_actor("Player")
        self.world = make_authored_world(connection, owner_user_id=self.gm.user_id)
        self.campaign = make_authored_campaign(connection, self.world)
        connection.execute(
            text("""
                INSERT INTO security.campaign_memberships
                    (campaign_id, user_id, membership_status_id, joined_at)
                VALUES (:c, :u, (SELECT membership_status_id FROM security.membership_statuses
                                 WHERE code = 'active'), now())
            """),
            {"c": self.campaign, "u": self.player.user_id},
        )
        connection.execute(
            text("""
                INSERT INTO security.membership_roles (campaign_membership_id, role_id)
                SELECT cm.campaign_membership_id, r.role_id
                FROM security.campaign_memberships cm, security.roles r
                WHERE cm.campaign_id = :c AND cm.user_id = :u
                  AND r.code = 'player' AND r.campaign_id IS NULL
            """),
            {"c": self.campaign, "u": self.player.user_id},
        )

    def mark(
        self, entity_id: uuid.UUID, canon: str = "canon", lifecycle: str = "active"
    ) -> uuid.UUID:
        self.connection.execute(
            text(
                "UPDATE core.entities SET canon_status_id = :c, lifecycle_status_id = :l "
                "WHERE entity_id = :e"
            ),
            {
                "c": status_id(self.connection, "canon_statuses", canon),
                "l": status_id(self.connection, "lifecycle_statuses", lifecycle),
                "e": entity_id,
            },
        )
        return entity_id

    def location(self, name: str, canon: str = "canon", lifecycle: str = "active") -> uuid.UUID:
        return self.mark(
            make_location(self.connection, self.world.world_id, name=name), canon, lifecycle
        )

    def names(self, actor: Actor, **params: object) -> list[str]:
        response = actor.get(f"/campaigns/{self.campaign}/world/search", **params)
        assert response.status_code == 200, response.text
        return [item["name"] for item in response.json()["items"]]

    def get(self, actor: Actor, path: str):  # type: ignore[no-untyped-def]
        return actor.get(f"/campaigns/{self.campaign}/{path}")


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> Setup:
    return Setup(harness, db_connection)


def _seed(s: Setup) -> dict[str, uuid.UUID]:
    return {
        status: s.location(f"{status.title()} Place", canon=status)
        for status in ("canon", "draft", "proposed", "approved", "rejected", "superseded")
    } | {"archived": s.location("Archived Place", lifecycle="archived")}


def test_a_player_browses_only_published_active_definitions(s: Setup) -> None:
    _seed(s)
    assert s.names(s.player, q="Place") == ["Canon Place"]


def test_a_gm_browses_published_active_by_default_and_previews_on_request(s: Setup) -> None:
    _seed(s)
    assert s.names(s.gm, q="Place") == ["Canon Place"]
    everything = s.names(s.gm, q="Place", include_noncanon="true", include_archived="true")
    assert sorted(everything) == sorted(
        [
            "Canon Place",
            "Draft Place",
            "Proposed Place",
            "Approved Place",
            "Rejected Place",
            "Superseded Place",
            "Archived Place",
        ]
    )
    noncanon_only = s.names(s.gm, q="Place", include_noncanon="true")
    assert "Archived Place" not in noncanon_only and "Draft Place" in noncanon_only
    archived_only = s.names(s.gm, q="Place", include_archived="true")
    assert "Archived Place" in archived_only and "Draft Place" not in archived_only


def test_a_players_preview_flags_are_silently_ignored(s: Setup) -> None:
    _seed(s)
    assert s.names(s.player, q="Place", include_noncanon="true", include_archived="true") == [
        "Canon Place"
    ]


def test_search_cards_carry_status_codes(s: Setup) -> None:
    s.location("Archived Card", lifecycle="archived")
    response = s.gm.get(f"/campaigns/{s.campaign}/world/search", q="Card", include_archived="true")
    assert response.json()["items"][0]["lifecycle_status"] == "archived"
    assert response.json()["items"][0]["canon_status"] == "canon"


@pytest.mark.parametrize("status", ["draft", "proposed", "approved", "rejected"])
def test_unpublished_detail_is_the_same_404_for_a_player_but_open_to_a_gm(
    s: Setup, status: str
) -> None:
    place = s.location("Hidden", canon=status)
    path = f"world/locations/{place}"
    missing = s.get(s.player, f"world/locations/{uuid.uuid4()}")
    hidden = s.get(s.player, path)
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json()["error"]["code"] == missing.json()["error"]["code"]
    assert hidden.json()["error"]["message"] == missing.json()["error"]["message"]
    seen = s.get(s.gm, path)
    assert seen.status_code == 200
    assert (seen.json()["canon_status"], seen.json()["lifecycle_status"]) == (status, "active")


def test_archived_and_superseded_definitions_stay_referenceable(s: Setup) -> None:
    archived = s.location("Old Fort", lifecycle="archived")
    old = s.location("Old Name", canon="superseded")
    new = s.location("New Name")
    s.connection.execute(
        text("UPDATE core.entities SET superseded_by_entity_id = :n WHERE entity_id = :o"),
        {"n": new, "o": old},
    )
    detail = s.get(s.player, f"world/locations/{archived}")
    assert detail.status_code == 200
    assert detail.json()["lifecycle_status"] == "archived"
    superseded = s.get(s.player, f"world/locations/{old}").json()
    assert superseded["canon_status"] == "superseded"
    assert superseded["superseded_by"] == {"entity_id": str(new), "name": "New Name"}


def test_a_replacement_that_is_not_visible_is_not_named(s: Setup) -> None:
    old = s.location("Old Name", canon="superseded")
    draft_replacement = s.location("Secret Plan", canon="draft")
    s.connection.execute(
        text("UPDATE core.entities SET superseded_by_entity_id = :n WHERE entity_id = :o"),
        {"n": draft_replacement, "o": old},
    )
    player_view = s.get(s.player, f"world/locations/{old}")
    assert player_view.json()["superseded_by"] is None
    assert "Secret Plan" not in player_view.text
    assert s.get(s.gm, f"world/locations/{old}").json()["superseded_by"]["name"] == "Secret Plan"


def test_a_deleted_definition_is_hidden_from_everyone(s: Setup) -> None:
    gone = s.location("Gone", lifecycle="deleted")
    assert s.get(s.gm, f"world/locations/{gone}").status_code == 404
    assert s.get(s.player, f"world/locations/{gone}").status_code == 404
    assert "Gone" not in s.names(s.gm, include_noncanon="true", include_archived="true")


def test_religion_and_organization_details_follow_the_same_rule(s: Setup) -> None:
    religion = s.mark(make_religion(s.connection, s.world.world_id, name="Draft Faith"), "draft")
    org = s.mark(make_organization(s.connection, s.world.world_id, name="Draft Guild"), "draft")
    for path in (f"world/religions/{religion}", f"organizations/{org}"):
        assert s.get(s.player, path).status_code == 404, path
        assert s.get(s.gm, path).status_code == 200, path
    published = s.mark(make_religion(s.connection, s.world.world_id, name="Real Faith"))
    assert s.get(s.player, f"world/religions/{published}").status_code == 200


def test_relationships_with_an_unpublished_participant_are_suppressed_whole(s: Setup) -> None:
    visible = s.location("Visible")
    draft = s.location("Draft Keep", canon="draft")
    archived = s.location("Archived Keep", lifecycle="archived")
    hidden_edge = make_relationship(s.connection, s.world.world_id, description="secret")
    make_relationship_participant(s.connection, hidden_edge, visible)
    make_relationship_participant(s.connection, hidden_edge, draft, role_code="object")
    historic_edge = make_relationship(s.connection, s.world.world_id, description="history")
    make_relationship_participant(s.connection, historic_edge, visible)
    make_relationship_participant(s.connection, historic_edge, archived, role_code="object")

    listed = s.get(s.player, "world/relationships").json()["items"]
    ids = {item["relationship_id"] for item in listed}
    assert str(hidden_edge) not in ids
    assert str(historic_edge) in ids  # archived stays referenceable
    assert s.get(s.player, f"relationships/{hidden_edge}").status_code == 404
    assert s.get(s.player, f"relationships/{historic_edge}").status_code == 200
    gm_ids = {i["relationship_id"] for i in s.get(s.gm, "world/relationships").json()["items"]}
    assert str(hidden_edge) in gm_ids
    assert s.get(s.gm, f"relationships/{hidden_edge}").status_code == 200


def test_event_participants_and_locations_omit_unpublished_definitions(s: Setup) -> None:
    visible = s.location("Visible Hall")
    draft = s.location("Draft Hall", canon="draft")
    time = make_world_time(s.connection, s.world.world_id, 10)
    event = make_event(
        s.connection, s.world.world_id, s.world.primary_timeline_id, time, name="Feast"
    )
    s.connection.execute(
        text("""
            INSERT INTO narrative.event_locations (event_id, location_id, event_location_role)
            VALUES (:e, :a, 'occurred_at'), (:e, :b, 'affected')
        """),
        {"e": event, "a": visible, "b": draft},
    )
    player = s.get(s.player, f"world/events/{event}").json()
    assert [loc["location_id"] for loc in player["locations"]] == [str(visible)]
    gm = s.get(s.gm, f"world/events/{event}").json()
    assert {loc["location_id"] for loc in gm["locations"]} == {str(visible), str(draft)}


def test_publishing_through_the_lifecycle_routes_makes_it_visible_to_players(s: Setup) -> None:
    place = s.location("Slow Burn", canon="draft")
    url = f"/campaigns/{s.campaign}/entities/{place}/lifecycle"
    assert s.names(s.player, q="Slow") == []
    for suffix in ("submit-for-review", "approve", "publish"):
        version = s.gm.get(url).json()["row_version"]
        response = s.gm.post(f"{url}/{suffix}", {"expected_row_version": version})
        assert response.status_code == 200, response.text
        if suffix != "publish":
            assert s.names(s.player, q="Slow") == []
    assert s.names(s.player, q="Slow") == ["Slow Burn"]

    version = s.gm.get(url).json()["row_version"]
    s.gm.post(f"{url}/archive", {"expected_row_version": version})
    assert s.names(s.player, q="Slow") == []
    assert s.get(s.player, f"world/locations/{place}").status_code == 200
    version = s.gm.get(url).json()["row_version"]
    s.gm.post(f"{url}/restore", {"expected_row_version": version, "reason": "back"})
    assert s.names(s.player, q="Slow") == ["Slow Burn"]
