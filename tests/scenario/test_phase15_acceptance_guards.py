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
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

from dnd_ai.domain.access import (
    FOUNDRY_ACCESS_AUTH_METHOD,
    AuthenticatedPrincipal,
)
from tests.authoring_support import ORIGIN, AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times, _advance, _branch_campaign
from tests.database.test_api_routes_travel import clock_at
from tests.scenario.phase15_route_manifest import CAMPAIGN, FOUNDRY_PERMITTED, Entry, classify

pytestmark = pytest.mark.scenario

# Pinned on purpose: adding or removing a route changes these and forces a conscious update.
EXPECTED_GUARDED = 232  # 190 Phase 15 + 40 earlier-phase GM routes + 2 world-scoped
EXPECTED_PHASE15_GM = 190
EXPECTED_MEMBER_READS = 25


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def manifest(s: ContentSetup) -> list[Entry]:
    """Every operation of the application, classified (see `phase15_route_manifest`)."""
    entries, unclassified = classify(s.harness.app.openapi()["paths"])
    assert unclassified == [], f"unclassified routes: {unclassified}"
    return entries


def concrete(s: ContentSetup, entry: Entry, campaign_id: str | None = None) -> str:
    path = entry.template.replace("{campaign_id}", campaign_id or s.cid)
    path = path.replace("{world_id}", str(s.world_id))
    return re.sub(r"\{[a-z_]+\}", lambda _: str(uuid.uuid4()), path)


def guarded(s: ContentSetup) -> list[Entry]:
    """Routes that need authority a plain member does not hold: GM-only campaign routes and the
    world-scoped authoring routes."""
    routes = [e for e in manifest(s) if e.klass in ("gm", "world")]
    assert len(routes) >= EXPECTED_GUARDED, "the route table was not read; a guard would be vacuous"
    return routes


def call(client, entry: Entry, path: str):  # type: ignore[no-untyped-def]
    if entry.method == "GET":
        return client.get(path)
    if entry.method == "DELETE":
        if hasattr(client, "post_raw"):
            return client.client.delete(path, headers=client.headers(key=None))
        return client.delete(path, headers={"Origin": ORIGIN})
    if hasattr(client, "post_raw"):
        return client.post_raw(path, {}, key=client.fresh_key())
    return client.post(path, json={}, headers={"Origin": ORIGIN})


def test_every_route_is_classified(s: ContentSetup) -> None:
    entries = manifest(s)
    assert len({(e.method, e.template) for e in entries}) == len(entries)
    assert {e.klass for e in entries} == {"gm", "member_read", "world", "out_of_scope"}
    # Aliases: no two templates differ only by their id placeholder names.
    shapes = [(e.method, re.sub(r"\{[a-z_]+\}", "{}", e.template)) for e in entries]
    assert len(set(shapes)) == len(shapes)


def test_the_manifest_covers_every_phase15_family_and_its_size_is_pinned(s: ContentSetup) -> None:
    entries = manifest(s)
    gm = [e for e in entries if e.klass == "gm"]
    assert len(guarded(s)) == EXPECTED_GUARDED
    assert sum(1 for e in gm if e.phase15) == EXPECTED_PHASE15_GM
    assert sum(1 for e in entries if e.klass == "member_read") == EXPECTED_MEMBER_READS
    families = {e.family.split(" (")[0] for e in gm if e.phase15}
    for required in (
        "authoring",
        "campaign clock",
        "world-time points",
        "calendars",
        "parties, party membership, party inventory",
        "session definition, participation, start, end, log",
        "events and corrections",
        "quest runtime and progress",
        "knowledge runtime and audience",
        "dungeon state",
        "organization state",
        "relationship kernel",
        "item instances, custody, operations",
        "encounter preparation and operation",
        "sources",
        "lifecycle, publication, provenance, revisions",
        "review queue",
        "routes and travel",
        "character-relationship administration",
        "audit history",
    ):
        assert required in families, required
    # The authoring family spans many sub-families; each must have routes in the table.
    authoring = [e.template for e in gm if e.template.startswith(f"{CAMPAIGN}/authoring/")]
    for part in (
        "player-characters",
        "npcs",
        "builds",
        "dungeons",
        "relationships",
        "routes",
        "item-definitions",
        "items",
        "encounters",
        "locations",
        "organizations",
        "religions",
        "quests",
        "knowledge",
        "portrayal",
    ):
        assert any(part in t for t in authoring), part


def test_players_are_refused_every_gm_route(s: ContentSetup) -> None:
    wrong: list[tuple[str, str, int]] = []
    for entry in guarded(s):
        response = call(s.player, entry, concrete(s, entry))
        if response.status_code != entry.insufficient_authority:
            wrong.append((entry.method, entry.template, response.status_code))
    assert wrong == []


