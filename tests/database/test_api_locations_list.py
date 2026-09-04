"""Tests for `dnd_ai.api.locations` — Phase 13D World Explorer backend
readiness's `GET /campaigns/{campaign_id}/locations`
(docs/PHASE13D_WORLD_LOCATION_BROWSE.md), the first bounded World Explorer
read slice: an authorized, type-filtered, searchable, keyset-paginated
list of locations and dungeon areas.

Mirrors `tests/database/test_api_dungeon.py`'s shape: `get_authenticated_
user_id` is overridden directly, since these tests exercise campaign-
capability enforcement, per-location resource-grant overrides, and
pagination — not OIDC token verification, already covered by
`tests/database/test_api_auth.py`.

Covers: access control (non-member 404, capless-member 403); a legitimate
empty result; type filtering; case-insensitive name/summary search;
deterministic keyset pagination across identically-named locations (UUID
tie-break); a per-location `campaign.view` resource-grant deny excluded
*before* pagination rather than consuming a page slot; the identical deny
withholding an inaccessible parent's id/name from an otherwise-visible
child's breadcrumb fields; a malformed cursor mapped to the ordinary 400
`validation_failed` contract; and the corrected visibility rule's own
regression coverage — an ordinary location with undiscovered lore
attached is not hidden, and a location's visibility is unaffected by an
unrelated party's discovery of some other claim (`dnd_ai.queries.location`'s
own docstring has the full account of the unsound inference this replaces).
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
    make_dungeon,
    make_dungeon_area,
    make_knowledge_item,
    make_location,
    make_membership_role,
    make_party,
    make_party_discovery,
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

        # Always visible — dungeon/dungeon_area, exercising the "positive
        # control" breadcrumb (area's parent, the dungeon, is itself
        # visible).
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

        # An ordinary, otherwise-visible location with an *undiscovered*
        # knowledge item naming it as subject — regression coverage for the
        # corrected rule: mere lore about a location must never hide it.
        self.lore_location_id = make_location(
            connection, self.world_id, entity_type_code="building", name="Public Archive"
        )
        self.lore_knowledge_id = make_knowledge_item(
            connection,
            self.world_id,
            statement="The archive keeps records dating back three centuries.",
            subject_entity_id=self.lore_location_id,
        )

        # A second, otherwise-visible location whose one associated claim
        # *has* been discovered — by a party wholly unrelated to any user
        # in this fixture. Regression coverage: a location must not be
        # treated any differently (more or less visible) because someone,
        # somewhere, discovered an unrelated claim naming it — visibility
        # here no longer depends on knowledge/discovery state at all.
        self.sibling_location_id = make_location(
            connection, self.world_id, entity_type_code="building", name="Old Chapel"
        )
        self.sibling_knowledge_id = make_knowledge_item(
            connection,
            self.world_id,
            statement="A minor rumor about the old chapel's bell.",
            subject_entity_id=self.sibling_location_id,
        )
        self.discovery_party_id = make_party(connection, self.world_id, name="Passerby Party")
        make_party_discovery(
            connection,
            self.timeline_id,
            self.sibling_knowledge_id,
            party_id=self.discovery_party_id,
        )

        # Always visible by default; a resource-grant deny targeting it is
        # created ad hoc by the one test that needs it.
        self.denied_id = make_location(
            connection, self.world_id, entity_type_code="region", name="Forbidden Marches"
        )

        # A parent whose own resource-grant deny is created ad hoc; its
        # child is never itself denied — proves the deny blanks the
        # breadcrumb without affecting the child's own presence.
        self.denied_parent_id = make_location(
            connection, self.world_id, entity_type_code="settlement", name="Hidden Settlement"
        )
        self.denied_parent_child_id = make_location(
            connection,
            self.world_id,
            entity_type_code="building",
            name="Watchtower",
            parent_location_id=self.denied_parent_id,
        )

        # Identically-named pair, isolated by a unique entity_type/name for
        # a clean pagination-tie-break test.
        self.tie_a_id = make_location(
            connection, self.world_id, entity_type_code="district", name="Twin Peak"
        )
        self.tie_b_id = make_location(
            connection, self.world_id, entity_type_code="district", name="Twin Peak"
        )

        # Three same-type locations, alphabetically ordered; the middle one
        # is denied ad hoc by the pre-pagination-exclusion test — proves
        # exclusion happens before LIMIT is applied, not after.
        self.zone_a_id = make_location(
            connection, self.world_id, entity_type_code="nation", name="Zone A"
        )
        self.zone_b_id = make_location(
            connection, self.world_id, entity_type_code="nation", name="Zone B"
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
        self.view_capability_id = view_capability_id
        self.canon_edit_capability_id = canon_edit_id

        # Holds canon.edit in addition to campaign.view — used to prove
        # that capability confers no special location visibility any more
        # (the corrected rule has no GM/canonical-truth escape hatch left).
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
        # regression tests below, never by the shared Fixture itself —
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
            text("DELETE FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(text("DELETE FROM campaign.parties WHERE world_id = :w"), {"w": w})
        cleanup.execute(text("DELETE FROM campaign.timelines WHERE world_id = :w"), {"w": w})
        cleanup.execute(text("DELETE FROM core.entities WHERE world_id = :w"), {"w": w})
        cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": w})
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


def test_a_member_sees_ordinary_locations(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
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
# A canon.edit holder gets no special visibility (the corrected rule has no
# GM/canonical-truth escape hatch left — see dnd_ai.queries.location's own
# docstring)
# ---------------------------------------------------------------------------


def test_a_canon_edit_holder_and_a_plain_campaign_view_member_see_the_same_locations(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        gm_response = client.get(_list_url(f), params={"entity_type": "building"})
    with client_factory(f.player_user_id) as client:
        player_response = client.get(_list_url(f), params={"entity_type": "building"})
    assert gm_response.status_code == 200, gm_response.text
    assert player_response.status_code == 200, player_response.text
    gm_ids = {item["location_id"] for item in gm_response.json()["items"]}
    player_ids = {item["location_id"] for item in player_response.json()["items"]}
    assert gm_ids == player_ids
    assert {str(f.lore_location_id), str(f.sibling_location_id)} <= gm_ids


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


def test_a_denied_location_does_not_consume_a_page_slot(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Zone A/B/C are alphabetically ordered; Zone B is denied for the
    player's own membership only. With limit=2, a buggy implementation
    that filtered *after* paging would return only Zone A (Zone B
    consuming the second slot, then dropped) or leak Zone B entirely; the
    correct behavior returns both truly-accessible items and reports no
    further page."""
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            entity_id=f.zone_b_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )

    with client_factory(f.player_user_id) as client:
        response = client.get(_list_url(f), params={"entity_type": "nation", "limit": 2})
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
        denied_response = client.get(_list_url(f), params={"entity_type": "region"})
    with client_factory(f.gm_user_id) as client:
        gm_response = client.get(_list_url(f), params={"entity_type": "region"})

    assert denied_response.status_code == 200, denied_response.text
    assert gm_response.status_code == 200, gm_response.text
    assert denied_response.json()["items"] == []
    assert {item["location_id"] for item in gm_response.json()["items"]} == {str(f.denied_id)}


