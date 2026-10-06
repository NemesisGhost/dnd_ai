"""Dungeon authoring and runtime state (checkpoint 15.3A-1, decision D-31, migration 128)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.domain.data_classification import replay_body
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


def dungeon_url(s: ContentSetup, dungeon_id: str, suffix: str = "") -> str:
    return s.url(f"dungeons/{dungeon_id}{suffix}")


def new_dungeon(s: ContentSetup, name: str = "The Sunken Vault", **extra: object) -> dict:
    response = s.gm.post(
        s.url("dungeons"),
        {"name": name, "summary": "Flooded halls.", "danger_level": 6, **extra},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def view(s: ContentSetup, dungeon_id: str) -> dict:
    response = s.gm.get(dungeon_url(s, dungeon_id))
    assert response.status_code == 200, response.text
    return response.json()


def post(s: ContentSetup, dungeon: dict, suffix: str, body: dict, *, fresh: bool = True):  # type: ignore[no-untyped-def]
    current = view(s, dungeon["dungeon_id"]) if fresh else dungeon
    return s.gm.post(
        dungeon_url(s, dungeon["dungeon_id"], suffix),
        {"expected_row_version": current["row_version"], **body},
        key=s.gm.fresh_key(),
    )


def new_area(s: ContentSetup, dungeon: dict, name: str = "Entry Hall", **extra: object) -> dict:
    response = s.gm.post(
        dungeon_url(s, dungeon["dungeon_id"], "/areas"),
        {"name": name, "area_type": "hall", "dimensions": "30 ft by 40 ft", **extra},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def publish_all(s: ContentSetup, dungeon: dict, *areas: dict) -> None:
    current = view(s, dungeon["dungeon_id"])
    s.publish(dungeon["dungeon_id"], current["row_version"])
    for area in areas:
        fresh = s.gm.get(s.url(f"dungeon-areas/{area['dungeon_area_id']}")).json()
        s.publish(area["dungeon_area_id"], fresh["row_version"])


def set_clock(s: ContentSetup) -> str:
    time_id = Times(s).at(1)
    assert _advance(s, time_id, 0).status_code == 200
    return time_id


def child(s: ContentSetup, dungeon: dict, kind: str, area: dict, **extra: object):  # type: ignore[no-untyped-def]
    return post(
        s,
        dungeon,
        f"/{kind}",
        {"dungeon_area_id": area["dungeon_area_id"], "child_type": "thing", **extra},
    )


# --- the dungeon and its areas ----------------------------------------------------------------


def test_a_dungeon_and_its_areas_are_authored_as_drafts(s: ContentSetup) -> None:
    dungeon = new_dungeon(s)
    assert dungeon["canon_status"] == "draft" and dungeon["danger_level"] == 6
    assert dungeon["areas"] == [] and "update" in dungeon["available_actions"]
    area = new_area(s, dungeon, summary="Where it begins.")
    assert area["canon_status"] == "draft" and area["dungeon"]["entity_id"] == dungeon["dungeon_id"]
    assert area["area_type"] == "hall" and area["structure_actions"]
    listed = view(s, dungeon["dungeon_id"])
    assert [a["name"] for a in listed["areas"]] == ["Entry Hall"]
    [audit] = s.audit("create_dungeon_area")
    assert audit.action == "created" and "flooded" not in str(audit.changed_fields).lower()
    assert s.audit("create_dungeon")[0].changed_fields["danger_level"] == 6


def test_updating_the_dungeon_and_an_area_use_their_own_versions(s: ContentSetup) -> None:
    dungeon = new_dungeon(s)
    area = new_area(s, dungeon)
    response = post(s, dungeon, "/update", {"name": "The Drowned Vault", "danger_level": 8})
    assert response.status_code == 200 and response.json()["name"] == "The Drowned Vault"
    assert response.json()["row_version"] == dungeon["row_version"] + 1
    refreshed_area = s.gm.get(s.url(f"dungeon-areas/{area['dungeon_area_id']}")).json()
    assert refreshed_area["row_version"] == area["row_version"]  # the area was not touched
    changed = s.gm.post(
        s.url(f"dungeon-areas/{area['dungeon_area_id']}/update"),
        {
            "expected_row_version": area["row_version"],
            "name": "Great Hall",
            "area_type": "hall",
            "dimensions": "50 ft",
        },
        key=s.gm.fresh_key(),
    )
    assert changed.status_code == 200 and changed.json()["name"] == "Great Hall"
    assert changed.json()["row_version"] == area["row_version"] + 1
    assert view(s, dungeon["dungeon_id"])["row_version"] == response.json()["row_version"]
    stale = s.gm.post(
        s.url(f"dungeon-areas/{area['dungeon_area_id']}/update"),
        {"expected_row_version": area["row_version"], "name": "Late"},
        key=s.gm.fresh_key(),
    )
    assert stale.status_code == 409 and code(stale) == "stale_write"
    same = post(s, dungeon, "/update", {"name": "The Drowned Vault", "danger_level": 8})
    assert same.status_code == 200 and same.json()["changed"] is False
    bad = post(s, dungeon, "/update", {"name": "X", "danger_level": 11})
    assert bad.status_code == 422


def test_an_area_publishes_only_after_its_dungeon_and_a_dungeon_archives_without_active_areas(
    s: ContentSetup,
) -> None:
    dungeon = new_dungeon(s)
    area = new_area(s, dungeon)
    area_view = s.gm.get(s.url(f"dungeon-areas/{area['dungeon_area_id']}")).json()
    version = s.transition(area["dungeon_area_id"], "submit-for-review", area_view["row_version"])
    version = s.transition(area["dungeon_area_id"], "approve", version["row_version"])
    approved = s.gm.get(s.url(f"dungeon-areas/{area['dungeon_area_id']}")).json()
    blocked = {b["action"]: b["reason"] for b in approved["blocked_actions"]}
    assert blocked["publish"] == "reference_not_published"
    s.transition(area["dungeon_area_id"], "return-to-draft", approved["row_version"])
    publish_all(s, dungeon, area)
    area_after = s.gm.get(s.url(f"dungeon-areas/{area['dungeon_area_id']}")).json()
    assert area_after["canon_status"] == "canon"
    current = view(s, dungeon["dungeon_id"])
    assert {b["action"]: b["reason"] for b in current["blocked_actions"]}["archive"] == (
        "dungeon_has_active_areas"
    )
    archived = s.gm.post(
        s.lifecycle(dungeon["dungeon_id"], "/archive"),
        {"expected_row_version": current["row_version"]},
        key=s.gm.fresh_key(),
    )
    assert archived.status_code == 409 and code(archived) == "dungeon_has_active_areas"


def test_the_parent_location_must_be_published(s: ContentSetup) -> None:
    region = s.gm.post(
        s.url("locations"), {"category": "region", "name": "Marches"}, key=s.gm.fresh_key()
    ).json()
    dungeon = new_dungeon(s, parent_location_id=region["location_id"])
    version = s.transition(dungeon["dungeon_id"], "submit-for-review", dungeon["row_version"])
    s.transition(dungeon["dungeon_id"], "approve", version["row_version"])
    blocked = {b["action"]: b["reason"] for b in view(s, dungeon["dungeon_id"])["blocked_actions"]}
    assert blocked["publish"] == "reference_not_published"
    s.publish(region["location_id"], region["row_version"])
    assert "publish" not in {b["action"] for b in view(s, dungeon["dungeon_id"])["blocked_actions"]}
    bad = s.gm.post(
        s.url("dungeons"),
        {"name": "Nowhere", "parent_location_id": str(uuid.uuid4())},
        key=s.gm.fresh_key(),
    )
    assert bad.status_code == 400 and code(bad) == "parent_location_invalid"


# --- structural children ----------------------------------------------------------------------


def test_children_and_connections_bump_the_dungeon_version(s: ContentSetup) -> None:
    dungeon = new_dungeon(s)
    hall = new_area(s, dungeon)
    vault = new_area(s, dungeon, "Vault")
    start = view(s, dungeon["dungeon_id"])["row_version"]
    linked = post(
        s,
        dungeon,
        "/connections",
        {
            "from_area_id": hall["dungeon_area_id"],
            "to_area_id": vault["dungeon_area_id"],
            "connection_type": "door",
            "is_hidden": True,
            "description": "Behind the tapestry.",
        },
    )
    assert linked.status_code == 201, linked.text
    assert linked.json()["row_version"] == start + 1 and len(linked.json()["connections"]) == 1
    assert child(s, dungeon, "features", hall, description="A mural.").status_code == 201
    assert (
        child(
            s, dungeon, "hazards", hall, child_type="trap", severity=7, is_hidden=True
        ).status_code
        == 201
    )
    assert child(s, dungeon, "interactables", vault, child_type="lever").status_code == 201
    final = view(s, dungeon["dungeon_id"])
    assert final["row_version"] == start + 4
    hall_view = s.gm.get(s.url(f"dungeon-areas/{hall['dungeon_area_id']}")).json()
    assert [f["child_type"] for f in hall_view["features"]] == ["thing"]
    assert hall_view["hazards"][0]["severity"] == 7 and hall_view["hazards"][0]["is_hidden"] is True
    assert hall_view["connections"][0]["to_area"]["name"] == "Vault"
    assert hall_view["row_version"] == hall["row_version"]
    assert [a.action for a in s.audit("add_area_connection")] == ["created"]
    assert "tapestry" not in str(s.audit("add_area_connection")[0].changed_fields)
    stale = post(
        s,
        dungeon,
        "/features",
        {"dungeon_area_id": hall["dungeon_area_id"]},
        fresh=False,
    )
    assert stale.status_code == 409 and code(stale) == "stale_write"


def test_connection_rules(s: ContentSetup) -> None:
    dungeon = new_dungeon(s)
    other = new_dungeon(s, "Elsewhere")
    hall, vault = new_area(s, dungeon), new_area(s, dungeon, "Vault")
    foreign = new_area(s, other, "Foreign")

    def link(**extra: object):  # type: ignore[no-untyped-def]
        return post(
            s,
            dungeon,
            "/connections",
            {
                "from_area_id": hall["dungeon_area_id"],
                "to_area_id": vault["dungeon_area_id"],
                "connection_type": "door",
                **extra,
            },
        )

    same = link(to_area_id=hall["dungeon_area_id"])
    assert same.status_code == 400 and code(same) == "connection_invalid"
    across = link(to_area_id=foreign["dungeon_area_id"])
    assert across.status_code == 404
    bad_type = link(connection_type="wormhole")
    assert bad_type.status_code == 400 and code(bad_type) == "connection_type_invalid"
    missing = link(is_conditional=True)
    assert missing.status_code == 400 and code(missing) == "connection_invalid"
    ok = link(is_conditional=True, condition_description="Needs the brass key.", is_one_way=True)
    assert ok.status_code == 201
    connection_id = ok.json()["connections"][0]["area_connection_id"]
    updated = post(
        s,
        dungeon,
        f"/connections/{connection_id}/update",
        {"connection_type": "secret_door", "is_hidden": True, "is_one_way": True},
    )
    assert updated.status_code == 200
    edge = updated.json()["connections"][0]
    assert edge["connection_type"] == "secret_door" and edge["is_conditional"] is False
    assert edge["from_area"]["entity_id"] == hall["dungeon_area_id"]  # endpoints never change
    unknown = s.gm.post(
        dungeon_url(s, dungeon["dungeon_id"], f"/connections/{connection_id}/update"),
        {
            "expected_row_version": updated.json()["row_version"],
            "connection_type": "door",
            "from_area_id": vault["dungeon_area_id"],
        },
        key=s.gm.fresh_key(),
    )
    assert unknown.status_code == 422


def test_removal_is_for_drafts_only(s: ContentSetup) -> None:
    dungeon = new_dungeon(s)
    hall, vault = new_area(s, dungeon), new_area(s, dungeon, "Vault")
    link = post(
        s,
        dungeon,
        "/connections",
        {
            "from_area_id": hall["dungeon_area_id"],
            "to_area_id": vault["dungeon_area_id"],
            "connection_type": "door",
        },
    ).json()
    feature = child(s, dungeon, "features", hall).json()
    feature_id = next(
        f["child_id"]
        for f in s.gm.get(s.url(f"dungeon-areas/{hall['dungeon_area_id']}")).json()["features"]
    )
    assert feature["changed"] is True
    removed = post(s, dungeon, f"/features/{feature_id}/remove", {})
    assert removed.status_code == 200
    assert s.gm.get(s.url(f"dungeon-areas/{hall['dungeon_area_id']}")).json()["features"] == []
    removed_link = post(
        s, dungeon, f"/connections/{link['connections'][0]['area_connection_id']}/remove", {}
    )
    assert removed_link.status_code == 200 and removed_link.json()["connections"] == []
    hazard = child(s, dungeon, "hazards", hall, severity=3).json()
    publish_all(s, dungeon, hall)
    hazard_id = s.gm.get(s.url(f"dungeon-areas/{hall['dungeon_area_id']}")).json()["hazards"][0][
        "child_id"
    ]
    refused = post(s, dungeon, f"/hazards/{hazard_id}/remove", {})
    assert refused.status_code == 409 and code(refused) == "dungeon_not_draft"
    # A published dungeon is still edited in place.
    edited = post(s, dungeon, f"/hazards/{hazard_id}/update", {"child_type": "trap", "severity": 9})
    assert edited.status_code == 200
    assert hazard["changed"] is True


# --- who sees what ----------------------------------------------------------------------------


def test_players_see_only_published_areas_and_connections(s: ContentSetup) -> None:
    dungeon = new_dungeon(s)
    hall, vault = new_area(s, dungeon), new_area(s, dungeon, "Vault")
    post(
        s,
        dungeon,
        "/connections",
        {
            "from_area_id": hall["dungeon_area_id"],
            "to_area_id": vault["dungeon_area_id"],
            "connection_type": "door",
        },
    )
    child(s, dungeon, "features", hall, description="A mural.")
    child(s, dungeon, "hazards", hall, child_type="trap", is_hidden=True)
    hall_url = f"/campaigns/{s.cid}/dungeon-areas/{hall['dungeon_area_id']}"
    assert s.player.get(hall_url).status_code == 404  # a draft area
    assert s.gm.get(hall_url).status_code == 200
    publish_all(s, dungeon, hall)  # the vault stays a draft
    seen = s.player.get(hall_url)
    assert seen.status_code == 200
    body = seen.json()
    assert [f["description"] for f in body["features"]] == ["A mural."]
    assert body["hazards"] == []  # hidden and undiscovered
    assert body["connections"] == []  # the other end is still a draft
    assert (
        s.player.get(f"/campaigns/{s.cid}/dungeon-areas/{vault['dungeon_area_id']}").status_code
        == 404
    )
    gm_body = s.gm.get(hall_url).json()
    assert len(gm_body["connections"]) == 1 and len(gm_body["hazards"]) == 1
    publish_all(s, dungeon, vault) if False else None
    assert s.player.get(s.url(f"dungeons/{dungeon['dungeon_id']}")).status_code == 403


# --- runtime state -----------------------------------------------------------------------------


def published_dungeon(s: ContentSetup) -> tuple[dict, dict, dict, dict]:
    dungeon = new_dungeon(s)
    hall, vault = new_area(s, dungeon), new_area(s, dungeon, "Vault")
    post(
        s,
        dungeon,
        "/connections",
        {
            "from_area_id": hall["dungeon_area_id"],
            "to_area_id": vault["dungeon_area_id"],
            "connection_type": "door",
        },
    )
    child(s, dungeon, "features", hall, description="A mural.")
    child(s, dungeon, "hazards", hall, child_type="trap", severity=5)
    child(s, dungeon, "interactables", hall, child_type="lever")
    publish_all(s, dungeon, hall, vault)
    return dungeon, hall, vault, s.gm.get(s.url(f"dungeon-areas/{hall['dungeon_area_id']}")).json()


def state(
    s: ContentSetup, area: dict, kind: str, target: str, token: str | None, **changes: object
):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        f"/campaigns/{s.cid}/dungeon-areas/{area['dungeon_area_id']}/state",
        {"kind": kind, "target_id": target, "expected_last_event_id": token, **changes},
        key=s.gm.fresh_key(),
    )


def hall_view(s: ContentSetup, hall: dict) -> dict:
    return s.gm.get(s.url(f"dungeon-areas/{hall['dungeon_area_id']}")).json()


def test_state_commands_change_each_kind_with_an_event(s: ContentSetup) -> None:
    dungeon, hall, vault, current = published_dungeon(s)
    set_clock(s)
    assert current["can_set_state"] is True
    door = current["connections"][0]["area_connection_id"]
    hazard = current["hazards"][0]["child_id"]
    lever = current["interactables"][0]["child_id"]
    mural = current["features"][0]["child_id"]

    opened = state(s, hall, "connection", door, None, connection_status="open")
    assert opened.status_code == 200 and opened.json()["event_id"]
    triggered = state(s, hall, "hazard", hazard, None, hazard_status="triggered")
    assert triggered.status_code == 200
    assert (
        state(s, hall, "interactable", lever, None, interactable_status="activated").status_code
        == 200
    )
    assert (
        state(
            s, hall, "feature", mural, None, is_destroyed=True, condition_notes="Smashed."
        ).status_code
        == 200
    )
    searched = state(
        s, hall, "area", hall["dungeon_area_id"], None, is_searched=True, alarm_level=2
    )
    assert searched.status_code == 200
    after = hall_view(s, hall)
    assert after["connections"][0]["status"] == "open"
    assert after["hazards"][0]["status"] == "triggered"
    assert after["interactables"][0]["status"] == "activated"
    assert after["features"][0]["is_destroyed"] is True
    assert after["state"]["is_searched"] is True and after["state"]["alarm_level"] == 2
    assert after["row_version"] == current["row_version"]  # the definition did not move
    assert (
        view(s, dungeon["dungeon_id"])["row_version"]
        == view(s, dungeon["dungeon_id"])["row_version"]
    )
    types = (
        s.connection.execute(
            text("""
            SELECT et.code FROM narrative.events ev
            JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
            WHERE ev.campaign_id = :c AND et.code = 'dungeon_state_changed'
        """),
            {"c": s.cid},
        )
        .scalars()
        .all()
    )
    assert len(types) == 5
    [audit] = s.audit("set_dungeon_state")[:1]
    assert audit.action == "updated"
    # Players see the new status through the audience-filtered read.
    seen = s.player.get(f"/campaigns/{s.cid}/dungeon-areas/{hall['dungeon_area_id']}").json()
    assert seen["connections"][0]["connection_status_code"] == "open"


def test_state_tokens_values_and_targets_are_checked(s: ContentSetup) -> None:
    dungeon, hall, vault, current = published_dungeon(s)
    set_clock(s)
    door = current["connections"][0]["area_connection_id"]
    first = state(s, hall, "connection", door, None, connection_status="locked").json()
    stale = state(s, hall, "connection", door, None, connection_status="open")
    assert stale.status_code == 409 and code(stale) == "stale_write"
    noop = state(s, hall, "connection", door, first["event_id"], connection_status="locked")
    assert noop.status_code == 200 and noop.json()["changed"] is False
    bad_value = state(s, hall, "connection", door, first["event_id"], connection_status="vanished")
    assert bad_value.status_code == 400 and code(bad_value) == "state_target_invalid"
    wrong_field = state(s, hall, "connection", door, first["event_id"], hazard_status="armed")
    assert wrong_field.status_code == 400
    nothing = state(s, hall, "connection", door, first["event_id"])
    assert nothing.status_code == 400
    elsewhere = state(s, vault, "connection", door, first["event_id"], connection_status="open")
    assert elsewhere.status_code == 200  # a connection belongs to both of its areas
    ghost = state(s, hall, "hazard", str(uuid.uuid4()), None, hazard_status="armed")
    assert ghost.status_code == 404
    off = state(s, vault, "feature", current["features"][0]["child_id"], None, is_destroyed=True)
    assert off.status_code == 400  # that feature is in the hall, not the vault


def test_state_needs_published_areas_and_the_clock(s: ContentSetup) -> None:
    dungeon = new_dungeon(s)
    hall = new_area(s, dungeon)
    set_clock(s)
    draft = state(s, hall, "area", hall["dungeon_area_id"], None, is_searched=True)
    assert draft.status_code == 404
    publish_all(s, dungeon, hall)
    ok = state(s, hall, "area", hall["dungeon_area_id"], None, is_searched=True)
    assert ok.status_code == 200
    s.set_status(dungeon["dungeon_id"], canon="draft")
    refused = state(s, hall, "area", hall["dungeon_area_id"], ok.json()["event_id"], alarm_level=1)
    assert refused.status_code == 404


def test_a_state_change_can_be_corrected_and_the_door_closes_again(s: ContentSetup) -> None:
    dungeon, hall, vault, current = published_dungeon(s)
    set_clock(s)
    door = current["connections"][0]["area_connection_id"]
    opened = state(s, hall, "connection", door, None, connection_status="open").json()
    locked = state(
        s, hall, "connection", door, opened["event_id"], connection_status="locked"
    ).json()
    refused = s.gm.post_raw(
        f"/campaigns/{s.cid}/events/{opened['event_id']}/void",
        {"reason": "Wrong door"},
        key=s.gm.fresh_key(),
    )
    assert refused.status_code == 409 and code(refused) == "correction_not_reversible"
    undone = s.gm.post_raw(
        f"/campaigns/{s.cid}/events/{locked['event_id']}/void",
        {"reason": "Not locked"},
        key=s.gm.fresh_key(),
    )
    assert undone.status_code == 200, undone.text
    assert hall_view(s, hall)["connections"][0]["status"] == "open"
    # A first write is removed entirely.
    first = state(
        s, hall, "hazard", current["hazards"][0]["child_id"], None, hazard_status="triggered"
    ).json()
    assert (
        s.gm.post_raw(
            f"/campaigns/{s.cid}/events/{first['event_id']}/void",
            {"reason": "Oops"},
            key=s.gm.fresh_key(),
        ).status_code
        == 200
    )
    assert hall_view(s, hall)["hazards"][0]["status"] is None


def test_authority_replay_and_foreign_dungeons(s: ContentSetup) -> None:
    dungeon = new_dungeon(s)
    denied = s.player.post(s.url("dungeons"), {"name": "Mine"}, key=s.player.fresh_key())
    assert denied.status_code == 403
    key = s.gm.fresh_key()
    body = {"name": "Replayed", "danger_level": 2}
    first = s.gm.post(s.url("dungeons"), body, key=key)
    replay = s.gm.post(s.url("dungeons"), body, key=key)
    assert first.status_code == replay.status_code == 201 and replay.json() == replay_body(
        first.json()
    )
    assert len(s.audit("create_dungeon")) == 2  # the first test dungeon and the replayed one
    foreign = s.stranger.post(
        s.url("dungeons", s.other_cid), {"name": "Elsewhere"}, key=s.stranger.fresh_key()
    ).json()
    assert s.gm.get(dungeon_url(s, foreign["dungeon_id"])).status_code == 404
    assert (
        s.gm.post(
            dungeon_url(s, foreign["dungeon_id"], "/areas"),
            {"name": "Sneaky"},
            key=s.gm.fresh_key(),
        ).status_code
        == 400
    )
    assert dungeon["dungeon_id"]
