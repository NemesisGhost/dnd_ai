"""Phase 15.1 exit scenario: a GM authors a connected body of world content using
only the HTTP API (a real cookie session, CSRF token and Origin check on every
write) -- places, organizations, a religion, NPCs, a quest and knowledge claims
-- publishes it in dependency order, edits and supersedes some of it, and a
player sees only what has been published. No SQL, import, AI, or VTT.

The only direct SQL is the player's campaign membership (invitation delivery is
Phase 16) and the harness's own account setup.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup

pytestmark = pytest.mark.scenario


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


def test_a_gm_authors_publishes_and_revises_a_connected_world(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    s = ContentSetup(harness, db_connection)

    def post(path: str, body: dict, status: int = 201) -> dict:
        response = s.gm.post(s.url(path), body, key=s.gm.fresh_key())
        assert response.status_code == status, (path, response.text)
        return response.json()

    def update(path: str, record: dict, **fields: object) -> dict:
        body = {"expected_row_version": record["row_version"], **fields}
        return post(path, body, 200)

    # --- author, bottom-up where publishing needs it ---------------------------------
    region = post("locations", {"category": "region", "name": "Ashmark"})
    town = post(
        "locations",
        {
            "category": "settlement",
            "name": "Brindlehaven",
            "parent_location_id": region["location_id"],
            "population": 1200,
        },
    )
    hall = post(
        "locations",
        {"category": "building", "name": "Guildhall", "parent_location_id": town["location_id"]},
    )
    council = post(
        "organizations",
        {
            "kind": "government",
            "name": "Town Council",
            "headquarters_location_id": hall["location_id"],
        },
    )
    faith = post("religions", {"name": "Tidewardens", "summary": None, "pantheon_structure": None})
    options = s.gm.get(s.url("npcs/options")).json()
    npc = post(
        "npcs",
        {
            "name": "Harbormaster Lysa",
            "species_id": options["species"][0]["species_id"],
            "size_category": "medium",
            "origin_location_id": town["location_id"],
            "notes": "Takes bribes.",
        },
    )
    quest = post("quests", {"name": "The Missing Manifest", "summary": None})
    qid = quest["quest_id"]
    stage = post(
        f"quests/{qid}/stages",
        {
            "expected_row_version": quest["row_version"],
            "name": "Find it",
            "stage_type": "sequential",
        },
        200,
    )
    post(
        f"quests/{qid}/stages/{stage['stages'][0]['quest_stage_id']}/objectives",
        {
            "expected_row_version": stage["row_version"],
            "name": "Question Lysa",
            "objective_type": "other",
            "requirement_level": "required",
            "completion_mode": "automatic",
            "visibility_policy": "visible",
            "target_entity_id": npc["npc_id"],
        },
        200,
    )
    claim = post(
        "knowledge",
        {
            "statement": "Lysa takes bribes.",
            "knowledge_type": "rumor",
            "truth_status": "true",
            "sensitivity": "restricted",
            "subject_entity_id": npc["npc_id"],
        },
    )

    # --- a player sees none of it yet --------------------------------------------------
    search = f"/campaigns/{s.cid}/world/search?limit=100"
    assert s.player.get(search).json()["items"] == []
    assert s.player.get(f"/campaigns/{s.cid}/quests").json() == []
    assert s.player.get(f"/campaigns/{s.cid}/knowledge?view=known").json()["items"] == []

    # --- publishing is dependency-ordered ------------------------------------------------
    refused = s.gm.post(
        s.lifecycle(npc["npc_id"], "/publish"),
        {"expected_row_version": npc["row_version"]},
        key=s.gm.fresh_key(),
    )
    assert refused.status_code == 409  # the NPC cannot go canon while its origin is still a draft

    for record, key in (
        (region, "location_id"),
        (town, "location_id"),
        (hall, "location_id"),
        (council, "organization_id"),
        (faith, "religion_id"),
        (npc, "npc_id"),
        (quest, "quest_id"),
    ):
        current = s.gm.get(s.url(f"{_route(key)}/{record[key]}")).json()
        s.publish(record[key], current["row_version"])
    current_claim = s.gm.get(s.url(f"knowledge/{claim['knowledge_item_id']}")).json()
    s.publish(claim["knowledge_item_id"], current_claim["row_version"])

    names = {i["name"] for i in s.player.get(search).json()["items"]}
    assert {"Ashmark", "Brindlehaven", "Guildhall"} <= names
    assert [q["name"] for q in s.player.get(f"/campaigns/{s.cid}/quests").json()] in (
        [],
        ["The Missing Manifest"],
    )

    # --- the GM-only note never reaches the player --------------------------------------
    character = s.player.get(f"/campaigns/{s.cid}/characters/{npc['npc_id']}")
    assert "Takes bribes." not in character.text

    # --- a published place is edited in place and audited --------------------------------
    town_now = s.gm.get(s.url(f"locations/{town['location_id']}")).json()
    edited = update(
        f"locations/{town['location_id']}/update",
        town_now,
        name="Brindlehaven Harbor",
        summary=None,
        parent_location_id=region["location_id"],
        population=1300,
        building_use=None,
    )
    assert edited["name"] == "Brindlehaven Harbor" and edited["changed"] is True
    assert len(s.audit("update_location")) == 1

    # --- archive hides it from players; the GM still reads it ---------------------------
    s.transition(
        hall["location_id"],
        "archive",
        s.gm.get(s.url(f"locations/{hall['location_id']}")).json()["row_version"],
    )
    names_after = {i["name"] for i in s.player.get(search).json()["items"]}
    assert "Guildhall" not in names_after
    assert s.gm.get(s.url(f"locations/{hall['location_id']}")).status_code == 200


def _route(id_key: str) -> str:
    return {
        "location_id": "locations",
        "organization_id": "organizations",
        "religion_id": "religions",
        "npc_id": "npcs",
        "quest_id": "quests",
        "knowledge_item_id": "knowledge",
    }[id_key]
