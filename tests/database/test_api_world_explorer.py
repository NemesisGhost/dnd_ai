"""Tests for `dnd_ai.api.world_explorer` — the Phase 13D World Explorer
read API (unified entity search/browse, relationship list, and typed
detail routes for religions / item instances / historical events /
generic locations).

Covers, per docs/PHASE13D_BACKEND_READINESS.md §9: access control; every
supported category in search; category/type filtering; case-insensitive
search; deterministic ordering; first and subsequent cursor pages; invalid
cursor / invalid limit; empty results; GM canonical view; player/observer;
targeted `campaign.view` allow/deny; character-discover gating; event
timeline isolation and draft/voided handling; list/detail agreement;
inaccessible parent omitted from breadcrumbs; inaccessible related
resource omitted; nonexistent vs inaccessible detail returning identical
safe errors.

Follows the per-endpoint Fixture/cleanup convention of
`test_api_quests_list.py` / `test_api_organizations_query.py` rather than a
new shared harness.
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
    make_character_relationship_type,
    make_event,
    make_item_definition,
    make_item_instance,
    make_location,
    make_membership_character_relationship,
    make_membership_role,
    make_organization,
    make_relationship,
    make_relationship_participant,
    make_relationship_type_capability,
    make_religion,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_ruleset_version_for_world,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug, name="Explorer World")
        self.other_world_id = make_world(connection, slug=f"{slug}-other", name="Other World")
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        # A second timeline in the SAME world — for event isolation.
        self.other_timeline_id = make_timeline(connection, self.world_id, name="Sidebranch")
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )

        # --- world entities across every category ---------------------
        self.region_id = make_location(
            connection, self.world_id, entity_type_code="region", name="Amber Reach"
        )
        self.settlement_id = make_location(
            connection,
            self.world_id,
            entity_type_code="settlement",
            name="Brasshollow",
            parent_location_id=self.region_id,
        )
        connection.execute(
            text("INSERT INTO world.settlements (settlement_id, population) VALUES (:s, 4000)"),
            {"s": self.settlement_id},
        )
        # A location whose parent will be denied to the player.
        self.hidden_parent_id = make_location(
            connection, self.world_id, entity_type_code="region", name="Forbidden March"
        )
        self.child_of_hidden_id = make_location(
            connection,
            self.world_id,
            entity_type_code="building",
            name="Cindergate Watchtower",
            parent_location_id=self.hidden_parent_id,
        )
        connection.execute(
            text("INSERT INTO world.buildings (building_id, building_use) VALUES (:b, 'tower')"),
            {"b": self.child_of_hidden_id},
        )

        self.org_id = make_organization(connection, self.world_id, name="The Cartographers Guild")
        self.religion_id = make_religion(connection, self.world_id, name="The Ember Faith")

        item_def_id = make_item_definition(
            connection, make_ruleset_version_for_world(connection, self.world_id)
        )
        self.item_id = make_item_instance(
            connection, self.world_id, item_def_id, name="Blade of Saint Orra"
        )

        # Historical events: one recorded on the campaign timeline, one
        # recorded on the OTHER same-world timeline, one voided, one draft.
        self.event_id = make_event(
            connection,
            self.world_id,
            self.timeline_id,
            self.world_time_id,
            name="The Sundering of Brasshollow",
        )
        self.other_timeline_event_id = make_event(
            connection,
            self.world_id,
            self.other_timeline_id,
            self.world_time_id,
            name="A Sidebranch Skirmish",
        )
        self.voided_event_id = make_event(
            connection,
            self.world_id,
            self.timeline_id,
            self.world_time_id,
            name="The Retracted Council",
            event_status_code="voided",
        )
        self.draft_event_id = make_event(
            connection,
            self.world_id,
            self.timeline_id,
            self.world_time_id,
            name="An Unfinished Rumor",
            event_status_code="draft",
        )

        # Characters: one plain, one the player will get a relationship to.
        self.npc_id = make_character(connection, self.world_id, name="Vashka the Quiet")
        self.pc_id = make_character(connection, self.world_id, name="Aldric Vane")

        # A relationship between two visible entities, and one that
        # involves a character the player cannot discover.
        self.visible_relationship_id = make_relationship(
            connection,
            self.world_id,
            relationship_type_code="control",
            description="Guild oversight of the reach",
        )
        make_relationship_participant(connection, self.visible_relationship_id, self.org_id)
        make_relationship_participant(
            connection, self.visible_relationship_id, self.region_id, role_code="object"
        )
        self.character_relationship_id = make_relationship(
            connection,
            self.world_id,
            relationship_type_code="rivalry",
            description="A quiet feud",
        )
        make_relationship_participant(connection, self.character_relationship_id, self.org_id)
        make_relationship_participant(
            connection, self.character_relationship_id, self.npc_id, role_code="object"
        )

        # --- users / roles -------------------------------------------
        self.view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        discover_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_summary"
        )

        self.gm_user_id = make_user(connection, "Explorer GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        self.gm_membership_id = gm_membership_id
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, self.view_capability_id)
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        self.player_user_id = make_user(connection, "Explorer Player")
        player_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.player_user_id
        )
        self.player_membership_id = player_membership_id
        player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, player_role_id, self.view_capability_id)
        make_membership_role(connection, player_membership_id, player_role_id)

        # The player gets a per-character view_summary relationship to
        # exactly one character (self.pc_id).
        self.relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(
            connection, self.relationship_type_id, discover_capability_id
        )
        make_membership_character_relationship(
            connection,
            player_membership_id,
            self.pc_id,
            self.relationship_type_id,
            timeline_id=self.timeline_id,
        )

        # A member with no capability at all.
        self.capless_user_id = make_user(connection, "Explorer Capless")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # A non-member.
        self.outsider_user_id = make_user(connection, "Explorer Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"world-explorer-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        for stmt, param in [
            (
                "DELETE FROM security.membership_character_relationships "
                "WHERE campaign_membership_id IN (SELECT campaign_membership_id "
                "FROM security.campaign_memberships WHERE campaign_id = :c)",
                {"c": fixture.campaign_id},
            ),
            (
                "DELETE FROM security.membership_roles WHERE role_id IN "
                "(SELECT role_id FROM security.roles WHERE campaign_id = :c)",
                {"c": fixture.campaign_id},
            ),
            (
                "DELETE FROM security.role_capabilities WHERE role_id IN "
                "(SELECT role_id FROM security.roles WHERE campaign_id = :c)",
                {"c": fixture.campaign_id},
            ),
            ("DELETE FROM security.roles WHERE campaign_id = :c", {"c": fixture.campaign_id}),
            (
                "DELETE FROM security.resource_grants WHERE campaign_id = :c",
                {"c": fixture.campaign_id},
            ),
            (
                "DELETE FROM security.campaign_memberships WHERE campaign_id = :c",
                {"c": fixture.campaign_id},
            ),
            ("DELETE FROM campaign.campaigns WHERE campaign_id = :c", {"c": fixture.campaign_id}),
            (
                "DELETE FROM world.relationship_participants WHERE relationship_id IN "
                "(SELECT relationship_id FROM world.relationships WHERE world_id = :w)",
                {"w": fixture.world_id},
            ),
            ("DELETE FROM world.relationships WHERE world_id = :w", {"w": fixture.world_id}),
            (
                "DELETE FROM campaign.timelines WHERE world_id = ANY(:w)",
                {"w": [fixture.world_id, fixture.other_world_id]},
            ),
            (
                "DELETE FROM core.entities WHERE world_id = ANY(:w)",
                {"w": [fixture.world_id, fixture.other_world_id]},
            ),
            (
                "DELETE FROM core.worlds WHERE world_id = ANY(:w)",
                {"w": [fixture.world_id, fixture.other_world_id]},
            ),
            (
                "DELETE FROM security.character_relationship_type_capabilities "
                "WHERE character_relationship_type_id = :rt",
                {"rt": fixture.relationship_type_id},
            ),
            (
                "DELETE FROM security.character_relationship_types "
                "WHERE character_relationship_type_id = :rt",
                {"rt": fixture.relationship_type_id},
            ),
            (
                "DELETE FROM security.users WHERE user_id = ANY(:u)",
                {
                    "u": [
                        fixture.gm_user_id,
                        fixture.player_user_id,
                        fixture.capless_user_id,
                        fixture.outsider_user_id,
                    ]
                },
            ),
        ]:
            cleanup.execute(text(stmt), param)


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        from tests.factories import oidc_principal

        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _search(f: Fixture) -> str:
    return f"/campaigns/{f.campaign_id}/world/search"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_search_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        assert client.get(_search(f)).status_code == 404


def test_search_capless_member_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        assert client.get(_search(f)).status_code == 403


# ---------------------------------------------------------------------------
# Categories, filtering, search, ordering
# ---------------------------------------------------------------------------


def test_every_documented_category_is_reachable_via_search(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        body = client.get(_search(f), params={"limit": 100}).json()
    categories = {item["category"] for item in body["items"]}
    assert {"location", "organization", "religion", "item", "event", "character"} <= categories


def test_category_filter_restricts_results(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        body = client.get(_search(f), params={"category": "religion", "limit": 100}).json()
    assert {item["category"] for item in body["items"]} == {"religion"}
    assert any(item["entity_id"] == str(f.religion_id) for item in body["items"])


def test_search_is_case_insensitive(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        body = client.get(_search(f), params={"q": "bRaSs", "limit": 100}).json()
    names = {item["name"] for item in body["items"]}
    assert "Brasshollow" in names


def test_results_are_deterministically_ordered_by_name(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        items = client.get(_search(f), params={"limit": 100}).json()["items"]
    names = [item["name"].lower() for item in items]
    assert names == sorted(names)


def test_cursor_pages_cover_all_results_without_overlap(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        seen: list[str] = []
        cursor: str | None = None
        for _ in range(20):
            params = {"limit": 2}
            if cursor:
                params["cursor"] = cursor
            body = client.get(_search(f), params=params).json()
            seen.extend(item["entity_id"] for item in body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert len(seen) == len(set(seen))  # no duplicates across pages
        with client_factory(f.gm_user_id) as c2:
            one_shot = c2.get(_search(f), params={"limit": 100}).json()["items"]
        assert set(seen) == {item["entity_id"] for item in one_shot}


def test_a_generated_cursor_for_a_non_bmp_name_is_accepted_on_the_next_page(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Regression (review f66441f, Medium #1): an entity name whose 200-char
    sort prefix is supplementary-plane Unicode must still produce a
    `next_cursor` the decoder accepts."""
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE core.entities SET canonical_name = :s "
                "WHERE world_id = :w AND entity_id IN (:a, :b)"
            ),
            {"s": "\U0001f409" * 200, "w": f.world_id, "a": f.pc_id, "b": f.npc_id},
        )
    params = {"category": "character", "limit": 1}
    with client_factory(f.gm_user_id) as client:
        first = client.get(_search(f), params=params).json()
        cursor = first["next_cursor"]
        assert cursor
        second = client.get(_search(f), params={**params, "cursor": cursor})
    assert second.status_code == 200, f"cursor len={len(cursor)}"
    first_ids = [i["entity_id"] for i in first["items"]]
    second_ids = [i["entity_id"] for i in second.json()["items"]]
    assert set(first_ids).isdisjoint(second_ids)


