"""Encounter operation: start, turns, end and abort (checkpoint 15.3B-2b)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.domain.data_classification import replay_body
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_encounter_preparation import add, base, code, prepare, view
from tests.database.test_api_event_corrections import character_with_hp
from tests.database.test_api_routes_travel import clock_at, pc
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


def make(s: ContentSetup, *characters: str) -> str:
    session = new_session(s, title="Session 1")
    encounter = prepare(s, session["session_id"], summary="Fight").json()["encounter_id"]
    for character in characters:
        assert add(s, encounter, character).status_code == 201
    return str(encounter)


def start(s: ContentSetup, encounter: str, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(base(s, f"/{encounter}/start"), extra, key=s.gm.fresh_key())


def turn(s: ContentSetup, encounter: str, actor: str, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        base(s, f"/{encounter}/turns"), {"actor_entity_id": actor, **extra}, key=s.gm.fresh_key()
    )


def finish(s: ContentSetup, encounter: str, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(base(s, f"/{encounter}/end"), extra, key=s.gm.fresh_key())


def abort(s: ContentSetup, encounter: str, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(base(s, f"/{encounter}/abort"), extra, key=s.gm.fresh_key())


def events_of(s: ContentSetup, encounter: str) -> list[str]:
    return sorted(
        str(r[0])
        for r in s.connection.execute(
            text("""
                SELECT e.canonical_name FROM narrative.event_causes c
                JOIN core.entities e ON e.entity_id = c.event_id
                WHERE c.cause_encounter_id = :e
            """),
            {"e": encounter},
        )
    )


def hp(s: ContentSetup, character: str) -> int:
    return int(
        s.connection.execute(
            text("SELECT current_hit_points FROM campaign.character_state WHERE character_id = :c"),
            {"c": character},
        ).scalar()
        or 0
    )


def test_starting_needs_participants_and_records_an_event(s: ContentSetup) -> None:
    empty = make(s)
    refused = start(s, empty)
    assert refused.status_code == 409 and code(refused) == "encounter_not_ready"
    encounter = make(s, pc(s, "Aldric"), pc(s, "Bryn"))
    started = start(s, encounter, note="Steel is drawn")
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["status"] == "active" and body["current_round"] == 1 and body["event_id"]
    assert events_of(s, encounter) == ["Encounter started"]
    again = start(s, encounter)
    assert again.status_code == 409 and code(again) == "encounter_not_pending"
    (audit,) = s.audit("start_encounter")
    assert audit.action == "updated" and "Steel" not in str(audit.changed_fields)


def test_an_unpublished_participant_blocks_the_start(s: ContentSetup) -> None:
    aldric = pc(s, "Aldric")
    encounter = make(s, aldric)
    s.set_status(aldric, lifecycle="archived")
    refused = start(s, encounter)
    assert refused.status_code in (404, 409), refused.text
    assert view(s, encounter)["status"] == "pending"


def test_turns_default_to_the_current_round_and_the_next_turn(s: ContentSetup) -> None:
    attacker, victim = pc(s, "Aldric"), character_with_hp(s, 20)
    encounter = make(s, attacker, victim)
    start(s, encounter)
    first = turn(s, encounter, attacker, target_entity_id=victim, damage_amount=7, hit=True)
    assert first.status_code == 201, first.text
    assert first.json()["previous_hit_points"] == 20 and first.json()["new_hit_points"] == 13
    assert hp(s, victim) == 13
    miss = turn(s, encounter, victim, target_entity_id=attacker, damage_amount=5, hit=False)
    assert miss.status_code == 201 and miss.json()["event_id"] is None
    again = turn(s, encounter, attacker)
    assert again.status_code == 409  # one turn each per round
    shown = view(s, encounter)
    assert [t["turn_order"] for t in shown["rounds"][0]["turns"]] == [0, 1]
    assert shown["rounds"][0]["turns"][0]["actor_name"] == "Aldric"
    assert shown["rounds"][0]["turns"][0]["target_name"] is not None
    big = turn(
        s, encounter, attacker, round_number=2, target_entity_id=victim, damage_amount=99, hit=True
    )
    assert big.json()["new_hit_points"] == 0 and hp(s, victim) == 0
    after = view(s, encounter)
    assert after["current_round"] == 2 and [r["round_number"] for r in after["rounds"]] == [1, 2]
    next_turn = turn(s, encounter, victim)
    assert next_turn.status_code == 201
    assert [t["turn_order"] for t in view(s, encounter)["rounds"][1]["turns"]] == [0, 1]
    victim_row = next(p for p in after["participants"] if p["participant_entity_id"] == victim)
    assert victim_row["current_hit_points"] == 0 and victim_row["maximum_hit_points"] == 20


def test_only_participants_take_turns_and_only_while_active(s: ContentSetup) -> None:
    aldric, outsider = pc(s, "Aldric"), pc(s, "Outsider")
    encounter = make(s, aldric)
    pending = turn(s, encounter, aldric)
    assert pending.status_code == 409
    start(s, encounter)
    stranger = turn(s, encounter, outsider)
    assert stranger.status_code in (400, 404, 409, 500)
    assert stranger.status_code != 201
    assert view(s, encounter)["rounds"] == []


def test_ending_records_outcomes_and_the_end_event(s: ContentSetup) -> None:
    aldric, bryn = pc(s, "Aldric"), pc(s, "Bryn")
    encounter = make(s, aldric, bryn)
    start(s, encounter)
    ended = finish(
        s,
        encounter,
        outcomes=[{"participant_entity_id": bryn, "outcome": "surrendered"}],
        summary="Bryn yields",
    )
    assert ended.status_code == 200, ended.text
    shown = view(s, encounter)
    assert (
        shown["status"] == "completed" and shown["resulting_event_id"] == ended.json()["event_id"]
    )
    outcomes = {p["name"]: p["outcome"] for p in shown["participants"]}
    assert outcomes == {"Aldric": None, "Bryn": "surrendered"}
    assert events_of(s, encounter) == ["Encounter ended", "Encounter started"]
    late = turn(s, encounter, aldric)
    assert late.status_code == 409
    again = finish(s, encounter)
    assert again.status_code == 409


def test_aborting_a_pending_encounter_records_nothing(s: ContentSetup) -> None:
    encounter = make(s, pc(s, "Aldric"))
    aborted = abort(s, encounter)
    assert aborted.status_code == 200, aborted.text
    assert aborted.json()["status"] == "aborted" and aborted.json()["event_id"] is None
    assert events_of(s, encounter) == []
    assert start(s, encounter).status_code == 409
    assert abort(s, encounter).status_code == 409


def test_aborting_an_active_encounter_records_an_event_and_keeps_the_turns(s: ContentSetup) -> None:
    aldric = pc(s, "Aldric")
    encounter = make(s, aldric)
    start(s, encounter)
    assert turn(s, encounter, aldric).status_code == 201
    aborted = abort(s, encounter, note="The party flees")
    assert aborted.status_code == 200, aborted.text
    shown = view(s, encounter)
    assert (
        shown["status"] == "aborted" and shown["resulting_event_id"] == aborted.json()["event_id"]
    )
    assert len(shown["rounds"][0]["turns"]) == 1
    assert events_of(s, encounter) == ["Encounter aborted", "Encounter started"]
    again = abort(s, encounter)
    assert again.status_code == 409 and code(again) == "encounter_finished"


def test_players_and_other_worlds_cannot_operate_an_encounter(s: ContentSetup) -> None:
    aldric = pc(s, "Aldric")
    encounter = make(s, aldric)
    assert (
        s.player.post_raw(base(s, f"/{encounter}/start"), {}, key=s.player.fresh_key()).status_code
        == 403
    )
    assert (
        s.stranger.post_raw(
            base(s, f"/{encounter}/start", s.other_cid), {}, key=s.stranger.fresh_key()
        ).status_code
        == 404
    )
    assert view(s, encounter)["status"] == "pending"


def test_replay_of_a_turn_and_a_start_records_one(s: ContentSetup) -> None:
    aldric = pc(s, "Aldric")
    encounter = make(s, aldric)
    key = s.gm.fresh_key()
    first = s.gm.post_raw(base(s, f"/{encounter}/start"), {}, key=key)
    replay = s.gm.post_raw(base(s, f"/{encounter}/start"), {}, key=key)
    assert first.status_code == replay.status_code == 200 and replay.json() == replay_body(
        first.json()
    )
    assert events_of(s, encounter) == ["Encounter started"]
    turn_key = s.gm.fresh_key()
    body = {"actor_entity_id": aldric}
    one = s.gm.post_raw(base(s, f"/{encounter}/turns"), body, key=turn_key)
    two = s.gm.post_raw(base(s, f"/{encounter}/turns"), body, key=turn_key)
    assert one.status_code == two.status_code == 201 and two.json() == replay_body(one.json())
    assert len(view(s, encounter)["rounds"][0]["turns"]) == 1
    assert len(s.audit("resolve_combat_turn")) == 1
