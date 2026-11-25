"""`GET /campaigns/{campaign_id}/world/locations/{location_id}/children` (P15-C08-S01-T01).

Cases A1-A15 of docs/delivery/p15-c08-s01-location-children-plan.md section 6. Every refusal case also
asserts a positive control in the same test, because a missing route already answers 404 `not_found`:
a refusal-only assertion would pass for the wrong reason.

The fixture is its own: a world, a second world, a campaign with a GM (`campaign.view` and `canon.edit`,
and world authority through ownership), a player (`campaign.view`), a capless member and an outsider, plus
a second campaign on the same world whose GM holds no world authority.
"""

import uuid
from typing import Any

import pytest
from httpx import Response
from sqlalchemy import Connection, text

from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.builders import make_authored_campaign, make_authored_world
from tests.factories import (
    lookup_id,
    make_area_connection,
    make_area_feature,
    make_area_hazard,
    make_area_interactable,
    make_dungeon,
    make_dungeon_area,
    make_location,
    make_resource_grant,
    status_id,
)

pytestmark = pytest.mark.database

ITEM_KEYS = {
    "location_id",
    "name",
    "location_type_code",
    "summary",
    "canon_status",
    "lifecycle_status",
    "path",
}
CRUMB_KEYS = {"location_id", "name", "location_type_code"}


@pytest.fixture
def harness(db_connection: Connection):  # type: ignore[no-untyped-def]
    yield from harness_fixture_factory()(db_connection)


class Setup:
    def __init__(self, harness: AuthoringHarness, connection: Connection) -> None:
        self.connection = connection
        self.gm: Actor = harness.new_actor("GM")
        self.player: Actor = harness.new_actor("Player")
        self.capless: Actor = harness.new_actor("Capless")
        self.outsider: Actor = harness.new_actor("Outsider")
        self.gm2: Actor = harness.new_actor("Other GM")
        other_owner = harness.new_actor("Other Owner")
        self.world = make_authored_world(connection, owner_user_id=self.gm.user_id)
        self.other_world = make_authored_world(
            connection, owner_user_id=other_owner.user_id, name="Other World"
        )
        self.campaign = make_authored_campaign(connection, self.world)
        self.campaign2 = make_authored_campaign(connection, self.world, name="Second Campaign")
        self.player_membership = self._join(self.campaign, self.player, "player")
        self._join(self.campaign, self.capless, None)
        self._join(self.campaign2, self.gm2, "gm")
        self.view_capability = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )

    def _join(self, campaign: uuid.UUID, actor: Actor, role: str | None) -> uuid.UUID:
        membership = self.connection.execute(
            text("""
                INSERT INTO security.campaign_memberships
                    (campaign_id, user_id, membership_status_id, joined_at)
                VALUES (:c, :u, (SELECT membership_status_id FROM security.membership_statuses
                                 WHERE code = 'active'), now())
                RETURNING campaign_membership_id
            """),
            {"c": campaign, "u": actor.user_id},
        ).scalar()
        assert isinstance(membership, uuid.UUID)
        if role is not None:
            self.connection.execute(
                text("""
                    INSERT INTO security.membership_roles (campaign_membership_id, role_id)
                    SELECT :m, r.role_id FROM security.roles r
                    WHERE r.code = :role AND r.campaign_id IS NULL
                """),
                {"m": membership, "role": role},
            )
        return membership

    # --- places ------------------------------------------------------------

    def place(
        self,
        name: str,
        parent: uuid.UUID | None = None,
        *,
        canon: str = "canon",
        lifecycle: str = "active",
        summary: str | None = None,
        other_world: bool = False,
    ) -> uuid.UUID:
        world = self.other_world if other_world else self.world
        place = make_location(
            self.connection,
            world.world_id,
            parent_location_id=parent,
            entity_type_code="region",
            name=name,
        )
        self.mark(place, canon=canon, lifecycle=lifecycle)
        if summary is not None:
            self.connection.execute(
                text("UPDATE core.entities SET summary = :s WHERE entity_id = :e"),
                {"s": summary, "e": place},
            )
        return place

    def mark(self, entity: uuid.UUID, *, canon: str = "canon", lifecycle: str = "active") -> None:
        self.connection.execute(
            text(
                "UPDATE core.entities SET canon_status_id = :c, lifecycle_status_id = :l "
                "WHERE entity_id = :e"
            ),
            {
                "c": status_id(self.connection, "canon_statuses", canon),
                "l": status_id(self.connection, "lifecycle_statuses", lifecycle),
                "e": entity,
            },
        )

    def deny(self, entity: uuid.UUID) -> None:
        make_resource_grant(
            self.connection,
            self.campaign,
            self.view_capability,
            entity_id=entity,
            grantee_campaign_membership_id=self.player_membership,
            effect="deny",
        )

    # --- requests ----------------------------------------------------------

    def children(
        self,
        actor: Actor,
        parent: uuid.UUID | str,
        *,
        campaign: uuid.UUID | None = None,
        **params: Any,
    ) -> Response:
        return actor.get(
            f"/campaigns/{campaign or self.campaign}/world/locations/{parent}/children", **params
        )

    def detail(self, actor: Actor, place: uuid.UUID | str) -> Response:
        return actor.get(f"/campaigns/{self.campaign}/world/locations/{place}")

    def search(self, actor: Actor, **params: Any) -> Response:
        return actor.get(f"/campaigns/{self.campaign}/world/search", **params)

    def listed(
        self, actor: Actor, parent: uuid.UUID, *, campaign: uuid.UUID | None = None, **params: Any
    ) -> list[uuid.UUID]:
        response = self.children(actor, parent, campaign=campaign, **params)
        assert response.status_code == 200, response.text
        return [uuid.UUID(item["location_id"]) for item in response.json()["items"]]

    def pages(self, actor: Actor, parent: uuid.UUID, **params: Any) -> list[list[uuid.UUID]]:
        pages: list[list[uuid.UUID]] = []
        cursor: str | None = None
        for _ in range(50):
            page_params = dict(params)
            if cursor is not None:
                page_params["cursor"] = cursor
            response = self.children(actor, parent, **page_params)
            assert response.status_code == 200, response.text
            body = response.json()
            pages.append([uuid.UUID(item["location_id"]) for item in body["items"]])
            cursor = body["next_cursor"]
            if cursor is None:
                return pages
        raise AssertionError("paging did not end")


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> Setup:
    return Setup(harness, db_connection)