def test_search_cursor_walks_names_that_share_a_long_prefix_exactly_once(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Several names sharing the full 200-char sort prefix must still be
    traversed once each via the unique `entity_id` tie-breaker."""
    shared = "Q" * 240
    made: set[str] = set()
    with postgres_engine.begin() as connection:
        for suffix in ("-one", "-two", "-three"):
            loc_id = make_location(
                connection, f.world_id, entity_type_code="region", name=f"{shared}{suffix}"
            )
            made.add(str(loc_id))
    seen: list[str] = []
    cursor: str | None = None
    with client_factory(f.gm_user_id) as client:
        for _ in range(40):
            params = {"category": "location", "limit": 1}
            if cursor:
                params["cursor"] = cursor
            body = client.get(_search(f), params=params).json()
            seen.extend(i["entity_id"] for i in body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                break
    assert len(seen) == len(set(seen)), "an entity appeared on more than one page"
    assert made <= set(seen), "a shared-prefix entity was skipped"


def test_invalid_cursor_is_rejected_with_422(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_search(f), params={"cursor": "not-a-real-cursor"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_cursor"


def test_a_cursor_from_a_different_keyset_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        rel_body = client.get(
            f"/campaigns/{f.campaign_id}/world/relationships", params={"limit": 1}
        ).json()
        if rel_body["next_cursor"] is None:
            pytest.skip("only one visible relationship — no relationship cursor to misuse")
        response = client.get(_search(f), params={"cursor": rel_body["next_cursor"]})
    assert response.status_code == 422


def test_invalid_limit_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        assert client.get(_search(f), params={"limit": 0}).status_code == 422
        assert client.get(_search(f), params={"limit": 9999}).status_code == 422


def test_a_search_with_no_matches_returns_an_empty_list_not_a_hint(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        body = client.get(_search(f), params={"q": "zzz-nonexistent-zzz"}).json()
    assert body == {"items": [], "next_cursor": None}


# ---------------------------------------------------------------------------
# GM vs player: character discovery + events
# ---------------------------------------------------------------------------


def test_gm_sees_both_characters_but_player_sees_only_the_related_one(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as gm:
        gm_ids = {
            item["entity_id"]
            for item in gm.get(_search(f), params={"category": "character", "limit": 100}).json()[
                "items"
            ]
        }
    with client_factory(f.player_user_id) as player:
        player_ids = {
            item["entity_id"]
            for item in player.get(
                _search(f), params={"category": "character", "limit": 100}
            ).json()["items"]
        }
    assert {str(f.npc_id), str(f.pc_id)} <= gm_ids
    assert str(f.pc_id) in player_ids
    assert str(f.npc_id) not in player_ids


def test_voided_events_are_never_listed_and_draft_only_for_a_gm(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as gm:
        gm_ids = {
            item["entity_id"]
            for item in gm.get(_search(f), params={"category": "event", "limit": 100}).json()[
                "items"
            ]
        }
    with client_factory(f.player_user_id) as player:
        player_ids = {
            item["entity_id"]
            for item in player.get(_search(f), params={"category": "event", "limit": 100}).json()[
                "items"
            ]
        }
    assert str(f.event_id) in gm_ids and str(f.event_id) in player_ids
    assert str(f.voided_event_id) not in gm_ids and str(f.voided_event_id) not in player_ids
    assert str(f.draft_event_id) in gm_ids
    assert str(f.draft_event_id) not in player_ids
    # An event on another same-world timeline never appears for this campaign.
    assert str(f.other_timeline_event_id) not in gm_ids


# ---------------------------------------------------------------------------
# Targeted campaign.view deny
# ---------------------------------------------------------------------------


def test_a_targeted_deny_hides_an_entity_from_search_and_detail_for_that_member_only(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            entity_id=f.item_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )
    with client_factory(f.player_user_id) as player:
        search_ids = {
            item["entity_id"]
            for item in player.get(_search(f), params={"limit": 100}).json()["items"]
        }
        denied_detail = player.get(f"/campaigns/{f.campaign_id}/world/items/{f.item_id}")
        unrelated_detail = player.get(f"/campaigns/{f.campaign_id}/world/religions/{f.religion_id}")
    assert str(f.item_id) not in search_ids
    assert denied_detail.status_code == 404
    assert unrelated_detail.status_code == 200  # unrelated entity unaffected
    with client_factory(f.gm_user_id) as gm:
        gm_search = gm.get(_search(f), params={"limit": 100}).json()["items"]
        gm_detail = gm.get(f"/campaigns/{f.campaign_id}/world/items/{f.item_id}")
    assert str(f.item_id) in {item["entity_id"] for item in gm_search}
    assert gm_detail.status_code == 200  # the deny does not affect a different member


# ---------------------------------------------------------------------------
# Location detail + breadcrumbs
# ---------------------------------------------------------------------------


def test_location_detail_returns_breadcrumbs_and_state(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        body = client.get(f"/campaigns/{f.campaign_id}/world/locations/{f.settlement_id}").json()
    assert body["location_type_code"] == "settlement"
    assert body["population"] == 4000
    assert [c["location_id"] for c in body["breadcrumbs"]] == [str(f.region_id)]
    assert body["parent_location_id"] == str(f.region_id)


def test_an_inaccessible_parent_is_omitted_from_breadcrumbs(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            entity_id=f.hidden_parent_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )
    with client_factory(f.player_user_id) as client:
        body = client.get(
            f"/campaigns/{f.campaign_id}/world/locations/{f.child_of_hidden_id}"
        ).json()
    assert body["breadcrumbs"] == []
    assert body["parent_location_id"] is None
    # The denied parent itself is a non-disclosing 404.
    with client_factory(f.player_user_id) as client:
        assert (
            client.get(
                f"/campaigns/{f.campaign_id}/world/locations/{f.hidden_parent_id}"
            ).status_code
            == 404
        )


# ---------------------------------------------------------------------------
# Detail: nonexistent vs inaccessible are identical
# ---------------------------------------------------------------------------


def test_nonexistent_and_cross_world_details_return_identical_safe_errors(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    other_world_religion = None
    with postgres_engine.begin() as setup:
        other_world_religion = make_religion(setup, f.other_world_id, name="Alien Creed")
    with client_factory(f.gm_user_id) as client:
        missing = client.get(f"/campaigns/{f.campaign_id}/world/religions/{uuid.uuid4()}")
        cross_world = client.get(
            f"/campaigns/{f.campaign_id}/world/religions/{other_world_religion}"
        )
    assert missing.status_code == cross_world.status_code == 404
    assert missing.json()["error"]["code"] == cross_world.json()["error"]["code"]
    assert missing.json()["error"]["message"] == cross_world.json()["error"]["message"]


# ---------------------------------------------------------------------------
# Event detail
# ---------------------------------------------------------------------------


def test_event_detail_is_timeline_scoped(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        ok = client.get(f"/campaigns/{f.campaign_id}/world/events/{f.event_id}")
        other = client.get(f"/campaigns/{f.campaign_id}/world/events/{f.other_timeline_event_id}")
        voided = client.get(f"/campaigns/{f.campaign_id}/world/events/{f.voided_event_id}")
    assert ok.status_code == 200
    assert other.status_code == 404
    assert voided.status_code == 404


def test_event_detail_draft_visibility_matches_the_list(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as player:
        assert (
            player.get(f"/campaigns/{f.campaign_id}/world/events/{f.draft_event_id}").status_code
            == 404
        )
    with client_factory(f.gm_user_id) as gm:
        assert (
            gm.get(f"/campaigns/{f.campaign_id}/world/events/{f.draft_event_id}").status_code == 200
        )


# ---------------------------------------------------------------------------
# Relationships list
# ---------------------------------------------------------------------------


def test_relationships_list_mirrors_the_existing_detail_contract(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """Owner decision: World Explorer relationship visibility mirrors the
    existing `/relationships/{id}` route — every relationship (and its
    participant ids) is a structural fact visible to any `campaign.view`
    caller. Both the player and the GM see both relationships; the
    player's list agrees with what a direct `/relationships/{id}` fetch
    returns."""
    for user_id in (f.player_user_id, f.gm_user_id):
        with client_factory(user_id) as client:
            items = client.get(
                f"/campaigns/{f.campaign_id}/world/relationships", params={"limit": 100}
            ).json()["items"]
            ids = {item["relationship_id"] for item in items}
            assert {
                str(f.visible_relationship_id),
                str(f.character_relationship_id),
            } <= ids
            # list/detail agreement: each listed relationship is fetchable.
            for item in items:
                detail = client.get(
                    f"/campaigns/{f.campaign_id}/relationships/{item['relationship_id']}"
                )
                assert detail.status_code == 200


def test_relationships_can_be_filtered_by_type_and_related_entity(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        by_type = client.get(
            f"/campaigns/{f.campaign_id}/world/relationships",
            params={"type": "rivalry", "limit": 100},
        ).json()["items"]
        by_entity = client.get(
            f"/campaigns/{f.campaign_id}/world/relationships",
            params={"related_entity_id": str(f.region_id), "limit": 100},
        ).json()["items"]
    assert {item["relationship_id"] for item in by_type} == {str(f.character_relationship_id)}
    assert {item["relationship_id"] for item in by_entity} == {str(f.visible_relationship_id)}


# ---------------------------------------------------------------------------
# Religion detail: related-resource filtering
# ---------------------------------------------------------------------------


def test_religion_detail_omits_a_denied_serving_organization(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        serving_org = make_organization(
            setup,
            f.world_id,
            organization_type_code="religious_organization",
            name="Order of the Ember",
        )
        setup.execute(
            text(
                "INSERT INTO world.religious_organizations "
                "(religious_organization_id, religion_id) VALUES (:o, :r)"
            ),
            {"o": serving_org, "r": f.religion_id},
        )
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            entity_id=serving_org,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )
    with client_factory(f.player_user_id) as player:
        player_body = player.get(
            f"/campaigns/{f.campaign_id}/world/religions/{f.religion_id}"
        ).json()
    with client_factory(f.gm_user_id) as gm:
        gm_body = gm.get(f"/campaigns/{f.campaign_id}/world/religions/{f.religion_id}").json()
    assert str(serving_org) not in player_body["serving_organization_ids"]
    assert str(serving_org) in gm_body["serving_organization_ids"]


# ---------------------------------------------------------------------------
# List/detail agreement
# ---------------------------------------------------------------------------


def test_existing_organization_detail_route_now_honors_a_targeted_deny(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The pre-existing `/campaigns/{id}/organizations/{id}` route was
    hardened in this workstream so its eligibility agrees with the World
    Explorer list."""
    with client_factory(f.player_user_id) as player:
        assert player.get(f"/campaigns/{f.campaign_id}/organizations/{f.org_id}").status_code == 200
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            entity_id=f.org_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )
    with client_factory(f.player_user_id) as player:
        search_ids = {
            item["entity_id"]
            for item in player.get(_search(f), params={"limit": 100}).json()["items"]
        }
        detail = player.get(f"/campaigns/{f.campaign_id}/organizations/{f.org_id}")
    assert str(f.org_id) not in search_ids
    assert detail.status_code == 404
    with client_factory(f.gm_user_id) as gm:
        assert gm.get(f"/campaigns/{f.campaign_id}/organizations/{f.org_id}").status_code == 200


