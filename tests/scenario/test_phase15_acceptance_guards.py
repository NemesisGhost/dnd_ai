"""Phase 15 final-acceptance guards (checkpoint 15.4), beside the exit scenario.

The exit scenario (`test_phase15_completion_flow.py`) shows a GM doing the work. These guards
show what everyone else cannot do, over the whole route table rather than a hand-picked list:
players, outsiders and paired Foundry principals are refused every Phase 15 GM route; a second
world's ids are not found; a hidden record looks like a missing one; a branch does not see later
events of its parent; a stale write is recovered by rereading; a retried create and a retried
state command each have one effect.
"""

import re
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.domain.access import FOUNDRY_ACCESS_AUTH_METHOD, AuthenticatedPrincipal
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times, _advance, _branch_campaign
from tests.database.test_api_routes_travel import clock_at

pytestmark = pytest.mark.scenario

# The Phase 15 GM route families: every route under these prefixes is a GM-only route.
GM_ROUTE_PATTERNS = [
    r"^/campaigns/\{campaign_id\}/authoring/",
    r"^/campaigns/\{campaign_id\}/items/\{[a-z_]+\}/(award|equip|unequip|consume|damage|repair|destroy|attune|end-attunement|transfer|identify)$",
    r"^/campaigns/\{campaign_id\}/encounters(/.*)?$",
    r"^/campaigns/\{campaign_id\}/sources$",
    r"^/campaigns/\{campaign_id\}/entities/\{[a-z_]+\}/(sources/(attach|detach)|provenance|revisions(/compare)?)$",
    r"^/campaigns/\{campaign_id\}/review-queue$",
    r"^/campaigns/\{campaign_id\}/travel$",
    r"^/campaigns/\{campaign_id\}/parties/\{[a-z_]+\}/inventory$",
]
GM_ROUTES = [re.compile(p) for p in GM_ROUTE_PATTERNS]


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def gm_routes(s: ContentSetup) -> list[tuple[str, str]]:
    """`(METHOD, concrete path)` for every Phase 15 GM route, ids filled with fresh UUIDs.

    The route table is read from the app's OpenAPI document, which lists every included router
    (the app's own `routes` holds lazily included routers that cannot be walked)."""
    found: list[tuple[str, str]] = []
    for template, operations in s.harness.app.openapi()["paths"].items():
        if not any(p.match(template) for p in GM_ROUTES):
            continue
        for method in sorted(m.upper() for m in operations if m in ("get", "post")):
            if method == "GET" and re.search(r"/encounters/\{[a-z_]+\}$", template):
                continue  # the encounter record read is `campaign.view`, open to every member
            path = template.replace("{campaign_id}", s.cid)
            path = re.sub(r"\{[a-z_]+\}", lambda _: str(uuid.uuid4()), path)
            found.append((method, path))
    return found


def test_there_are_many_gm_routes_to_guard(s: ContentSetup) -> None:
    routes = gm_routes(s)
    assert len(routes) >= 120, len(routes)
    methods = {m for m, _ in routes}
    assert methods == {"GET", "POST"}


def guarded_routes(s: ContentSetup) -> list[tuple[str, str]]:
    routes = gm_routes(s)
    assert len(routes) >= 120, "the route table was not read; a guard over it would pass vacuously"
    return routes


def test_players_are_refused_every_phase15_gm_route(s: ContentSetup) -> None:
    refused: list[tuple[str, str, int]] = []
    for method, path in guarded_routes(s):
        if method == "GET":
            response = s.player.get(path)
        else:
            response = s.player.post_raw(path, {}, key=s.player.fresh_key())
        if response.status_code != 403:
            refused.append((method, path, response.status_code))
    assert refused == []


def test_outsiders_find_no_phase15_gm_route_of_this_campaign(s: ContentSetup) -> None:
    leaked: list[tuple[str, str, int]] = []
    for method, path in guarded_routes(s):
        if method == "GET":
            response = s.stranger.get(path)
        else:
            response = s.stranger.post_raw(path, {}, key=s.stranger.fresh_key())
        if response.status_code != 404:
            leaked.append((method, path, response.status_code))
    assert leaked == []


