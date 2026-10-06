"""Encounter preparation (checkpoint 15.3B-2a, decision D-23)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.domain.data_classification import replay_body
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_routes_travel import clock_at, pc, place
from tests.database.test_api_session_play import new_session

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    setup = ContentSetup(harness, db_connection)
    clock_at(setup, 5)
    return setup


def code(response) -> str:  # type: ignore[no-untyped-def]
    return str(response.json()["error"]["code"])


def base(s: ContentSetup, suffix: str = "", cid: str | None = None) -> str:
    return f"/campaigns/{cid or s.cid}/encounters{suffix}"


def prepare(s: ContentSetup, session_id: str, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        base(s, "/prepare"), {"session_id": session_id, **extra}, key=s.gm.fresh_key()
    )


def add(s: ContentSetup, encounter_id: str, character: str, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        base(s, f"/{encounter_id}/participants"),
        {"participant_entity_id": character, **extra},
        key=s.gm.fresh_key(),
    )


def view(s: ContentSetup, encounter_id: str) -> dict:
    response = s.gm.get(s.url(f"encounters/{encounter_id}"))
    assert response.status_code == 200, response.text
    return dict(response.json())


def start_it(s: ContentSetup, encounter_id: str) -> None:
    """Move the encounter out of `pending` the way the existing command does."""
    s.connection.execute(
        text("UPDATE narrative.encounters SET status = 'active' WHERE encounter_id = :e"),
        {"e": encounter_id},
    )


def test_an_encounter_is_prepared_pending_in_a_session_at_the_campaign_time(
    s: ContentSetup,
) -> None:
    session = new_session(s, title="Session 1")
    town = place(s, "Stonebridge")
    made = prepare(s, session["session_id"], location_id=town, summary="  Ambush at the gate  ")
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["status"] == "pending" and body["can_prepare"] is True
    assert body["summary"] == "Ambush at the gate" and body["location_name"] == "Stonebridge"
    assert body["session_id"] == session["session_id"] and body["participants"] == []
    listed = s.gm.get(s.url("encounters"), session_id=session["session_id"]).json()["items"]
    assert [i["encounter_id"] for i in listed] == [body["encounter_id"]]
    (audit,) = s.audit("create_encounter")
    assert audit.action == "created" and "Ambush" not in str(audit.changed_fields)


def test_participants_are_published_characters_with_a_side_and_initiative(s: ContentSetup) -> None:
    session = new_session(s, title="Session 1")
    encounter = prepare(s, session["session_id"]).json()["encounter_id"]
    aldric, bryn, draft = pc(s, "Aldric"), pc(s, "Bryn"), pc(s, "Draft", publish=False)
    first = add(s, encounter, aldric, side="party", initiative=14)
    assert first.status_code == 201, first.text
    assert add(s, encounter, bryn, side="enemy").status_code == 201
    shown = view(s, encounter)["participants"]
    assert [(p["name"], p["side"], p["initiative"]) for p in shown] == [
        ("Aldric", "party", 14),
        ("Bryn", "enemy", None),
    ]
    again = add(s, encounter, aldric)
    assert again.status_code == 409 and code(again) == "encounter_participant_exists"
    for bad in (draft, str(uuid.uuid4()), place(s, "Stonebridge")):
        refused = add(s, encounter, bad)
        assert refused.status_code in (400, 404, 409), refused.text
    invalid_side = add(s, encounter, pc(s, "Cade"), side="villain")
    assert invalid_side.status_code in (400, 422)
    assert len(view(s, encounter)["participants"]) == 2


def test_participants_can_change_side_and_initiative_and_leave(s: ContentSetup) -> None:
    session = new_session(s, title="Session 1")
    encounter = prepare(s, session["session_id"]).json()["encounter_id"]
    added = add(s, encounter, pc(s, "Aldric")).json()
    participant = added["participants"][0]["encounter_participant_id"]
    url = base(s, f"/{encounter}/participants/{participant}")
    changed = s.gm.post_raw(
        url + "/update", {"side": "ally", "initiative": 20}, key=s.gm.fresh_key()
    )
    assert changed.status_code == 200 and changed.json()["participants"][0]["side"] == "ally"
    same = s.gm.post_raw(url + "/update", {"side": "ally", "initiative": 20}, key=s.gm.fresh_key())
    assert same.json()["changed"] is False
    removed = s.gm.post_raw(url + "/remove", {}, key=s.gm.fresh_key())
    assert removed.status_code == 200 and removed.json()["participants"] == []
    missing = s.gm.post_raw(url + "/remove", {}, key=s.gm.fresh_key())
    assert missing.status_code == 404


def test_the_place_and_summary_can_change_while_pending(s: ContentSetup) -> None:
    session = new_session(s, title="Session 1")
    encounter = prepare(s, session["session_id"], summary="Old").json()["encounter_id"]
    town = place(s, "Stonebridge")
    updated = s.gm.post_raw(
        base(s, f"/{encounter}/update"),
        {"location_id": town, "summary": "New"},
        key=s.gm.fresh_key(),
    )
    assert updated.status_code == 200 and updated.json()["location_name"] == "Stonebridge"
    assert updated.json()["summary"] == "New"


def test_nothing_changes_once_the_encounter_has_started(s: ContentSetup) -> None:
    session = new_session(s, title="Session 1")
    encounter = prepare(s, session["session_id"]).json()["encounter_id"]
    added = add(s, encounter, pc(s, "Aldric")).json()
    participant = added["participants"][0]["encounter_participant_id"]
    start_it(s, encounter)
    url = base(s, f"/{encounter}")
    attempts = [
        s.gm.post_raw(url + "/update", {"summary": "x"}, key=s.gm.fresh_key()),
        add(s, encounter, pc(s, "Bryn")),
        s.gm.post_raw(
            url + f"/participants/{participant}/update", {"side": "enemy"}, key=s.gm.fresh_key()
        ),
        s.gm.post_raw(url + f"/participants/{participant}/remove", {}, key=s.gm.fresh_key()),
    ]
    for response in attempts:
        assert response.status_code == 409 and code(response) == "encounter_not_pending"
    assert len(view(s, encounter)["participants"]) == 1


def test_the_session_must_belong_to_the_campaign_and_be_active(s: ContentSetup) -> None:
    session = new_session(s, title="Session 1")
    foreign = prepare(s, str(uuid.uuid4()))
    assert foreign.status_code in (400, 404)
    archived = s.gm.post_raw(
        f"/campaigns/{s.cid}/sessions/{session['session_id']}/archive",
        {"expected_row_version": session["row_version"]},
        key=s.gm.fresh_key(),
    )
    assert archived.status_code == 200, archived.text
    refused = prepare(s, session["session_id"])
    assert refused.status_code == 409 and code(refused) == "session_not_usable"


def test_players_and_other_worlds_cannot_prepare_or_read(s: ContentSetup) -> None:
    session = new_session(s, title="Session 1")
    encounter = prepare(s, session["session_id"]).json()["encounter_id"]
    assert (
        s.player.post_raw(
            base(s, "/prepare"), {"session_id": session["session_id"]}, key=s.player.fresh_key()
        ).status_code
        == 403
    )
    assert s.player.get(s.url(f"encounters/{encounter}")).status_code == 403
    assert s.stranger.get(s.url(f"encounters/{encounter}", s.other_cid)).status_code == 404
    assert (
        s.stranger.post_raw(
            base(s, f"/{encounter}/participants", s.other_cid),
            {"participant_entity_id": str(uuid.uuid4())},
            key=s.stranger.fresh_key(),
        ).status_code
        == 404
    )


def test_replay_returns_the_same_response_with_one_participant(s: ContentSetup) -> None:
    session = new_session(s, title="Session 1")
    encounter = prepare(s, session["session_id"]).json()["encounter_id"]
    aldric = pc(s, "Aldric")
    key = s.gm.fresh_key()
    url = base(s, f"/{encounter}/participants")
    first = s.gm.post_raw(url, {"participant_entity_id": aldric}, key=key)
    replay = s.gm.post_raw(url, {"participant_entity_id": aldric}, key=key)
    assert first.status_code == replay.status_code == 201 and replay.json() == replay_body(
        first.json()
    )
    assert len(view(s, encounter)["participants"]) == 1
    assert len(s.audit("add_encounter_participant")) == 1
