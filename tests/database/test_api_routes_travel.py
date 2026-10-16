"""Routes between locations and recording travel (checkpoint 15.3A-2c, decision D-20, migration 130)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times, _advance

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def code(response) -> str:  # type: ignore[no-untyped-def]
    return str(response.json()["error"]["code"])


def place(s: ContentSetup, name: str, *, publish: bool = True) -> str:
    created = s.gm.post(
        s.url("locations"), {"category": "settlement", "name": name}, key=s.gm.fresh_key()
    ).json()
    if publish:
        s.publish(created["location_id"], created["row_version"])
    return str(created["location_id"])


def pc(s: ContentSetup, name: str, *, publish: bool = True) -> str:
    species = s.gm.get(s.url("player-characters/options")).json()["species"][0]["species_id"]
    created = s.gm.post(
        s.url("player-characters"),
        {"name": name, "species_id": species, "size_category": "medium"},
        key=s.gm.fresh_key(),
    ).json()
    if publish:
        s.publish(created["player_character_id"], created["row_version"])
    return str(created["player_character_id"])


def route(s: ContentSetup, origin: str, destination: str, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post(
        s.url("relationships"),
        {
            "kind": "route",
            "relationship_type": "route",
            "participants": [
                {"entity_id": origin, "role": "origin"},
                {"entity_id": destination, "role": "destination"},
            ],
            **extra,
        },
        key=s.gm.fresh_key(),
    )


def travel(s: ContentSetup, destination: str, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        f"/campaigns/{s.cid}/travel",
        {"destination_location_id": destination, **extra},
        key=s.gm.fresh_key(),
    )


def clock_at(s: ContentSetup, year: int, times: Times | None = None) -> str:
    times = times or Times(s)
    time_id = times.at(year)
    version = s.connection.execute(
        text("""
            SELECT tc.row_version FROM campaign.timeline_clocks tc
            JOIN campaign.campaigns c ON c.timeline_id = tc.timeline_id WHERE c.campaign_id = :c
        """),
        {"c": s.cid},
    ).scalar()
    assert _advance(s, time_id, int(version or 0)).status_code == 200
    return time_id


def history(s: ContentSetup, character: str) -> list[tuple[str, bool]]:
    rows = s.connection.execute(
        text("""
            SELECT e.canonical_name, h.departed_at_world_time_id IS NULL AS open
            FROM campaign.character_location_history h
            JOIN core.entities e ON e.entity_id = h.location_id
            JOIN core.world_times wt ON wt.world_time_id = h.arrived_at_world_time_id
            WHERE h.character_id = :c ORDER BY wt.sort_key
        """),
        {"c": character},
    ).all()
    return [(str(r.canonical_name), bool(r.open)) for r in rows]


def events(s: ContentSetup) -> int:
    return int(
        s.connection.execute(
            text("""
                SELECT count(*) FROM narrative.events ev
                JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
                WHERE ev.campaign_id = :c AND et.code = 'characters_traveled'
            """),
            {"c": s.cid},
        ).scalar()
        or 0
    )


def test_a_route_joins_two_places_with_travel_details(s: ContentSetup) -> None:
    north, south = place(s, "Northmark"), place(s, "Southmark")
    created = route(
        s,
        north,
        south,
        description="The old salt road.",
        distance_text="40 miles",
        travel_time_text="Two days",
        travel_mode="On foot",
        is_hidden=False,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "route"
    assert body["typed"] == {
        "distance_text": "40 miles",
        "travel_time_text": "Two days",
        "travel_mode": "On foot",
        "is_hidden": False,
    }
    assert {(p["role"], p["name"]) for p in body["participants"]} == {
        ("origin", "Northmark"),
        ("destination", "Southmark"),
    }
    listed = s.gm.get(s.url("routes"), location_id=south).json()["items"]
    assert [(i["origin"]["name"], i["destination"]["name"]) for i in listed] == [
        ("Northmark", "Southmark")
    ]
    assert s.player.get(s.url("routes"), location_id=south).status_code == 403
    updated = s.gm.post(
        s.url(f"relationships/{body['relationship_id']}/update"),
        {
            "expected_row_version": body["row_version"],
            "description": "The old salt road.",
            "distance_text": "42 miles",
            "is_hidden": True,
        },
        key=s.gm.fresh_key(),
    )
    assert updated.status_code == 200 and updated.json()["typed"]["distance_text"] == "42 miles"


def test_route_shapes_are_checked(s: ContentSetup) -> None:
    north, south = place(s, "Northmark"), place(s, "Southmark")
    mira = pc(s, "Mira")
    before = s.count("world.route_relationships")
    for response in (
        route(s, north, north),
        route(s, north, mira),
        route(s, mira, south),
    ):
        assert response.status_code == 400, response.text
    assert s.count("world.route_relationships") == before


def test_a_concealed_route_is_hidden_from_readers_only(s: ContentSetup) -> None:
    north, south, east = place(s, "Northmark"), place(s, "Southmark"), place(s, "Eastmark")
    open_road = route(s, north, south).json()
    secret = route(s, north, east, is_hidden=True).json()
    reader = s.player.get(f"/campaigns/{s.cid}/world/relationships").json()["items"]
    assert [i["relationship_id"] for i in reader] == [open_road["relationship_id"]]
    assert (
        s.player.get(f"/campaigns/{s.cid}/relationships/{secret['relationship_id']}").status_code
        == 404
    )
    editor = s.gm.get(f"/campaigns/{s.cid}/world/relationships").json()["items"]
    assert {i["relationship_id"] for i in editor} == {
        open_road["relationship_id"],
        secret["relationship_id"],
    }


def test_travel_moves_several_characters_in_one_event(s: ContentSetup) -> None:
    town, keep = place(s, "Stonebridge"), place(s, "The Keep")
    aldric, mira = pc(s, "Aldric"), pc(s, "Mira")
    times = Times(s)
    clock_at(s, 1, times)
    first = travel(s, town, character_ids=[aldric, mira], note="GM only: they set out at dawn")
    assert first.status_code == 200, first.text
    assert first.json()["changed"] is True and set(first.json()["moved"]) == {aldric, mira}
    assert history(s, aldric) == [("Stonebridge", True)]
    assert events(s) == 1
    clock_at(s, 2, times)
    again = travel(s, town, character_ids=[aldric, mira])
    assert again.status_code == 200
    assert again.json()["changed"] is False and set(again.json()["already_there"]) == {aldric, mira}
    assert events(s) == 1
    moved = travel(s, keep, character_ids=[aldric])
    assert moved.status_code == 200 and moved.json()["moved"] == [aldric]
    assert history(s, aldric) == [("Stonebridge", False), ("The Keep", True)]
    assert history(s, mira) == [("Stonebridge", True)]
    effects = s.connection.execute(
        text("""
            SELECT count(*) FROM narrative.event_effects ef
            WHERE ef.event_id = :e AND ef.target_component = 'current_location_id'
        """),
        {"e": first.json()["event_id"]},
    ).scalar()
    assert effects == 2
    [audit, *_] = s.audit("record_travel")
    assert audit.action == "updated" and audit.changed_fields["traveler_count"]["to"] == 2


def test_a_party_travels_as_its_current_members(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    aldric, mira, out = pc(s, "Aldric"), pc(s, "Mira"), pc(s, "Left Behind")
    times = Times(s)
    year1 = clock_at(s, 1, times)
    party = s.gm.post_raw(
        f"/campaigns/{s.cid}/parties", {"name": "The Company"}, key=s.gm.fresh_key()
    ).json()
    for member in (aldric, mira):
        added = s.gm.post_raw(
            f"/campaigns/{s.cid}/parties/{party['party_id']}/members",
            {
                "character_id": member,
                "effective_from_world_time_id": year1,
                "expected_party_row_version": s.gm.get(
                    f"/campaigns/{s.cid}/parties/{party['party_id']}"
                ).json()["row_version"],
            },
            key=s.gm.fresh_key(),
        )
        assert added.status_code == 201, added.text
    clock_at(s, 2, times)
    result = travel(s, town, party_id=party["party_id"], character_ids=[out])
    assert result.status_code == 200, result.text
    assert set(result.json()["moved"]) == {aldric, mira, out}
    foreign = s.stranger.post_raw(
        f"/campaigns/{s.other_cid}/travel",
        {"destination_location_id": town, "party_id": party["party_id"]},
        key=s.stranger.fresh_key(),
    )
    assert foreign.status_code in (400, 404)


def test_one_bad_traveler_stops_the_whole_journey(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    aldric, draft = pc(s, "Aldric"), pc(s, "Unpublished", publish=False)
    clock_at(s, 1)
    refused = travel(s, town, character_ids=[aldric, draft])
    assert refused.status_code == 400 and code(refused) == "travel_invalid"
    assert history(s, aldric) == [] and events(s) == 0
    for body in (
        {"character_ids": []},
        {"character_ids": [str(uuid.uuid4())]},
        {"character_ids": [aldric], "destination_location_id": str(uuid.uuid4())},
    ):
        response = s.gm.post_raw(
            f"/campaigns/{s.cid}/travel",
            {"destination_location_id": town, **body},
            key=s.gm.fresh_key(),
        )
        assert response.status_code == 400, response.text
    draft_place = place(s, "Unbuilt", publish=False)
    assert travel(s, draft_place, character_ids=[aldric]).status_code == 400
    assert history(s, aldric) == []


def test_a_route_must_join_where_they_are_to_where_they_are_going(s: ContentSetup) -> None:
    north, south, east = place(s, "Northmark"), place(s, "Southmark"), place(s, "Eastmark")
    aldric = pc(s, "Aldric")
    times = Times(s)
    clock_at(s, 1, times)
    road = route(s, north, south).json()
    assert travel(s, north, character_ids=[aldric]).status_code == 200
    clock_at(s, 2, times)
    wrong_end = travel(s, east, character_ids=[aldric], route_id=road["relationship_id"])
    assert wrong_end.status_code == 409 and code(wrong_end) == "route_mismatch"
    ok = travel(s, south, character_ids=[aldric], route_id=road["relationship_id"])
    assert ok.status_code == 200, ok.text
    clock_at(s, 3, times)
    # Back along the same road is fine; a traveler with no known start is not on any road.
    back = travel(s, north, character_ids=[aldric], route_id=road["relationship_id"])
    assert back.status_code == 200
    stranger = pc(s, "Newcomer")
    nowhere = travel(s, south, character_ids=[stranger], route_id=road["relationship_id"])
    assert nowhere.status_code == 409 and code(nowhere) == "route_mismatch"
    archived = s.gm.post(
        s.url(f"relationships/{road['relationship_id']}/archive"),
        {
            "expected_row_version": s.gm.get(
                s.url(f"relationships/{road['relationship_id']}")
            ).json()["row_version"]
        },
        key=s.gm.fresh_key(),
    )
    assert archived.status_code == 200
    clock_at(s, 4, times)
    gone = travel(s, south, character_ids=[aldric], route_id=road["relationship_id"])
    assert gone.status_code == 409 and code(gone) == "route_mismatch"
    missing = travel(s, south, character_ids=[aldric], route_id=str(uuid.uuid4()))
    assert missing.status_code == 409


def test_time_comes_from_the_clock_and_must_follow_the_arrival(s: ContentSetup) -> None:
    north, south = place(s, "Northmark"), place(s, "Southmark")
    aldric = pc(s, "Aldric")
    needs = travel(s, north, character_ids=[aldric])
    assert needs.status_code == 409 and code(needs) == "clock_required"
    times = Times(s)
    clock_at(s, 5, times)
    assert travel(s, north, character_ids=[aldric]).status_code == 200
    same_time = travel(s, south, character_ids=[aldric])
    assert same_time.status_code == 409 and code(same_time) == "travel_time_invalid"
    explicit = travel(s, south, character_ids=[aldric], world_time_id=times.at(9))
    assert explicit.status_code == 200
    assert history(s, aldric) == [("Northmark", False), ("Southmark", True)]


def test_authority_and_replay(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    aldric = pc(s, "Aldric")
    clock_at(s, 1)
    denied = s.player.post_raw(
        f"/campaigns/{s.cid}/travel",
        {"destination_location_id": town, "character_ids": [aldric]},
        key=s.player.fresh_key(),
    )
    assert denied.status_code == 403
    key = s.gm.fresh_key()
    body = {"destination_location_id": town, "character_ids": [aldric]}
    first = s.gm.post_raw(f"/campaigns/{s.cid}/travel", body, key=key)
    replay = s.gm.post_raw(f"/campaigns/{s.cid}/travel", body, key=key)
    assert first.status_code == replay.status_code == 200 and first.json() == replay.json()
    assert events(s) == 1 and len(s.audit("record_travel")) == 1