def test_a_paired_foundry_principal_is_refused_every_phase15_gm_route(s: ContentSetup) -> None:
    foundry = AuthenticatedPrincipal(
        user_id=s.gm.user_id,
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=uuid.uuid4(),
        foundry_world_id=uuid.uuid4(),
        campaign_id=uuid.UUID(s.cid),
        foundry_connection_id=uuid.uuid4(),
        foundry_device_id=uuid.uuid4(),
        foundry_scopes=frozenset({"encounter_read", "character_read"}),
    )
    client = s.harness.principal_client(foundry)
    allowed: list[tuple[str, str, int]] = []
    for method, path in guarded_routes(s):
        response = client.get(path) if method == "GET" else client.post(path, json={})
        # A Foundry device never gets through; the paired routes it may use are not in this list.
        if response.status_code not in (401, 403, 404):
            allowed.append((method, path, response.status_code))
    assert allowed == []


def test_a_second_worlds_ids_are_not_found_from_this_campaign(s: ContentSetup) -> None:
    clock_at(s, 5)  # item routes read the campaign time before they look at the item
    foreign_place = s.stranger.post_raw(
        s.url("locations", s.other_cid),
        {"category": "settlement", "name": "Elsewhere"},
        key=s.stranger.fresh_key(),
    ).json()["location_id"]
    foreign_npc_species = s.stranger.get(s.url("npcs/options", s.other_cid)).json()["species"][0]
    foreign_npc = s.stranger.post_raw(
        s.url("npcs", s.other_cid),
        {
            "name": "Stranger",
            "species_id": foreign_npc_species["species_id"],
            "size_category": "medium",
        },
        key=s.stranger.fresh_key(),
    ).json()["npc_id"]
    definitions = s.stranger.get(s.url("item-definitions", s.other_cid)).json()["items"]
    foreign_item = s.stranger.post_raw(
        s.url("items", s.other_cid),
        {
            "name": "Elsewhere Sword",
            "item_definition_id": next(
                d["item_definition_id"] for d in definitions if d["code"] == "longsword"
            ),
        },
        key=s.stranger.fresh_key(),
    ).json()["item_instance_id"]
    reads = [
        s.url(f"locations/{foreign_place}"),
        s.url(f"npcs/{foreign_npc}"),
        s.url(f"npcs/{foreign_npc}/portrayal"),
        s.url(f"items/{foreign_item}"),
        f"/campaigns/{s.cid}/entities/{foreign_place}/provenance",
        f"/campaigns/{s.cid}/entities/{foreign_place}/revisions",
        f"/campaigns/{s.cid}/entities/{foreign_place}/revisions/compare?from=1&to=1",
    ]
    for path in reads:
        assert s.gm.get(path).status_code == 404, path
    writes = [
        (
            s.url(f"locations/{foreign_place}/update"),
            {"expected_row_version": 1, "name": "Mine"},
        ),
        (f"/campaigns/{s.cid}/items/{foreign_item}/equip", {"expected_last_event_id": None}),
        (
            f"/campaigns/{s.cid}/entities/{foreign_place}/sources/attach",
            {"source_id": str(uuid.uuid4())},
        ),
        (s.lifecycle(foreign_place, "/submit-for-review"), {"expected_row_version": 1}),
    ]
    for path, body in writes:
        assert s.gm.post_raw(path, body, key=s.gm.fresh_key()).status_code == 404, path
    queue = s.gm.get(f"/campaigns/{s.cid}/review-queue").json()
    assert all(
        i["entity_id"] not in {foreign_place, foreign_npc, foreign_item} for i in queue["items"]
    )


def test_a_hidden_record_looks_the_same_as_a_missing_one_to_a_player(s: ContentSetup) -> None:
    draft = s.gm.post_raw(
        s.url("locations"), {"category": "settlement", "name": "Hidden"}, key=s.gm.fresh_key()
    ).json()["location_id"]
    missing = str(uuid.uuid4())

    def body(response):  # type: ignore[no-untyped-def]
        content = response.json()
        content.get("error", {}).pop("correlation_id", None)
        return response.status_code, content

    for template in (
        "/campaigns/{cid}/world/locations/{id}",
        "/campaigns/{cid}/world/items/{id}",
        "/campaigns/{cid}/characters/{id}",
    ):
        hidden = s.player.get(template.format(cid=s.cid, id=draft))
        absent = s.player.get(template.format(cid=s.cid, id=missing))
        assert body(hidden) == body(absent), template
        assert hidden.status_code == 404