def _strip(value: Any) -> Any:
    """A response body without its per-request `correlation_id`."""
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k != "correlation_id"}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _order(places: dict[str, uuid.UUID], *names: str) -> list[uuid.UUID]:
    return [places[name] for name in names]


# --- A1 ----------------------------------------------------------------------


def test_a1_direct_children_only_in_name_then_id_order(s: Setup) -> None:
    region = s.place("Amber Reach")
    places = {name: s.place(name, region) for name in ("Cinder", "Anvil", "Brass")}
    s.place("Deep Cellar", places["Brass"])  # a grandchild: never a direct child
    expected = _order(places, "Anvil", "Brass", "Cinder")
    assert s.listed(s.gm, region) == expected
    assert s.listed(s.player, region) == expected


# --- A2 ----------------------------------------------------------------------


def test_a2_a_targeted_deny_hides_the_child_from_that_player_only(s: Setup) -> None:
    region = s.place("Amber Reach")
    open_child = s.place("Anvil", region)
    denied = s.place("Brass Secret", region)
    s.deny(denied)
    response = s.children(s.player, region)
    assert response.status_code == 200
    assert s.listed(s.player, region) == [open_child]
    assert str(denied) not in response.text and "Brass Secret" not in response.text
    assert s.listed(s.gm, region) == [open_child, denied]


# --- A3 ----------------------------------------------------------------------


def test_a3_lifecycle_visibility_and_the_read_private_gate(s: Setup) -> None:
    region = s.place("Amber Reach")
    visible = s.place("Anvil", region)
    draft = s.place("Brass Draft", region, canon="draft")
    archived = s.place("Cinder Old", region, lifecycle="archived")
    # (a) a draft is hidden from the player, who still sees the published child
    assert s.listed(s.player, region) == [visible]
    assert s.listed(s.player, region, include_noncanon="true", include_archived="true") == [visible]
    # (b) the GM with read-private sees the draft only when asking for it
    assert s.listed(s.gm, region) == [visible]
    assert s.listed(s.gm, region, include_noncanon="true") == [visible, draft]
    # (c) a GM of another campaign on the same world has no read-private
    assert s.listed(s.gm2, region, campaign=s.campaign2) == [visible]
    assert s.listed(s.gm2, region, campaign=s.campaign2, include_noncanon="true") == [visible]
    # (d) an archived child is hidden by default and shown on request
    assert archived not in s.listed(s.gm, region)
    assert s.listed(s.gm, region, include_archived="true") == [visible, archived]
    assert s.listed(s.gm2, region, campaign=s.campaign2, include_archived="true") == [visible]


# --- A4 ----------------------------------------------------------------------


