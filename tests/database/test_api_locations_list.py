"""Tests for `dnd_ai.api.locations` — Phase 13D World Explorer backend
readiness's `GET /campaigns/{campaign_id}/locations`
(docs/PHASE13D_WORLD_LOCATION_BROWSE.md), the first bounded World Explorer
read slice: an authorized, type-filtered, searchable, keyset-paginated
list of locations and dungeon areas.

Mirrors `tests/database/test_api_dungeon.py`'s shape: `get_authenticated_
user_id` is overridden directly, since these tests exercise campaign-
capability enforcement, party-scoped discovery filtering, resource-grant
overrides, and pagination — not OIDC token verification, already covered
by `tests/database/test_api_auth.py`. `visibility_policy`-style discovery
filtering itself (a hidden structural child requires party discovery) is
already exhaustively covered there for the dungeon-area *detail* route;
this file proves the identical rule generalized to `subject_entity_id` for
the *list* route, plus everything specific to listing: type filtering,
search, keyset pagination (including ties), and parent/breadcrumb
non-disclosure.

Covers: access control (non-member 404, capless-member 403); a legitimate
empty result; type filtering; case-insensitive name/summary search;
deterministic keyset pagination across identically-named locations (UUID
tie-break); an inaccessible (discovery-gated, undiscovered) location
excluded *before* pagination rather than consuming a page slot; a
per-location `campaign.view` resource-grant deny; non-GM discovery-gated
visibility (absent without discovery, present once the caller's authorized
party has discovered it); GM canonical visibility (no discovery needed);
an inaccessible parent's id/name withheld from an otherwise-visible
child's breadcrumb fields; and a malformed cursor mapped to the ordinary
400 `validation_failed` contract.
"""