def test_existing_character_detail_route_now_honors_an_entity_targeted_deny(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Regression for the review's High finding #2: an entity-targeted
    `campaign.view` deny removed a character from `/world/search` but
    `/characters/{id}` still returned 200. Summary-tier player."""
    with client_factory(f.player_user_id) as player:
        # Baseline: the summary-tier player can open the character.
        assert player.get(f"/campaigns/{f.campaign_id}/characters/{f.pc_id}").status_code == 200
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            entity_id=f.pc_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )
    with client_factory(f.player_user_id) as player:
        search_ids = {
            item["entity_id"]
            for item in player.get(
                _search(f), params={"category": "character", "limit": 100}
            ).json()["items"]
        }
        detail = player.get(f"/campaigns/{f.campaign_id}/characters/{f.pc_id}")
    assert str(f.pc_id) not in search_ids
    assert detail.status_code == 404


def test_entity_targeted_deny_also_hides_character_full_tier_and_inventory(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The same deny applied to a GM (full tier + `canon.edit`) hides the
    character detail *and* its inventory subresource; an undenied
    character is unaffected."""
    with client_factory(f.gm_user_id) as gm:
        assert gm.get(f"/campaigns/{f.campaign_id}/characters/{f.pc_id}").status_code == 200
        assert (
            gm.get(f"/campaigns/{f.campaign_id}/characters/{f.pc_id}/inventory").status_code == 200
        )
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            entity_id=f.pc_id,
            grantee_campaign_membership_id=f.gm_membership_id,
            effect="deny",
        )
    with client_factory(f.gm_user_id) as gm:
        assert gm.get(f"/campaigns/{f.campaign_id}/characters/{f.pc_id}").status_code == 404
        assert (
            gm.get(f"/campaigns/{f.campaign_id}/characters/{f.pc_id}/inventory").status_code == 404
        )
        # A different character with no deny is still fully readable.
        assert gm.get(f"/campaigns/{f.campaign_id}/characters/{f.npc_id}").status_code == 200