# ---------------------------------------------------------------------------
# Corrected visibility rule: knowledge/discovery state never gates a
# location (see dnd_ai.queries.location's own docstring for the removed,
# unsound inference this replaces)
# ---------------------------------------------------------------------------


def test_undiscovered_lore_about_a_visible_location_does_not_hide_it(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_list_url(f), params={"entity_type": "building"})
    assert response.status_code == 200, response.text
    location_ids = {item["location_id"] for item in response.json()["items"]}
    assert str(f.lore_location_id) in location_ids


def test_a_locations_visibility_is_unaffected_by_an_unrelated_partys_discovery(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """sibling_location_id's one associated claim has been discovered by a
    party with no relationship whatsoever to the requesting user; it must
    appear exactly like lore_location_id (whose claim is undiscovered) —
    neither location's presence depends on knowledge/discovery state at
    all any more."""
    with client_factory(f.player_user_id) as client:
        response = client.get(_list_url(f), params={"entity_type": "building"})
    assert response.status_code == 200, response.text
    location_ids = {item["location_id"] for item in response.json()["items"]}
    assert {str(f.lore_location_id), str(f.sibling_location_id)} <= location_ids


# ---------------------------------------------------------------------------
# Inaccessible parent/breadcrumb non-disclosure
# ---------------------------------------------------------------------------


def test_a_member_sees_the_visible_parent_in_the_breadcrumb(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_list_url(f), params={"entity_type": "dungeon_area"})
    assert response.status_code == 200, response.text
    item = next(i for i in response.json()["items"] if i["location_id"] == str(f.area_id))
    assert item["parent_location_id"] == str(f.dungeon_id)
    assert item["parent_name"] == "Shadowfen Dungeon"


def test_a_denied_parent_is_withheld_from_the_breadcrumb_for_that_member_only(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.view_capability_id,
            entity_id=f.denied_parent_id,
            grantee_campaign_membership_id=f.player_membership_id,
            effect="deny",
        )

    with client_factory(f.player_user_id) as client:
        denied_response = client.get(_list_url(f), params={"entity_type": "building"})
    with client_factory(f.gm_user_id) as client:
        gm_response = client.get(_list_url(f), params={"entity_type": "building"})

    assert denied_response.status_code == 200, denied_response.text
    assert gm_response.status_code == 200, gm_response.text

    denied_item = next(
        i
        for i in denied_response.json()["items"]
        if i["location_id"] == str(f.denied_parent_child_id)
    )
    assert denied_item["parent_location_id"] is None
    assert denied_item["parent_name"] is None

    gm_item = next(
        i for i in gm_response.json()["items"] if i["location_id"] == str(f.denied_parent_child_id)
    )
    assert gm_item["parent_location_id"] == str(f.denied_parent_id)
    assert gm_item["parent_name"] == "Hidden Settlement"


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