import base64
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
    make_campaign_party,
    make_character,
    make_character_relationship_type,
    make_dungeon,
    make_dungeon_area,
    make_knowledge_item,
    make_location,
    make_membership_character_relationship,
    make_membership_role,
    make_party,
    make_party_discovery,
    make_party_membership,
    make_relationship_type_capability,
    make_resource_grant,
    make_role,
    make_role_capability,
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
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )

        # Always visible, no discovery gate — dungeon/dungeon_area,
        # exercising the "positive control" breadcrumb (area's parent, the
        # dungeon, is itself visible).
        self.dungeon_id = make_dungeon(connection, self.world_id, name="Shadowfen Dungeon")
        self.area_id = make_dungeon_area(connection, self.dungeon_id, name="Entrance Hall")

        # A settlement with search-relevant summary text.
        self.settlement_id = make_location(
            connection, self.world_id, entity_type_code="settlement", name="Rivertown"
        )
        connection.execute(
            text("UPDATE core.entities SET summary = :s WHERE entity_id = :e"),
            {"s": "A bustling market town.", "e": self.settlement_id},
        )

        # Discovery-gated: a knowledge item names it as subject, no
        # discovery recorded yet by default. Its parent is the (always
        # visible) settlement above.
        self.gated_id = make_location(
            connection,
            self.world_id,
            entity_type_code="building",
            name="Hidden Vault",
            parent_location_id=self.settlement_id,
        )
        self.gated_knowledge_id = make_knowledge_item(
            connection,
            self.world_id,
            statement="The vault is concealed behind a false wall.",
            subject_entity_id=self.gated_id,
        )

        # Itself ungated (always visible), but its own parent (gated_id) is
        # discovery-gated — the negative-control breadcrumb case.
        self.gated_child_id = make_location(
            connection,
            self.world_id,
            entity_type_code="building",
            name="Vault Annex",
            parent_location_id=self.gated_id,
        )

        # Always visible by default; a resource-grant deny targeting it is
        # created ad hoc by the one test that needs it.
        self.denied_id = make_location(
            connection, self.world_id, entity_type_code="region", name="Forbidden Marches"
        )

        # Identically-named pair, isolated by a unique entity_type/name for
        # a clean pagination-tie-break test.
        self.tie_a_id = make_location(
            connection, self.world_id, entity_type_code="district", name="Twin Peak"
        )
        self.tie_b_id = make_location(
            connection, self.world_id, entity_type_code="district", name="Twin Peak"
        )

        # Three same-type locations, alphabetically ordered, the middle one
        # discovery-gated and undiscovered — proves exclusion happens
        # before LIMIT is applied, not after.
        self.zone_a_id = make_location(
            connection, self.world_id, entity_type_code="nation", name="Zone A"
        )
        self.zone_b_id = make_location(
            connection, self.world_id, entity_type_code="nation", name="Zone B"
        )
        make_knowledge_item(
            connection,
            self.world_id,
            statement="Zone B is warded from view.",
            subject_entity_id=self.zone_b_id,
        )
        self.zone_c_id = make_location(
            connection, self.world_id, entity_type_code="nation", name="Zone C"
        )

        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        view_knowledge_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_knowledge"
        )
        self.view_capability_id = view_capability_id
        self.canon_edit_capability_id = canon_edit_id

        self.gm_user_id = make_user(connection, "Location List GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        self.gm_membership_id = gm_membership_id
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, view_capability_id)
        make_role_capability(connection, gm_role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        self.player_user_id = make_user(connection, "Location List Player")
        player_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.player_user_id
        )
        self.player_membership_id = player_membership_id
        player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, player_role_id, view_capability_id)
        make_membership_role(connection, player_membership_id, player_role_id)

        # party_id: the player's authorized perspective (character_id is a
        # current member, and player_user holds character.view_knowledge
        # for it via a real relationship — the same resource-scoped shape
        # resolve_party_perspective() requires). Discovers gated_id only —
        # zone_b_id stays undiscovered by this party, proving filtering is
        # per location, not an all-or-nothing party flag.
        self.party_id = make_party(connection, self.world_id, name="The Company")
        make_campaign_party(connection, self.campaign_id, self.party_id)
        self.character_id = make_character(connection, self.world_id, name="Aria")
        make_party_membership(
            connection, self.timeline_id, self.party_id, self.character_id, self.world_time_id
        )
        self.relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(
            connection, self.relationship_type_id, view_knowledge_capability_id
        )
        make_membership_character_relationship(
            connection,
            player_membership_id,
            self.character_id,
            self.relationship_type_id,
            timeline_id=self.timeline_id,
        )
        make_party_discovery(
            connection, self.timeline_id, self.gated_knowledge_id, party_id=self.party_id
        )

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Location List Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Location List Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"location-list-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        w = fixture.world_id
        cleanup.execute(
            text("""
                DELETE FROM security.membership_character_relationships
                WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id = :c
                )
            """),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id = :c
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
        # security.resource_grants is created ad hoc by the resource-grant
        # regression test below, never by the shared Fixture itself —
        # cleaned up here, scoped by campaign_id, before the
        # campaign_memberships row it references is removed.
        cleanup.execute(
            text("DELETE FROM security.resource_grants WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM security.campaign_memberships WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM knowledge.party_discoveries WHERE knowledge_item_id IN (
                    SELECT knowledge_item_id FROM knowledge.knowledge_items ki
                    JOIN core.entities e ON e.entity_id = ki.knowledge_item_id
                    WHERE e.world_id = :w
                )
            """),
            {"w": w},
        )
        cleanup.execute(
            text("DELETE FROM campaign.party_memberships WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaign_parties WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(text("DELETE FROM campaign.parties WHERE world_id = :w"), {"w": w})
        cleanup.execute(text("DELETE FROM campaign.timelines WHERE world_id = :w"), {"w": w})
        cleanup.execute(text("DELETE FROM core.entities WHERE world_id = :w"), {"w": w})
        cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": w})
        # security.character_relationship_types is a global lookup table,
        # not scoped by world — deleted here by id, after the
        # membership_character_relationships row referencing it above.
        cleanup.execute(
            text(
                "DELETE FROM security.character_relationship_type_capabilities "
                "WHERE character_relationship_type_id = :rt"
            ),
            {"rt": fixture.relationship_type_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.character_relationship_types "
                "WHERE character_relationship_type_id = :rt"
            ),
            {"rt": fixture.relationship_type_id},
        )
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


def _list_url(f: Fixture) -> str:
    return f"/campaigns/{f.campaign_id}/locations"


def _player_perspective_params(f: Fixture) -> dict[str, str]:
    return {"character_id": str(f.character_id), "party_id": str(f.party_id)}


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_list_url(f))
    assert response.status_code == 404


def test_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_list_url(f))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Basic listing and empty result
# ---------------------------------------------------------------------------


def test_a_gm_sees_ungated_locations(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_list_url(f))
    assert response.status_code == 200, response.text
    location_ids = {item["location_id"] for item in response.json()["items"]}
    assert {str(f.dungeon_id), str(f.area_id), str(f.settlement_id)} <= location_ids


def test_a_legitimate_empty_search_returns_an_empty_successful_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_list_url(f), params={"q": "zzz-no-such-location-zzz"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["next_cursor"] is None


# ---------------------------------------------------------------------------
# Type filtering
# ---------------------------------------------------------------------------


def test_type_filtering_returns_only_the_requested_entity_type(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_list_url(f), params={"entity_type": "dungeon_area"})
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert {item["location_id"] for item in items} == {str(f.area_id)}
    assert items[0]["entity_type_code"] == "dungeon_area"


# ---------------------------------------------------------------------------
# Text search
# ---------------------------------------------------------------------------


def test_search_matches_case_insensitively_over_name_and_summary(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        by_name = client.get(_list_url(f), params={"q": "riverTOWN"})
        by_summary = client.get(_list_url(f), params={"q": "BUSTLING"})
    assert by_name.status_code == 200, by_name.text
    assert by_summary.status_code == 200, by_summary.text
    assert {item["location_id"] for item in by_name.json()["items"]} == {str(f.settlement_id)}
    assert {item["location_id"] for item in by_summary.json()["items"]} == {str(f.settlement_id)}


# ---------------------------------------------------------------------------
# Deterministic keyset pagination, including tied names
# ---------------------------------------------------------------------------


def test_pagination_across_tied_names_is_deterministic_with_no_gaps_or_duplicates(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        page_1 = client.get(_list_url(f), params={"q": "Twin Peak", "limit": 1})
        assert page_1.status_code == 200, page_1.text
        page_1_body = page_1.json()
        assert len(page_1_body["items"]) == 1
        assert page_1_body["next_cursor"] is not None

        page_2 = client.get(
            _list_url(f),
            params={"q": "Twin Peak", "limit": 1, "cursor": page_1_body["next_cursor"]},
        )
        assert page_2.status_code == 200, page_2.text
        page_2_body = page_2.json()
        assert len(page_2_body["items"]) == 1
        assert page_2_body["next_cursor"] is None

    first_id = uuid.UUID(page_1_body["items"][0]["location_id"])
    second_id = uuid.UUID(page_2_body["items"][0]["location_id"])
    assert {first_id, second_id} == {f.tie_a_id, f.tie_b_id}
    # Names are identical ("Twin Peak" for both) — the UUID tie-break must
    # place the smaller id first, deterministically.
    assert first_id < second_id


# ---------------------------------------------------------------------------
# Inaccessible records excluded before pagination
# ---------------------------------------------------------------------------


def test_a_discovery_gated_undiscovered_location_does_not_consume_a_page_slot(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """Zone A/B/C are alphabetically ordered; Zone B is discovery-gated and
    undiscovered by f.player_user_id's party. With limit=2, a buggy
    implementation that filtered *after* paging would return only Zone A
    (Zone B consuming the second slot, then dropped) or leak Zone B
    entirely; the correct behavior returns both truly-accessible items and
    reports no further page."""
    with client_factory(f.player_user_id) as client:
        response = client.get(
            _list_url(f),
            params={"entity_type": "nation", "limit": 2, **_player_perspective_params(f)},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["location_id"] for item in body["items"]] == [str(f.zone_a_id), str(f.zone_c_id)]
    assert body["next_cursor"] is None


# ---------------------------------------------------------------------------
# Per-location resource-grant deny
# ---------------------------------------------------------------------------


def test_a_targeted_campaign_view_deny_hides_the_location_for_that_member_only(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            entity_id=f.denied_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )

    with client_factory(f.player_user_id) as client:
        denied_response = client.get(
            _list_url(f), params={"entity_type": "region", **_player_perspective_params(f)}
        )
    with client_factory(f.gm_user_id) as client:
        gm_response = client.get(_list_url(f), params={"entity_type": "region"})

    assert denied_response.status_code == 200, denied_response.text
    assert gm_response.status_code == 200, gm_response.text
    assert denied_response.json()["items"] == []
    assert {item["location_id"] for item in gm_response.json()["items"]} == {str(f.denied_id)}


# ---------------------------------------------------------------------------
# Non-GM discovery/perspective filtering vs. GM canonical visibility
# ---------------------------------------------------------------------------


def test_a_non_gm_without_a_perspective_never_sees_a_gated_location(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """gated_child_id shares the same entity_type but is itself ungated, so
    it still appears — only gated_id (discovery-gated, undiscovered by
    this caller) must be absent."""
    with client_factory(f.player_user_id) as client:
        response = client.get(_list_url(f), params={"entity_type": "building"})
    assert response.status_code == 200, response.text
    location_ids = {item["location_id"] for item in response.json()["items"]}
    assert str(f.gated_id) not in location_ids
    assert str(f.gated_child_id) in location_ids


def test_a_non_gm_with_an_authorized_party_that_discovered_it_sees_the_gated_location(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(
            _list_url(f),
            params={"entity_type": "building", **_player_perspective_params(f)},
        )
    assert response.status_code == 200, response.text
    location_ids = {item["location_id"] for item in response.json()["items"]}
    assert str(f.gated_id) in location_ids


def test_a_gm_sees_the_gated_location_with_no_discovery_at_all(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_list_url(f), params={"entity_type": "building"})
    assert response.status_code == 200, response.text
    location_ids = {item["location_id"] for item in response.json()["items"]}
    assert {str(f.gated_id), str(f.gated_child_id)} <= location_ids


# ---------------------------------------------------------------------------
# Inaccessible parent/breadcrumb non-disclosure
# ---------------------------------------------------------------------------


def test_a_gm_sees_the_visible_parent_in_the_breadcrumb(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_list_url(f), params={"entity_type": "dungeon_area"})
    assert response.status_code == 200, response.text
    item = next(i for i in response.json()["items"] if i["location_id"] == str(f.area_id))
    assert item["parent_location_id"] == str(f.dungeon_id)
    assert item["parent_name"] == "Shadowfen Dungeon"


def test_a_non_gm_never_sees_an_inaccessible_parent_even_for_a_visible_child(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """gated_child_id is itself ungated (always visible), but its parent
    (gated_id) is discovery-gated and undiscovered by this caller — the
    breadcrumb fields must be null, not the parent's real id/name."""
    with client_factory(f.player_user_id) as client:
        response = client.get(_list_url(f), params={"entity_type": "building"})
    assert response.status_code == 200, response.text
    item = next(i for i in response.json()["items"] if i["location_id"] == str(f.gated_child_id))
    assert item["parent_location_id"] is None
    assert item["parent_name"] is None


def test_a_gm_sees_the_same_childs_parent_once_it_is_canonically_authorized(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_list_url(f), params={"entity_type": "building"})
    assert response.status_code == 200, response.text
    item = next(i for i in response.json()["items"] if i["location_id"] == str(f.gated_child_id))
    assert item["parent_location_id"] == str(f.gated_id)
    assert item["parent_name"] == "Hidden Vault"


# ---------------------------------------------------------------------------
# Malformed cursor
# ---------------------------------------------------------------------------


def test_a_malformed_cursor_is_rejected_through_the_normal_error_contract(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_list_url(f), params={"cursor": "not-a-valid-cursor!!"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_cursor_that_is_valid_base64_but_not_the_expected_payload_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    garbage = base64.urlsafe_b64encode(b"not json at all").decode("ascii")
    with client_factory(f.gm_user_id) as client:
        response = client.get(_list_url(f), params={"cursor": garbage})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_failed"