def test_a4_parent_refusals_match_the_detail_route(s: Setup) -> None:
    region = s.place("Amber Reach")
    child = s.place("Anvil", region)
    foreign = s.place("Far Away", other_world=True)
    forbidden = s.place("Forbidden March")
    s.place("Hidden Tower", forbidden)
    s.deny(forbidden)
    archived = s.place("Old Keep", lifecycle="archived")
    old_child = s.place("Old Gate", archived)
    # positive control: a visible parent answers 200 with its children
    assert s.listed(s.player, region) == [child]
    for refused in (uuid.uuid4(), foreign, forbidden):
        answer = s.children(s.player, refused)
        assert answer.status_code == 404
        assert _strip(answer.json()) == _strip(s.detail(s.player, refused).json())
        assert s.detail(s.player, refused).status_code == 404
    # an archived parent is still referenceable, so its children are listed
    assert s.detail(s.player, archived).status_code == 200
    assert s.listed(s.player, archived) == [old_child]
    # the GM has no deny, and a place of another world is refused even to the world's owner
    assert s.listed(s.gm, forbidden) != []
    assert s.children(s.gm, foreign).status_code == 404


# --- A5 ----------------------------------------------------------------------


def test_a5_hidden_chain_truncation(s: Setup) -> None:
    top = s.place("Top")
    middle = s.place("Middle Hall", top)
    crypt = s.place("Crypt of Echoes", middle)
    inner = s.place("Antechamber", crypt)
    s.deny(middle)
    # positive control: the GM reaches the whole chain
    assert s.listed(s.gm, top) == [middle]
    gm_search = s.children(s.gm, top, q="Crypt")
    assert gm_search.status_code == 200
    (found,) = gm_search.json()["items"]
    assert found["location_id"] == str(crypt)
    assert found["path"] == [
        {"location_id": str(middle), "name": "Middle Hall", "location_type_code": "region"}
    ]
    # the player's search from the top reaches neither the hidden place nor anything below it
    for term in ("Crypt", "Middle", "Antechamber"):
        answer = s.children(s.player, top, q=term)
        assert answer.status_code == 200
        assert answer.json()["items"] == []
        for hidden in (middle, crypt, inner):
            assert str(hidden) not in answer.text
    assert s.listed(s.player, top) == []
    # a hidden place deeper in the tree (below a visible one) truncates the same way
    gate = s.place("Gate", top)
    stair = s.place("Hidden Stair", gate)
    cellar = s.place("Cellar of Echoes", stair)
    s.deny(stair)
    assert s.listed(s.gm, top, q="Cellar") == [cellar]  # positive control
    for term in ("Cellar", "Stair"):
        assert s.listed(s.player, top, q=term) == []
    assert s.listed(s.player, top, q="Gate") == [gate]
    # the player can still open the place below the hidden one directly
    assert s.listed(s.player, crypt) == [inner]
    assert s.listed(s.player, crypt, q="Antechamber") == [inner]
    # the existing breadcrumb truncation is unchanged
    below = s.detail(s.player, crypt).json()
    assert below["breadcrumbs"] == [] and below["parent_location_id"] is None
    assert [c["location_id"] for c in s.detail(s.gm, crypt).json()["breadcrumbs"]] == [
        str(top),
        str(middle),
    ]


# --- A6 ----------------------------------------------------------------------


def test_a6_a_deep_path_lists_every_intermediate_top_to_bottom(s: Setup) -> None:
    chain = [s.place("Level 0")]
    for depth in range(1, 6):
        chain.append(s.place(f"Level {depth}", chain[-1]))
    s.place("Zebra Leaf", chain[-1])
    answer = s.children(s.gm, chain[0], q="Zebra")
    (leaf,) = answer.json()["items"]
    assert [crumb["location_id"] for crumb in leaf["path"]] == [str(c) for c in chain[1:]]
    assert [crumb["name"] for crumb in leaf["path"]] == [f"Level {d}" for d in range(1, 6)]
    # the parent itself is excluded from the path, and a direct child's path is empty
    assert s.children(s.gm, chain[0]).json()["items"][0]["path"] == []


# --- A7 ----------------------------------------------------------------------


