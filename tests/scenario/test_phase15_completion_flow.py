"""Phase 15 completion exit scenario (PLANv2 15.8, built incrementally).

A GM sets up and runs a campaign using only the HTTP API with a real cookie
session, CSRF token, and Origin check on every write: no SQL, no seed script, no
Foundry, no importer, no AI. Each Phase 15 completion checkpoint appends its
steps to this one flow and keeps the earlier steps green; checkpoint 15.4 runs the
whole flow against a freshly migrated database.

Steps implemented so far (numbering follows the plan's §11 table):

  1  create a world (owner)                 -- Phase 14, via the shared setup
  2  create a campaign                      -- Phase 14, via the shared setup
  3  calendar and world times               -- 15.2W-1
  5  player character identity (builds: B-2) -- 15.2B-1
  6  grant relationship, perspective          -- 15.2B-1 (invitations: later)
  7  party, member, party perspective        -- 15.2C-1, 15.2C-2
  9  advance (and correct) the clock          -- 15.2W-2
 10  schedule and edit a session             -- 15.2D-1
 11  participants, start, log, end           -- 15.2D-2
 12  record and correct an event             -- 15.2E-1
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.queries.bootstrap import get_session_bootstrap
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup

pytestmark = pytest.mark.scenario


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


def test_a_gm_sets_up_and_runs_a_campaign(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    # Steps 1-2: the shared setup creates the world, timeline, and campaign through
    # the production routes (a GM who owns the world, a player, and an outsider).
    s = ContentSetup(harness, db_connection)

    def write(path: str, body: dict, status: int = 201) -> dict:
        response = s.gm.post_raw(path, body, key=s.gm.fresh_key())
        assert response.status_code == status, (path, response.text)
        return response.json()

    # --- Step 3 (15.2W-1): a calendar, calendar dates, and a narrative moment ----------
    calendar = write(
        f"/worlds/{s.world_id}/calendars",
        {
            "name": "Common Reckoning",
            "description": None,
            "days_per_week": 7,
            "epoch_label": "Founding",
            "months": [{"name": "Frost", "day_count": 30}, {"name": "Bloom", "day_count": 30}],
        },
    )
    times = f"/campaigns/{s.cid}/world-times"
    opening = write(
        times, {"calendar_id": calendar["calendar_id"], "year": 1, "month_number": 1, "day": 1}
    )
    siege = write(
        times, {"label": "After the siege", "after_world_time_id": opening["world_time_id"]}
    )
    listed = s.gm.get(times).json()["items"]
    assert [i["world_time_id"] for i in listed] == [
        siege["world_time_id"],
        opening["world_time_id"],
    ]
    assert listed[1]["display"] == "Year 1 (Founding), Frost 1"
    # The player sees none of this authoring surface.
    assert s.player.get(times).status_code == 403
    assert s.player.post_raw(times, {"label": "x", "after_world_time_id": None}).status_code == 403

    # --- Step 9 (15.2W-2): advance the campaign clock, then correct a mistake ----------
    clock = f"/campaigns/{s.cid}/clock"
    assert s.gm.get(clock).json()["current"] is None
    advanced = write(
        f"{clock}/advance",
        {"world_time_id": siege["world_time_id"], "expected_row_version": 0},
        status=200,
    )
    assert s.gm.get(clock).json()["current"]["display"] == "After the siege"
    # A mistaken advance is corrected, not rewritten: the original event stays.
    corrected = write(
        f"{clock}/correct",
        {
            "world_time_id": opening["world_time_id"],
            "expected_row_version": advanced["row_version"],
            "corrects_event_id": advanced["event_id"],
        },
        status=200,
    )
    assert corrected["event_id"] != advanced["event_id"]
    assert s.gm.get(clock).json()["current"]["world_time_id"] == opening["world_time_id"]
    # Any member may read the clock; only an editor may change it.
    assert s.player.get(clock).status_code == 200
    assert (
        s.player.post_raw(
            f"{clock}/advance",
            {"world_time_id": opening["world_time_id"], "expected_row_version": 2},
        ).status_code
        == 403
    )

    # --- Steps 5-6 (15.2B-1): a player character is authored, published, and linked ---
    species = s.gm.get(f"/campaigns/{s.cid}/authoring/player-characters/options").json()["species"][
        0
    ]["species_id"]
    pc = write(
        f"/campaigns/{s.cid}/authoring/player-characters",
        {"name": "Aldric", "species_id": species, "size_category": "medium"},
    )
    pc_id = pc["player_character_id"]
    membership = db_connection.execute(
        text(
            "SELECT campaign_membership_id FROM security.campaign_memberships "
            "WHERE campaign_id = :c AND user_id = :u"
        ),
        {"c": s.cid, "u": s.player.user_id},
    ).scalar()
    link = f"/campaigns/{s.cid}/memberships/{membership}/character-relationships"

    def perspectives() -> list[str]:
        bootstrap = get_session_bootstrap(db_connection, user_id=s.player.user_id)
        campaign = next(c for c in bootstrap.campaigns if str(c.campaign_id) == s.cid)
        return [str(p.character_id) for p in campaign.character_perspectives]

    # A draft is invisible to the player, and linking a player to it confers nothing yet.
    assert s.player.get(f"/campaigns/{s.cid}/characters/{pc_id}").status_code == 404
    write(link, {"character_id": pc_id, "relationship_type_code": "owner"})
    assert perspectives() == []
    # Publishing makes the identity (without GM notes) and the perspective available.
    s.publish(pc_id, pc["row_version"])
    assert s.player.get(f"/campaigns/{s.cid}/characters/{pc_id}").status_code == 200
    assert perspectives() == [pc_id]

    # --- Step 5 (15.2B-2): a build, starting state, and the first activation ----------
    options = s.gm.get(f"/campaigns/{s.cid}/authoring/character-build-options").json()
    builds = f"/campaigns/{s.cid}/authoring/characters/{pc_id}/builds"
    build = write(
        builds,
        {
            "label": "Level 1 Fighter",
            "ability_scores": [{"ability_id": options["abilities"][0]["id"], "score": 15}],
            "class_levels": [
                {"class_id": options["classes"][0]["id"], "subclass_id": None, "level": 1}
            ],
        },
    )
    write(
        f"/campaigns/{s.cid}/authoring/characters/{pc_id}/state/initialize",
        {"maximum_hit_points": 12},
    )
    activated = write(
        f"{builds}/{build['character_build_id']}/activate",
        {"expected_active_build_id": None},
        status=200,
    )
    assert "event_id" not in activated  # the first activation is the administrative baseline
    listing = s.gm.get(builds).json()
    assert listing["active_build_id"] == build["character_build_id"]
    assert listing["state"]["current_hit_points"] == 12
    assert s.player.get(builds).status_code == 403

    # --- Step 7 (15.2C-1, 15.2C-2): a party, a member, and the party perspective -------
    party = write(f"/campaigns/{s.cid}/parties", {"name": "The Company"})
    members = f"/campaigns/{s.cid}/parties/{party['party_id']}/members"
    joined = write(
        members,
        {
            "character_id": pc_id,
            "effective_from_world_time_id": opening["world_time_id"],
            "expected_party_row_version": party["row_version"],
        },
    )
    assert [m["character_name"] for m in s.gm.get(members).json()["members"]] == ["Aldric"]
    campaign_view = next(
        c
        for c in get_session_bootstrap(db_connection, user_id=s.player.user_id).campaigns
        if str(c.campaign_id) == s.cid
    )
    assert [
        str(p.party_id)
        for pv in campaign_view.character_perspectives
        for p in pv.authorized_parties
    ] == [party["party_id"]]
    write(
        f"{members}/{joined['party_membership_id']}/end",
        {
            "effective_to_world_time_id": siege["world_time_id"],
            "expected_party_row_version": joined["row_version"],
        },
        status=200,
    )
    assert s.gm.get(members).json()["members"][0]["is_current"] is False
    assert s.player.get(members).status_code == 403

    # --- Step 10 (15.2D-1): schedule a session, edit it, and see its derived status ----
    sessions = f"/campaigns/{s.cid}/sessions"
    session = write(sessions, {"title": "The Hollow Road", "scheduled_for": "2026-12-01T19:00:00Z"})
    assert session["session_number"] == 1
    write(
        f"{sessions}/{session['session_id']}/update",
        {
            "expected_row_version": session["row_version"],
            "title": "The Hollow Road, part one",
            "scheduled_for": "2026-12-01T19:00:00Z",
            "summary": "The party sets out.",
        },
        status=200,
    )
    listed_sessions = s.gm.get(sessions).json()
    assert [(i["title"], i["play_status"]) for i in listed_sessions] == [
        ("The Hollow Road, part one", "scheduled")
    ]
    assert s.player.get(sessions).json()[0]["row_version"] is None
    assert s.player.post_raw(sessions, {"title": "x"}).status_code == 403

    # --- Step 11 (15.2D-2): run the session: participant, start, log, end ---------------
    session_url = f"{sessions}/{session['session_id']}"

    def session_version() -> int:
        return int(s.gm.get(session_url).json()["row_version"])

    write(
        f"{session_url}/participants",
        {
            "expected_row_version": session_version(),
            "character_id": pc_id,
            "participation_role": "player_character",
        },
    )
    write(f"{session_url}/start", {"expected_row_version": session_version()}, status=200)
    logged = write(
        f"{session_url}/log",
        {"entry": "The party sets out.", "details": "GM only: the road is watched"},
    )
    assert logged["event_id"]
    played = s.gm.get(session_url).json()
    assert played["play_status"] == "in_progress"
    assert [p["character_name"] for p in played["participants"]] == ["Aldric"]
    seen_by_player = s.player.get(session_url).json()
    assert seen_by_player["participants"] is None
    assert [e["details"] for e in seen_by_player["events"]] == [None]
    write(
        f"{session_url}/end",
        {
            "expected_row_version": session_version(),
            "end_world_time_id": siege["world_time_id"],
            "summary": "A good start.",
        },
        status=200,
    )
    assert s.gm.get(session_url).json()["play_status"] == "completed"

    # --- Step 12 (15.2E-1): record an event, then correct it without losing history ----
    recorded = write(
        f"/campaigns/{s.cid}/events",
        {
            "world_time_id": opening["world_time_id"],
            "event_type_code": "other",
            "name": "The gate is found locked",
        },
    )
    event_url = f"/campaigns/{s.cid}/events/{recorded['event_id']}"
    assert s.gm.get(f"{event_url}/correction-preview").json()["can_correct"] is True
    corrected = write(
        f"{event_url}/correct",
        {
            "reason": "The gate was only stuck.",
            "replacement": {"event_type_code": "other", "name": "The gate is found stuck"},
        },
        status=200,
    )
    assert corrected["status"] == "corrected" and corrected["replacement_event_id"]
    history = s.gm.get(event_url).json()
    assert history["status"] == "corrected" and history["name"] == "The gate is found locked"
    assert history["correction"]["replacement_event_id"] == corrected["replacement_event_id"]
    assert s.player.get(f"{event_url}/correction-preview").status_code == 403

    # --- Step 13 (15.2E-2a): a quest gets dependencies, an outcome, a reward and notes ----
    quests = f"/campaigns/{s.cid}/authoring/quests"
    quest = write(quests, {"name": "The Lost Amulet", "summary": "Find it."})
    quest_url = f"{quests}/{quest['quest_id']}"

    def quest_write(suffix: str, body: dict) -> dict:
        version = int(s.gm.get(quest_url).json()["row_version"])
        write(f"{quest_url}{suffix}", {"expected_row_version": version, **body}, status=200)
        return dict(s.gm.get(quest_url).json())

    view = quest_write(
        "/stages", {"name": "Search", "description": None, "stage_type": "sequential"}
    )
    for name in ("Find the map", "Reach the ruin"):
        view = quest_write(
            f"/stages/{view['stages'][0]['quest_stage_id']}/objectives",
            {
                "name": name,
                "description": None,
                "objective_type": "other",
                "requirement_level": "required",
                "completion_mode": "automatic",
                "visibility_policy": "visible",
                "quantity_required": None,
                "target_entity_id": None,
            },
        )
    first, second = (o["quest_objective_id"] for o in view["stages"][0]["objectives"])
    view = quest_write(
        "/dependencies",
        {
            "objective_id": second,
            "depends_on_objective_id": first,
            "dependency_type": "prerequisite",
        },
    )
    assert len(view["dependencies"]) == 1
    view = quest_write(
        "/outcomes",
        {
            "code": "saved",
            "name": "The village is saved",
            "description": None,
            "outcome_category": "success",
        },
    )
    outcome_id = view["outcomes"][0]["quest_outcome_id"]
    view = quest_write(
        f"/outcomes/{outcome_id}/rewards",
        {"reward_type": "other", "description": "50 gold", "reward_knowledge_item_id": None},
    )
    assert view["outcomes"][0]["rewards"][0]["description"] == "50 gold"
    view = quest_write(
        "/update", {"name": view["name"], "summary": view["summary"], "gm_notes": "Twist"}
    )
    assert view["gm_notes"] == "Twist"
    assert "gm_notes" not in s.player.get(f"/campaigns/{s.cid}/quests/{quest['quest_id']}").text

    # --- Step 14 (15.2E-2b): publish the quest and run it with explicit GM commands -----
    for action in ("submit-for-review", "approve", "publish"):
        lifecycle = f"/campaigns/{s.cid}/entities/{quest['quest_id']}/lifecycle"
        version = int(s.gm.get(quest_url).json()["row_version"])
        write(f"{lifecycle}/{action}", {"expected_row_version": version}, status=200)
    quest_runtime = f"/campaigns/{s.cid}/quests/{quest['quest_id']}"
    write(f"{quest_runtime}/activate", {"expected_status": None}, status=200)
    write(
        f"/campaigns/{s.cid}/quests/objectives/{first}/status",
        {"new_status": "completed", "expected_status": None},
        status=200,
    )
    scope = s.gm.get(f"{quest_runtime}/progress").json()["scopes"][0]
    assert scope["status"] == "active" and scope["all_required_complete"] is False
    write(f"{quest_runtime}/complete", {"expected_status": "active", "note": "Done."}, status=200)
    assert s.gm.get(f"{quest_runtime}/progress").json()["scopes"][0]["status"] == "completed"
    assert s.player.get(f"{quest_runtime}/progress").status_code == 403

    # --- Step 15 (15.2E-3): a claim is learned, believed differently, and made public ----
    claim = write(
        f"/campaigns/{s.cid}/authoring/knowledge",
        {
            "statement": "The duke is a vampire.",
            "knowledge_type": "secret",
            "truth_status": "true",
            "sensitivity": "secret",
        },
    )
    for action in ("submit-for-review", "approve", "publish"):
        lifecycle = f"/campaigns/{s.cid}/entities/{claim['knowledge_item_id']}/lifecycle"
        version = int(
            s.gm.get(f"/campaigns/{s.cid}/authoring/knowledge/{claim['knowledge_item_id']}").json()[
                "row_version"
            ]
        )
        write(f"{lifecycle}/{action}", {"expected_row_version": version}, status=200)
    knowledge = f"/campaigns/{s.cid}/knowledge/{claim['knowledge_item_id']}"
    learned = write(
        f"{knowledge}/learn",
        {"knower_entity_id": pc_id, "awareness_level": "suspected", "interpretation": "He is ill."},
    )
    audience = s.gm.get(f"{knowledge}/audience").json()
    belief = audience["knowers"][0]
    assert (
        belief["awareness_level"] == "suspected" and belief["last_event_id"] == learned["event_id"]
    )
    write(
        f"/campaigns/{s.cid}/knowledge/knowers/{belief['entity_knowledge_id']}/belief",
        {"expected_last_event_id": learned["event_id"], "interpretation": "He is undead."},
        status=200,
    )
    assert (
        s.gm.get(f"{knowledge}/audience").json()["knowers"][0]["interpretation"] == "He is undead."
    )
    assert s.player.get(f"{knowledge}/audience").status_code == 403

    # --- Step 16 (15.3A-1): a dungeon is authored, published, run and read by a player ----
    authoring = f"/campaigns/{s.cid}/authoring"
    dungeon = write(f"{authoring}/dungeons", {"name": "The Sunken Vault", "danger_level": 6})
    dungeon_url = f"{authoring}/dungeons/{dungeon['dungeon_id']}"

    def dungeon_version() -> int:
        return int(s.gm.get(dungeon_url).json()["row_version"])

    areas = []
    for name in ("Entry Hall", "Vault"):
        created = write(f"{dungeon_url}/areas", {"name": name})
        areas.append(created["dungeon_area_id"])
    write(
        f"{dungeon_url}/connections",
        {
            "expected_row_version": dungeon_version(),
            "from_area_id": areas[0],
            "to_area_id": areas[1],
            "connection_type": "door",
        },
    )
    write(
        f"{dungeon_url}/hazards",
        {
            "expected_row_version": dungeon_version(),
            "dungeon_area_id": areas[0],
            "child_type": "trap",
            "severity": 5,
            "is_hidden": True,
        },
    )
    for entity_id in (dungeon["dungeon_id"], *areas):
        for action in ("submit-for-review", "approve", "publish"):
            current = (
                s.gm.get(dungeon_url)
                if entity_id == dungeon["dungeon_id"]
                else s.gm.get(f"{authoring}/dungeon-areas/{entity_id}")
            ).json()
            write(
                f"/campaigns/{s.cid}/entities/{entity_id}/lifecycle/{action}",
                {"expected_row_version": current["row_version"]},
                status=200,
            )
    hall = s.gm.get(f"{authoring}/dungeon-areas/{areas[0]}").json()
    door = hall["connections"][0]["area_connection_id"]
    write(
        f"/campaigns/{s.cid}/dungeon-areas/{areas[0]}/state",
        {
            "kind": "connection",
            "target_id": door,
            "expected_last_event_id": None,
            "connection_status": "open",
        },
        status=200,
    )
    seen = s.player.get(f"/campaigns/{s.cid}/dungeon-areas/{areas[0]}").json()
    assert seen["connections"][0]["connection_status_code"] == "open"
    assert seen["hazards"] == []  # hidden and undiscovered