def test_player_safe_reads_are_not_refused_to_a_player_and_not_found_by_an_outsider(
    s: ContentSetup,
) -> None:
    reads = [e for e in manifest(s) if e.klass == "member_read"]
    assert len(reads) == EXPECTED_MEMBER_READS
    wrong: list[tuple[str, int, int]] = []
    for entry in reads:
        path = concrete(s, entry)
        member = s.player.get(path).status_code
        outsider = s.stranger.get(path).status_code
        if member not in (200, 404) or outsider != 404:
            wrong.append((entry.template, member, outsider))
    assert wrong == []


def test_unauthenticated_callers_are_rejected_on_every_gm_route(s: ContentSetup) -> None:
    wrong: list[tuple[str, str, int]] = []
    with TestClient(s.harness.app, raise_server_exceptions=False) as anonymous:
        for entry in guarded(s):
            response = call(anonymous, entry, concrete(s, entry))
            if response.status_code != 401:
                wrong.append((entry.method, entry.template, response.status_code))
    assert wrong == []


def _normal(response):  # type: ignore[no-untyped-def]
    content = response.json()
    if isinstance(content.get("error"), dict):
        content["error"].pop("correlation_id", None)
    return response.status_code, content


def test_outsiders_find_no_gm_route_and_the_refusal_is_the_same_as_for_a_missing_campaign(
    s: ContentSetup,
) -> None:
    leaked: list[tuple[str, str, int]] = []
    different: list[str] = []
    for entry in guarded(s):
        response = call(s.stranger, entry, concrete(s, entry))
        if response.status_code != 404:
            leaked.append((entry.method, entry.template, response.status_code))
            continue
        if entry.klass == "gm":
            missing = call(s.stranger, entry, concrete(s, entry, campaign_id=str(uuid.uuid4())))
            if _normal(response) != _normal(missing):
                different.append(entry.template)
    assert leaked == []
    assert different == []


def _principal(s: ContentSetup, method: str) -> AuthenticatedPrincipal:
    device = method == FOUNDRY_ACCESS_AUTH_METHOD
    return AuthenticatedPrincipal(
        user_id=s.gm.user_id,
        auth_method=method,
        foundry_external_system_id=uuid.uuid4(),
        foundry_world_id=uuid.uuid4(),
        campaign_id=uuid.UUID(s.cid) if device else None,
        foundry_connection_id=uuid.uuid4() if device else None,
        foundry_device_id=uuid.uuid4() if device else None,
        foundry_scopes=frozenset({"encounter_read", "character_read"}) if device else None,
    )


def test_foundry_devices_cannot_invoke_human_gm_authoring(s: ContentSetup) -> None:
    client = s.harness.principal_client(_principal(s, FOUNDRY_ACCESS_AUTH_METHOD))
    allowed: list[tuple[str, str, int]] = []
    for entry in guarded(s):
        if (entry.method, entry.template) in FOUNDRY_PERMITTED:
            continue
        response = call(client, entry, concrete(s, entry))
        if response.status_code not in (401, 403, 404):
            allowed.append((entry.method, entry.template, response.status_code))
    assert allowed == []


def test_machine_credentials_cannot_invoke_human_gm_authoring(s: ContentSetup) -> None:
    # The two machine credential shapes the platform has known: the retired shared-secret
    # `FoundrySystem` key (revoked and rejected before any route runs) and a Foundry device
    # access token that was never issued. Neither reaches a GM route.
    wrong: list[tuple[str, str, str, int]] = []
    with TestClient(s.harness.app, raise_server_exceptions=False) as machine:
        for scheme in ("FoundrySystem", "FoundryAccess"):
            headers = {"Authorization": f"{scheme} not-a-real-credential", "Origin": ORIGIN}
            for entry in guarded(s):
                path = concrete(s, entry)
                if entry.method == "GET":
                    response = machine.get(path, headers=headers)
                elif entry.method == "DELETE":
                    response = machine.delete(path, headers=headers)
                else:
                    response = machine.post(path, json={}, headers=headers)
                if response.status_code != 401:
                    wrong.append((scheme, entry.method, entry.template, response.status_code))
    assert wrong == []


def test_the_completion_scenario_enrols_its_player_through_supported_routes_only() -> None:
    flow = (Path(__file__).parent / "test_phase15_completion_flow.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in flow.splitlines() if not line.lstrip().startswith("#"))
    code = code.split('"""', 2)[2]  # drop the module docstring, which explains what is forbidden
    assert "ContentSetup(harness, db_connection, enrol_player=False)" in code
    for forbidden in ("add_member", "membership_roles", "INSERT INTO security"):
        assert forbidden not in code, forbidden
    assert "FROM security.campaign_memberships" not in code
    for required in ("/invitations", "/campaign-invitations/accept", "/access-overview", "/roles"):
        assert required in code, required


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
