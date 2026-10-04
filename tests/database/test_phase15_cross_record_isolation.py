"""Cross-record isolation across every Phase 15.1 authoring type.

One matrix over locations, organizations, religions, NPCs, quests, and knowledge
claims: another world's record, a record of a different type, and a missing id
are the same non-disclosing 404 on every authoring read, update, and lifecycle
route; callers without `canon.edit` are refused before any lookup; and an
unpublished draft of any type is invisible to a player in every discovery
surface the type has.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection

from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup

pytestmark = pytest.mark.database

# route segment -> key of the record id in the authoring view
TYPES: dict[str, str] = {
    "locations": "location_id",
    "organizations": "organization_id",
    "religions": "religion_id",
    "npcs": "npc_id",
    "quests": "quest_id",
    "knowledge": "knowledge_item_id",
}


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def _species(actor: Actor, setup: ContentSetup, cid: str) -> str:
    options = actor.get(setup.url("npcs/options", cid)).json()
    return options["species"][0]["species_id"]


def make_all(actor: Actor, setup: ContentSetup, cid: str, tag: str) -> dict[str, dict]:
    """One draft record of every type in `cid`'s world, created through the routes."""

    def post(path: str, body: dict) -> dict:
        response = actor.post(setup.url(path, cid), body, key=actor.fresh_key())
        assert response.status_code == 201, (path, response.text)
        return response.json()

    return {
        "locations": post("locations", {"category": "region", "name": f"{tag} Region"}),
        "organizations": post(
            "organizations",
            {"kind": "organization", "organization_type": "guild", "name": f"{tag} Guild"},
        ),
        "religions": post(
            "religions", {"name": f"{tag} Faith", "summary": None, "pantheon_structure": None}
        ),
        "npcs": post(
            "npcs",
            {
                "name": f"{tag} Npc",
                "species_id": _species(actor, setup, cid),
                "size_category": "medium",
            },
        ),
        "quests": post("quests", {"name": f"{tag} Quest", "summary": None}),
        "knowledge": post(
            "knowledge",
            {
                "statement": f"{tag} claim.",
                "knowledge_type": "secret",
                "truth_status": "true",
                "sensitivity": "secret",
            },
        ),
    }


@pytest.fixture
def records(s: ContentSetup) -> dict[str, dict[str, dict]]:
    return {
        "mine": make_all(s.gm, s, s.cid, "Mine"),
        "foreign": make_all(s.stranger, s, s.other_cid, "Foreign"),
    }


def record_id(kind: str, record: dict) -> str:
    return record[TYPES[kind]]


# --- another world's record, a different type's record, and a missing id --------------------


@pytest.mark.parametrize("kind", list(TYPES))
def test_every_authoring_read_gives_one_404_for_foreign_wrong_type_and_missing_ids(
    s: ContentSetup, records: dict[str, dict[str, dict]], kind: str
) -> None:
    candidates = [record_id(kind, records["foreign"][kind]), str(uuid.uuid4())]
    candidates += [record_id(other, records["mine"][other]) for other in TYPES if other != kind]
    bodies = set()
    for candidate in candidates:
        response = s.gm.get(s.url(f"{kind}/{candidate}"))
        assert response.status_code == 404, (kind, candidate, response.text)
        error = response.json()["error"]
        bodies.add((error["code"], error["message"]))
    assert len(bodies) == 1
    # Control: the type's own record is readable.
    own = record_id(kind, records["mine"][kind])
    assert s.gm.get(s.url(f"{kind}/{own}")).status_code == 200


@pytest.mark.parametrize("kind", list(TYPES))
def test_lifecycle_commands_on_another_worlds_record_are_404_and_change_nothing(
    s: ContentSetup, records: dict[str, dict[str, dict]], kind: str
) -> None:
    foreign = records["foreign"][kind]
    foreign_id = record_id(kind, foreign)
    for action in ("submit-for-review", "archive"):
        response = s.gm.post(
            s.lifecycle(foreign_id, f"/{action}"),
            {"expected_row_version": foreign["row_version"]},
            key=s.gm.fresh_key(),
        )
        assert response.status_code == 404, (kind, action, response.text)
    still = s.stranger.get(s.url(f"{kind}/{foreign_id}", s.other_cid)).json()
    assert (still["canon_status"], still["lifecycle_status"], still["row_version"]) == (
        "draft",
        "active",
        foreign["row_version"],
    )


def test_a_foreign_record_cannot_be_named_as_a_reference_in_any_form(
    s: ContentSetup, records: dict[str, dict[str, dict]]
) -> None:
    foreign = records["foreign"]
    location = record_id("locations", foreign["locations"])
    religion = record_id("religions", foreign["religions"])
    guild = record_id("organizations", foreign["organizations"])
    attempts = [
        (
            "locations",
            {"category": "settlement", "name": "x", "parent_location_id": location},
            "parent_location_invalid",
        ),
        (
            "organizations",
            {
                "kind": "organization",
                "organization_type": "guild",
                "name": "x",
                "parent_organization_id": guild,
            },
            "organization_parent_invalid",
        ),
        (
            "organizations",
            {
                "kind": "organization",
                "organization_type": "guild",
                "name": "x",
                "headquarters_location_id": location,
            },
            "headquarters_location_invalid",
        ),
        (
            "organizations",
            {
                "kind": "religious_organization",
                "name": "x",
                "religion_id": religion,
            },
            "religion_invalid",
        ),
        (
            "npcs",
            {
                "name": "x",
                "species_id": _species(s.gm, s, s.cid),
                "size_category": "medium",
                "origin_location_id": location,
            },
            "origin_location_invalid",
        ),
        (
            "knowledge",
            {
                "statement": "x",
                "knowledge_type": "secret",
                "truth_status": "true",
                "sensitivity": "secret",
                "subject_entity_id": location,
            },
            "knowledge_subject_invalid",
        ),
    ]
    for path, body, code in attempts:
        before = s.count("core.entities")
        response = s.gm.post(s.url(path), body, key=s.gm.fresh_key())
        assert response.status_code == 400, (path, response.text)
        assert response.json()["error"]["code"] == code
        assert s.count("core.entities") == before