def test_a7_deterministic_paging_and_invalid_inputs(s: Setup) -> None:
    region = s.place("Amber Reach")
    # Six equal names, so that the id tie-break decides their order (random ids rarely match insertion order).
    spec = (
        "Echo",
        "Delta",
        "Same",
        "Alpha",
        "Same",
        "Same",
        "Golf",
        "Same",
        "Same",
        "Same",
        "Bravo",
    )
    children = [s.place(name, region) for name in spec]
    names = dict(zip(children, spec, strict=True))
    expected = sorted(children, key=lambda place: (names[place].lower(), str(place)))
    pages = s.pages(s.gm, region, limit=2)
    assert [len(page) for page in pages] == [2, 2, 2, 2, 2, 1]
    assert [place for page in pages for place in page] == expected
    assert s.pages(s.gm, region, limit=2) == pages
    # invalid inputs: 422, each alongside the 200 above
    search_cursor = s.search(s.gm, limit=1).json()["next_cursor"]
    assert search_cursor is not None
    for params in (
        {"cursor": search_cursor},
        {"cursor": "not-a-cursor"},
        {"limit": 0},
        {"limit": 101},
        {"q": "x" * 201},
    ):
        assert s.children(s.gm, region, **params).status_code == 422, params
    assert s.children(s.gm, region, limit=100).status_code == 200
    assert s.children(s.gm, region, q="x" * 200).status_code == 200


# --- A8 ----------------------------------------------------------------------