def test_character_detail_deny_is_lifted_when_the_grant_is_revoked(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            entity_id=f.pc_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )
    with client_factory(f.player_user_id) as player:
        assert player.get(f"/campaigns/{f.campaign_id}/characters/{f.pc_id}").status_code == 404
    with postgres_engine.begin() as revoke:
        revoke.execute(
            text(
                "UPDATE security.resource_grants SET revoked_at = now() "
                "WHERE campaign_id = :c AND entity_id = :e"
            ),
            {"c": f.campaign_id, "e": f.pc_id},
        )
    with client_factory(f.player_user_id) as player:
        restored = player.get(f"/campaigns/{f.campaign_id}/characters/{f.pc_id}")
    assert restored.status_code == 200
    assert restored.json()["name"] == "Aldric Vane"


def test_every_entity_in_search_has_a_fetchable_detail_for_that_caller(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    route_for = {
        "location": "locations",
        "religion": "religions",
        "item": "items",
        "event": "events",
    }
    with client_factory(f.player_user_id) as client:
        items = client.get(_search(f), params={"limit": 100}).json()["items"]
        for item in items:
            sub = route_for.get(item["category"])
            if sub is None:
                continue
            detail = client.get(f"/campaigns/{f.campaign_id}/world/{sub}/{item['entity_id']}")
            assert detail.status_code == 200, (item, detail.text)