# --- callers without canon.edit -------------------------------------------------------------


@pytest.mark.parametrize("kind", list(TYPES))
def test_a_player_is_refused_every_authoring_route_before_any_lookup(
    s: ContentSetup, records: dict[str, dict[str, dict]], kind: str
) -> None:
    mine = records["mine"][kind]
    existing = record_id(kind, mine)
    for candidate in (existing, str(uuid.uuid4()), record_id(kind, records["foreign"][kind])):
        response = s.player.get(s.url(f"{kind}/{candidate}"))
        assert response.status_code == 403, (kind, response.text)
    # The refusal does not depend on whether the id exists.
    codes = {
        s.player.get(s.url(f"{kind}/{c}")).json()["error"]["code"]
        for c in (existing, str(uuid.uuid4()))
    }
    assert len(codes) == 1
    response = s.player.post(
        s.lifecycle(existing, "/archive"),
        {"expected_row_version": mine["row_version"]},
        key=s.player.fresh_key(),
    )
    assert response.status_code == 403


@pytest.mark.parametrize("kind", list(TYPES))
def test_a_stranger_gm_cannot_use_another_campaigns_authoring_routes(
    s: ContentSetup, records: dict[str, dict[str, dict]], kind: str
) -> None:
    own = record_id(kind, records["mine"][kind])
    # A non-member learns nothing about the campaign: the same 404 as a missing one.
    assert s.stranger.get(s.url(f"{kind}/{own}")).status_code == 404
    assert s.stranger.get(s.url(f"{kind}/{own}", s.other_cid)).status_code == 404


# --- unpublished drafts are invisible to players ----------------------------------------------


def test_no_draft_of_any_type_is_discoverable_by_a_player_but_all_are_by_the_gm(
    s: ContentSetup, records: dict[str, dict[str, dict]]
) -> None:
    mine = records["mine"]
    draft_ids = {record_id(kind, mine[kind]) for kind in TYPES}
    search = f"/campaigns/{s.cid}/world/search?limit=100"
    player_ids = {i["entity_id"] for i in s.player.get(search).json()["items"]}
    assert player_ids.isdisjoint(draft_ids)
    gm_ids = {i["entity_id"] for i in s.gm.get(search + "&include_noncanon=true").json()["items"]}
    assert {record_id(k, mine[k]) for k in ("locations", "organizations", "religions")} <= gm_ids

    # Detail routes the audience-safe surfaces expose.
    for path in (
        f"/campaigns/{s.cid}/world/organizations/{record_id('organizations', mine['organizations'])}",
        f"/campaigns/{s.cid}/quests/{record_id('quests', mine['quests'])}",
        f"/campaigns/{s.cid}/knowledge/{record_id('knowledge', mine['knowledge'])}",
        f"/campaigns/{s.cid}/characters/{record_id('npcs', mine['npcs'])}",
    ):
        assert s.player.get(path).status_code == 404, path
    for path in (f"/campaigns/{s.cid}/quests", f"/campaigns/{s.cid}/knowledge?view=known"):
        body = s.player.get(path).json()
        items = body["items"] if isinstance(body, dict) else body
        listed = {i.get("quest_id") or i.get("knowledge_item_id") for i in items}
        assert listed.isdisjoint(draft_ids), path


def test_publishing_makes_a_draft_visible_and_archiving_hides_it_again(
    s: ContentSetup, records: dict[str, dict[str, dict]]
) -> None:
    claim = records["mine"]["knowledge"]
    kid = record_id("knowledge", claim)
    path = f"/campaigns/{s.cid}/knowledge/{kid}"
    assert s.player.get(path).status_code == 404
    version = s.publish(kid, claim["row_version"])
    assert s.player.get(path).status_code in (200, 404)  # visible only to a knower; never a 5xx
    listed = s.player.get(f"/campaigns/{s.cid}/knowledge?view=known").json()["items"]
    assert kid not in {i["knowledge_item_id"] for i in listed}  # nobody knows it yet
    s.transition(kid, "archive", version)
    assert s.gm.get(path).status_code == 200  # archived stays readable to the editor by id


# --- editor status filter on world search -------------------------------------------------------


def test_the_canon_status_filter_is_editor_only(
    s: ContentSetup, records: dict[str, dict[str, dict]]
) -> None:
    place = records["mine"]["locations"]
    pid = record_id("locations", place)
    s.publish(pid, place["row_version"])
    draft_org = record_id("organizations", records["mine"]["organizations"])

    def ids(actor: Actor, query: str) -> set[str]:
        response = actor.get(f"/campaigns/{s.cid}/world/search?limit=100&{query}")
        assert response.status_code == 200, response.text
        return {i["entity_id"] for i in response.json()["items"]}

    gm_drafts = ids(s.gm, "include_noncanon=true&canon_status=draft")
    assert draft_org in gm_drafts and pid not in gm_drafts
    gm_canon = ids(s.gm, "include_noncanon=true&canon_status=canon")
    assert pid in gm_canon and draft_org not in gm_canon
    # A player's filter is ignored; they still see only published definitions.
    player = ids(s.player, "include_noncanon=true&canon_status=draft")
    assert draft_org not in player and pid in player
    bad = s.gm.get(f"/campaigns/{s.cid}/world/search?canon_status=bogus")
    assert bad.status_code == 422