def test_a_branch_does_not_see_events_recorded_later_on_its_parent(s: ContentSetup) -> None:
    times = Times(s)
    t1, t2, t3 = times.at(1), times.at(2), times.at(3)
    assert _advance(s, t1, 0).status_code == 200  # a branch point needs an advance event at it
    branch_cid = _branch_campaign(s, t1)
    assert _advance(s, t3, 1).status_code == 200  # the parent moves on after the branch point
    recorded = s.gm.post_raw(
        f"/campaigns/{s.cid}/events",
        {"world_time_id": t2, "event_type_code": "other", "name": "After the branch point"},
        key=s.gm.fresh_key(),
    )
    assert recorded.status_code == 201, recorded.text
    event_id = recorded.json()["event_id"]
    on_parent = s.gm.get(f"/campaigns/{s.cid}/world/events/{event_id}")
    on_branch = s.gm.get(f"/campaigns/{branch_cid}/world/events/{event_id}")
    assert on_parent.status_code == 200
    assert on_branch.status_code == 404
    effective = s.connection.execute(
        text("""
            SELECT count(*) FROM campaign.effective_events(
                (SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c)
            ) WHERE event_id = :e
        """),
        {"c": branch_cid, "e": event_id},
    ).scalar()
    assert effective == 0


def test_a_stale_write_is_recovered_by_rereading_and_retrying(s: ContentSetup) -> None:
    created = s.gm.post(
        s.url("locations"), {"category": "settlement", "name": "Original"}, key=s.gm.fresh_key()
    ).json()
    version = created["row_version"]
    first = s.gm.post(
        s.url(f"locations/{created['location_id']}/update"),
        {"expected_row_version": version, "name": "First edit"},
        key=s.gm.fresh_key(),
    )
    assert first.status_code == 200
    stale = s.gm.post_raw(
        s.url(f"locations/{created['location_id']}/update"),
        {"expected_row_version": version, "name": "Second edit"},
        key=s.gm.fresh_key(),
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"
    fresh = s.gm.get(s.url(f"locations/{created['location_id']}")).json()
    assert fresh["name"] == "First edit"
    retry = s.gm.post(
        s.url(f"locations/{created['location_id']}/update"),
        {
            "expected_row_version": fresh["row_version"],
            "name": "Second edit",
        },
        key=s.gm.fresh_key(),
    )
    assert retry.status_code == 200 and retry.json()["name"] == "Second edit"


def test_a_retried_create_and_a_retried_state_command_each_have_one_effect(s: ContentSetup) -> None:
    key = s.gm.fresh_key()
    body = {"category": "settlement", "name": "Retried Town"}
    first = s.gm.post_raw(s.url("locations"), body, key=key)
    again = s.gm.post_raw(s.url("locations"), body, key=key)
    assert first.status_code == again.status_code == 201
    assert again.json()["location_id"] == first.json()["location_id"]
    assert s.count("core.entities WHERE canonical_name = 'Retried Town'") == 1

    town = first.json()["location_id"]
    version = s.gm.get(s.url(f"locations/{town}")).json()["row_version"]
    for action in ("submit-for-review", "approve", "publish"):
        version = s.transition(town, action, version)["row_version"]
    pc = s.gm.get(s.url("player-characters/options")).json()["species"][0]["species_id"]
    created = s.gm.post_raw(
        s.url("player-characters"),
        {"name": "Retry Hero", "species_id": pc, "size_category": "medium"},
        key=s.gm.fresh_key(),
    ).json()
    s.publish(created["player_character_id"], created["row_version"])
    Times(s)  # the clock is needed for travel
    t = Times(s).at(7)
    assert _advance(s, t, 0).status_code == 200
    travel_key = s.gm.fresh_key()
    travel_body = {
        "destination_location_id": town,
        "character_ids": [created["player_character_id"]],
    }
    one = s.gm.post_raw(f"/campaigns/{s.cid}/travel", travel_body, key=travel_key)
    two = s.gm.post_raw(f"/campaigns/{s.cid}/travel", travel_body, key=travel_key)
    assert one.status_code == two.status_code == 200, one.text
    assert (
        s.count(
            "narrative.events ev JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id "
            "WHERE et.code = 'characters_traveled'"
        )
        == 1
    )