def test_a8_hidden_rows_are_filtered_before_paging(s: Setup) -> None:
    region = s.place("Amber Reach")
    children = [s.place(f"Child {letter}", region) for letter in "ABCDEFGHIJ"]
    hidden = {children[1], children[4], children[5]}
    for place in hidden:
        s.deny(place)
    visible = [place for place in children if place not in hidden]
    pages = s.pages(s.player, region, limit=2)
    assert [len(page) for page in pages] == [2, 2, 2, 1]
    assert len(pages) == -(-len(visible) // 2)
    assert [place for page in pages for place in page] == visible
    assert not hidden & {place for page in pages for place in page}
    # positive control: the GM pages through all ten
    assert [len(page) for page in s.pages(s.gm, region, limit=4)] == [4, 4, 2]


# --- A9 ----------------------------------------------------------------------


def test_a9_personas_and_authority_loss(s: Setup) -> None:
    region = s.place("Amber Reach")
    children = [s.place(f"Child {letter}", region) for letter in "ABC"]
    assert s.listed(s.player, region) == children  # positive control
    assert s.listed(s.gm, region) == children
    refused = s.children(s.outsider, region)
    assert refused.status_code == 404
    assert _strip(refused.json()) == _strip(
        s.outsider.get(f"/campaigns/{s.campaign}/world/locations/{region}").json()
    )
    capless = s.children(s.capless, region)
    assert capless.status_code == 403
    assert _strip(capless.json()) == _strip(s.detail(s.capless, region).json())
    assert str(children[0]) not in refused.text + capless.text
    # authority lost between pages: the earlier cursor lists nothing
    first = s.children(s.player, region, limit=1)
    assert [i["location_id"] for i in first.json()["items"]] == [str(children[0])]
    cursor = first.json()["next_cursor"]
    assert cursor is not None
    assert s.children(s.player, region, limit=1, cursor=cursor).status_code == 200
    s.connection.execute(
        text(
            "UPDATE security.campaign_memberships SET joined_at = now() - interval '2 seconds', "
            "ended_at = now() - interval '1 second' WHERE campaign_membership_id = :m"
        ),
        {"m": s.player_membership},
    )
    late = s.children(s.player, region, limit=1, cursor=cursor)
    assert late.status_code == 404
    assert "items" not in late.json()
    assert str(children[1]) not in late.text


# --- A10 ---------------------------------------------------------------------


def test_a10_places_of_another_world_are_never_reached(s: Setup) -> None:
    region = s.place("Amber Reach")
    own = s.place("Home Harbor", region)
    foreign_region = s.place("Far Region", other_world=True)
    foreign = s.place("Zanzibar Harbor", foreign_region, other_world=True)
    # positive control: the term shared by both worlds finds only the caller's own place
    shared = s.children(s.gm, region, q="Harbor")
    assert [i["location_id"] for i in shared.json()["items"]] == [str(own)]
    assert s.children(s.gm, foreign_region, q="Zanzibar").status_code == 404
    only_foreign = s.children(s.gm, region, q="Zanzibar")
    assert only_foreign.status_code == 200 and only_foreign.json()["items"] == []
    for body in (shared.text, only_foreign.text):
        assert str(foreign) not in body and str(foreign_region) not in body


# --- A11 ---------------------------------------------------------------------


def test_a11_search_text_is_literal_and_case_insensitive(s: Setup) -> None:
    region = s.place("Amber Reach")
    percent = s.place("Ten 100% Done", region)
    underscore = s.place("Under_score", region)
    plain = s.place("Plain Place", region, summary="Mentions UNDERground rivers")
    assert s.listed(s.gm, region, q="%") == [percent]
    assert s.listed(s.gm, region, q="_") == [underscore]
    assert s.listed(s.gm, region, q="PLAIN") == [plain]
    assert s.listed(s.gm, region, q="underground") == [plain]
    assert s.listed(s.gm, region, q="under") == [plain, underscore]


# --- A12 ---------------------------------------------------------------------


def test_a12_the_response_has_exactly_the_documented_shape(s: Setup) -> None:
    region = s.place("Amber Reach")
    child = s.place("Anvil", region, summary="A forge")
    s.place("Anvil Cellar", child)
    body = s.children(s.gm, region).json()
    assert set(body) == {"items", "next_cursor"}
    assert all(set(item) == ITEM_KEYS for item in body["items"])
    assert body["items"][0]["summary"] == "A forge"
    assert body["items"][0]["canon_status"] == "canon"
    assert body["items"][0]["lifecycle_status"] == "active"
    deep = s.children(s.gm, region, q="Cellar").json()["items"]
    assert [set(crumb) for item in deep for crumb in item["path"]] == [CRUMB_KEYS]
    assert "total" not in body and "count" not in body and "has_children" not in str(body)


# --- A13 ---------------------------------------------------------------------


def test_a13_a_dungeons_children_are_its_areas_under_the_same_rules(s: Setup) -> None:
    dungeon = make_dungeon(s.connection, s.world.world_id, name="The Deep")
    hall = make_dungeon_area(s.connection, dungeon, name="Entry Hall")
    vault = make_dungeon_area(s.connection, dungeon, name="Secret Vault")
    s.mark(vault, canon="draft")
    make_area_connection(s.connection, hall, vault)
    structural = [
        make_area_feature(s.connection, hall),
        make_area_hazard(s.connection, hall),
        make_area_interactable(s.connection, hall),
    ]
    answer = s.children(s.player, dungeon)
    assert answer.status_code == 200
    assert [i["location_id"] for i in answer.json()["items"]] == [str(hall)]
    assert s.listed(s.gm, dungeon) == [hall]
    assert s.listed(s.gm, dungeon, include_noncanon="true") == [hall, vault]
    area = s.children(s.gm, hall)
    assert area.status_code == 200 and area.json()["items"] == []
    for body in (answer.text, area.text, s.children(s.gm, dungeon, q="e").text):
        assert not any(str(item) in body for item in structural)


# --- A14 ---------------------------------------------------------------------


def test_a14_navigation_and_search_agree(s: Setup) -> None:
    top = s.place("Hall Top")
    one = s.place("Hall One", top)
    two = s.place("Hall Two", top)
    s.place("Hall One A", one)
    hidden = s.place("Hall One B", one)
    s.place("Hall Under Hidden", hidden)
    s.place("Hall Two A", two)
    s.place("Hall Draft", two, canon="draft")
    s.deny(hidden)

    def reachable(actor: Actor) -> set[uuid.UUID]:
        seen: set[uuid.UUID] = set()
        frontier = [top]
        while frontier:
            frontier = [
                child
                for place in frontier
                for page in s.pages(actor, place, limit=1)
                for child in page
            ]
            seen.update(frontier)
        return seen

    def searched(actor: Actor) -> set[uuid.UUID]:
        return {place for page in s.pages(actor, top, q="Hall", limit=2) for place in page}

    for actor in (s.player, s.gm):
        assert searched(actor) == reachable(actor)
    assert len(searched(s.player)) == 4  # One, Two, One A, Two A
    assert searched(s.player) < searched(s.gm)
    assert hidden not in searched(s.player) and hidden in searched(s.gm)


# --- A15 ---------------------------------------------------------------------


def test_a15_a_place_moved_between_pages_is_omitted_and_nothing_repeats(s: Setup) -> None:
    region = s.place("Amber Reach")
    elsewhere = s.place("Elsewhere")
    children = [s.place(f"Child {letter}", region) for letter in "ABCDE"]
    first = s.children(s.gm, region, limit=2)
    page_one = [uuid.UUID(i["location_id"]) for i in first.json()["items"]]
    assert page_one == children[:2]
    s.connection.execute(
        text("UPDATE world.locations SET parent_location_id = :p WHERE location_id = :l"),
        {"p": elsewhere, "l": children[3]},
    )
    second = s.children(s.gm, region, limit=2, cursor=first.json()["next_cursor"])
    page_two = [uuid.UUID(i["location_id"]) for i in second.json()["items"]]
    assert page_two == [children[2], children[4]]
    assert second.json()["next_cursor"] is None
    assert not set(page_one) & set(page_two)
    assert s.listed(s.gm, elsewhere) == [children[3]]
