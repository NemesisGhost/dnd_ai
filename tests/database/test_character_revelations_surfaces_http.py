"""Revelation-only reads on four more discovery surfaces (P03-A A3b disclosure-test gaps).

The session roster, session travel, the encounter projection and Knowledge subjects all read the
shared discovery bundle, each with its own response shape. For a reader whose only path to a
character is a campaign revelation, each test drives the production routes and asserts that surface's
own projection:

- before any revelation, nothing about the character is present;
- an authorized revelation names the character (id and name) where that surface names characters,
  never opens it, and reveals nothing about a second, unrevealed character;
- a whole-character `campaign.view` deny or a raw `character.discover` deny removes every reference
  even while the revelation is live;
- revoking the revelation removes the references on the next request;
- discovery never permits character detail, sheet or inventory.

The owner GM creates and revokes the revelation (`reveal`/`unreveal`); the reader is the campaign's
plain player, who holds no relationship to any character.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times
from tests.database.test_api_event_explanations import deny_entity, grant
from tests.database.test_api_knowledge_authoring import create as create_claim
from tests.database.test_api_routes_travel import clock_at, pc, place
from tests.database.test_api_session_play import detail, new_session, post
from tests.database.test_api_session_travel import session_travel, started_session
from tests.database.test_character_revelations_surfaces import reveal, unreveal
from tests.factories import make_public_knowledge

pytestmark = pytest.mark.database

DENIES = ["campaign_view", "character_discover"]


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def apply_deny(s: ContentSetup, character: str, kind: str) -> None:
    if kind == "campaign_view":
        deny_entity(s, character)
    else:
        grant(s, "character.discover", character, "deny")


def assert_not_openable(s: ContentSetup, character: str) -> None:
    """Discovery is not access: the reader's character routes stay closed and say nothing."""
    for suffix in ("", "/sheet", "/builds", "/inventory"):
        response = s.player.get(f"/campaigns/{s.cid}/characters/{character}{suffix}")
        assert response.status_code in (403, 404), suffix
        assert "Aldric" not in response.text and character not in response.text, suffix


def assert_absent(body: object, *hidden: str) -> None:
    rendered = str(body)
    for item in hidden:
        assert item not in rendered, item


# --- session roster ---------------------------------------------------------------------------


def roster_session(s: ContentSetup) -> tuple[str, str, str]:
    sid = new_session(s, title="Roster")["session_id"]
    aldric, borin = pc(s, "Aldric"), pc(s, "Borin")
    for character in (aldric, borin):
        added = post(
            s,
            sid,
            "/participants",
            {"character_id": character, "participation_role": "player_character"},
        )
        assert added.status_code == 201, added.text
    return sid, aldric, borin


def roster(s: ContentSetup, sid: str) -> list[tuple[str, str, bool]]:
    body = detail(s, sid, who="player")
    return [
        (p["character_id"], p["character_name"], p["can_open_character"])
        for p in body["participants"]
    ]


def test_the_session_roster_names_a_revealed_participant_and_never_opens_it(
    s: ContentSetup,
) -> None:
    sid, aldric, borin = roster_session(s)
    assert roster(s, sid) == []
    assert_absent(detail(s, sid, who="player"), "Aldric", "Borin", aldric, borin)

    revelation = reveal(s, aldric)
    assert roster(s, sid) == [(aldric, "Aldric", False)]  # named; can_open_character is false
    assert_absent(detail(s, sid, who="player"), "Borin", borin, revelation)
    assert_not_openable(s, aldric)
    assert_not_openable(s, borin)
    gm = detail(s, sid)["participants"]
    assert {(p["character_name"], p["can_open_character"]) for p in gm} == {
        ("Aldric", True),
        ("Borin", True),
    }  # the editor view is unchanged

    unreveal(s, aldric, revelation)
    assert roster(s, sid) == []
    assert_absent(detail(s, sid, who="player"), "Aldric", "Borin", aldric, borin)


@pytest.mark.parametrize("deny", DENIES)
def test_a_deny_removes_a_revealed_participant_from_the_session_roster(
    s: ContentSetup, deny: str
) -> None:
    sid, aldric, borin = roster_session(s)
    reveal(s, aldric)
    assert roster(s, sid) == [(aldric, "Aldric", False)]
    apply_deny(s, aldric, deny)
    assert roster(s, sid) == []
    assert_absent(detail(s, sid, who="player"), "Aldric", "Borin", aldric, borin)
    assert [p["character_name"] for p in detail(s, sid)["participants"]] == ["Aldric", "Borin"]


# --- session travel ---------------------------------------------------------------------------


def travel_session(s: ContentSetup) -> tuple[str, str, str, str, str]:
    north, south = place(s, "Northmark"), place(s, "Southmark")
    aldric, borin = pc(s, "Aldric"), pc(s, "Borin")
    times = Times(s)
    sid = started_session(s, times)
    assert session_travel(s, sid, north, character_ids=[aldric, borin]).status_code == 200
    clock_at(s, 2, times)
    assert session_travel(s, sid, south, character_ids=[aldric, borin]).status_code == 200
    return sid, aldric, borin, north, south


def legs(s: ContentSetup, sid: str) -> list[list[tuple[str | None, str | None]]]:
    """Each travel entry's (traveler id, traveler name) legs, as the player reads them."""
    return [
        [(leg["traveler"]["entity_id"], leg["traveler"]["name"]) for leg in entry["legs"]]
        for entry in detail(s, sid, who="player")["travel"]
    ]


def test_session_travel_names_a_revealed_traveler_only_and_while_revealed(
    s: ContentSetup,
) -> None:
    sid, aldric, borin, north, south = travel_session(s)
    before = detail(s, sid, who="player")
    assert all(entry["legs"] == [] for entry in before["travel"])  # bare entries, no travelers
    assert_absent(before, "Aldric", "Borin", aldric, borin)

    revelation = reveal(s, aldric)
    assert legs(s, sid) == [[(aldric, "Aldric")], [(aldric, "Aldric")]]
    after = detail(s, sid, who="player")
    assert_absent(after, "Borin", borin, revelation)
    assert [leg["to"]["name"] for entry in after["travel"] for leg in entry["legs"]] == [
        "Northmark",
        "Southmark",
    ]  # places are ordinary world records; the traveler is the revealed part
    assert after["participants"] == []
    assert_not_openable(s, aldric)
    assert [len(entry["legs"]) for entry in detail(s, sid)["travel"]] == [2, 2]  # GM unchanged

    unreveal(s, aldric, revelation)
    assert all(entry["legs"] == [] for entry in detail(s, sid, who="player")["travel"])
    assert_absent(detail(s, sid, who="player"), "Aldric", "Borin", aldric, borin)


@pytest.mark.parametrize("deny", DENIES)
def test_a_deny_removes_a_revealed_traveler_from_session_travel(s: ContentSetup, deny: str) -> None:
    sid, aldric, borin, _, _ = travel_session(s)
    reveal(s, aldric)
    assert legs(s, sid) == [[(aldric, "Aldric")], [(aldric, "Aldric")]]
    apply_deny(s, aldric, deny)
    assert all(entry["legs"] == [] for entry in detail(s, sid, who="player")["travel"])
    assert_absent(detail(s, sid, who="player"), "Aldric", "Borin", aldric, borin)


def test_a_denied_place_is_unavailable_while_the_revealed_traveler_stays_named(
    s: ContentSetup,
) -> None:
    sid, aldric, borin, north, south = travel_session(s)
    reveal(s, aldric)
    deny_entity(s, south)
    last = detail(s, sid, who="player")["travel"][-1]["legs"][0]
    assert last["traveler"]["name"] == "Aldric"
    assert last["to"] == {"state": "unavailable", "entity_id": None, "name": None}
    assert last["from"]["name"] == "Northmark"
    assert_absent(detail(s, sid, who="player"), "Southmark", south, "Borin", borin)


# --- encounters -------------------------------------------------------------------------------


def start_encounter(s: ContentSetup, *entities: str) -> str:
    started = s.gm.post_raw(
        f"/campaigns/{s.cid}/encounters",
        {
            "world_time_id": Times(s).at(1),
            "participant_entity_ids": list(entities),
        },
        key=s.gm.fresh_key(),
    )
    assert started.status_code == 201, started.text
    return str(started.json()["encounter_id"])


def encounter_for(s: ContentSetup, encounter: str, who: str = "player") -> dict:
    actor = s.player if who == "player" else s.gm
    response = actor.get(f"/campaigns/{s.cid}/encounters/{encounter}")
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def encounter_with_turns(s: ContentSetup) -> tuple[str, str, str, dict[str, str]]:
    """Aldric and Borin fight; Aldric then Borin each take a turn. Returns the encounter id, both
    character ids and the turn ids by actor."""
    aldric, borin = pc(s, "Aldric"), pc(s, "Borin")
    encounter = start_encounter(s, aldric, borin)
    for order, (actor, target) in enumerate(((aldric, borin), (borin, aldric))):
        turn = s.gm.post_raw(
            f"/campaigns/{s.cid}/encounters/{encounter}/turns",
            {
                "round_number": 1,
                "turn_order": order,
                "actor_entity_id": actor,
                "world_time_id": Times(s).at(1),
                "action_kind": "attack",
                "target_entity_id": target,
                "hit": False,
            },
            key=s.gm.fresh_key(),
        )
        assert turn.status_code == 201, turn.text
    return encounter, aldric, borin, {}


def shown(body: dict) -> tuple[list[str], list[str]]:
    """The participant entity ids and the actor-participant ids of every turn in the projection."""
    participants = [p["participant_entity_id"] for p in body["participants"]]
    by_participant = {
        p["encounter_participant_id"]: p["participant_entity_id"] for p in body["participants"]
    }
    turns = [by_participant[t["participant_id"]] for r in body["rounds"] for t in r["turns"]]
    return participants, turns


def test_an_encounter_shows_a_revealed_participant_and_its_turns_only(s: ContentSetup) -> None:
    encounter, aldric, borin, _ = encounter_with_turns(s)
    before = encounter_for(s, encounter)
    assert before["participants"] == [] and shown(before) == ([], [])
    assert_absent(before, aldric, borin, "Aldric", "Borin")

    revelation = reveal(s, aldric)
    body = encounter_for(s, encounter)
    assert shown(body) == ([aldric], [aldric])  # participant and its turn; Borin's turn is gone
    assert_absent(body, borin, "Borin", revelation)
    assert_not_openable(s, aldric)
    # The GM view is unchanged. Participant order is storage order, so compare sorted lists, which
    # still catch a duplicated or missing participant or turn.
    gm_participants, gm_turns = shown(encounter_for(s, encounter, "gm"))
    assert sorted(gm_participants) == sorted([aldric, borin])
    assert sorted(gm_turns) == sorted([aldric, borin])

    unreveal(s, aldric, revelation)
    after = encounter_for(s, encounter)
    assert shown(after) == ([], [])
    assert_absent(after, aldric, borin, "Aldric", "Borin")


@pytest.mark.parametrize("deny", DENIES)
def test_a_deny_removes_a_revealed_encounter_participant_and_its_turns(
    s: ContentSetup, deny: str
) -> None:
    encounter, aldric, borin, _ = encounter_with_turns(s)
    reveal(s, aldric)
    assert shown(encounter_for(s, encounter)) == ([aldric], [aldric])
    apply_deny(s, aldric, deny)
    body = encounter_for(s, encounter)
    assert shown(body) == ([], [])
    assert_absent(body, aldric, borin, "Aldric", "Borin")


# --- Knowledge subjects -----------------------------------------------------------------------


def published_claim(s: ContentSetup, subject: str) -> str:
    """A public, published claim whose subject is a character. The authoring route offers only
    non-character subjects, so the subject is set in the fixture, as the Knowledge browse tests do;
    every read below is the production route."""
    item = create_claim(s, "Aldric carries the key.", knowledge_type="rumor", sensitivity="public")
    s.publish(item["knowledge_item_id"], item["row_version"])
    s.connection.execute(
        text(
            "UPDATE knowledge.knowledge_items SET subject_entity_id = :s WHERE knowledge_item_id = :k"
        ),
        {"s": subject, "k": item["knowledge_item_id"]},
    )
    timeline = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": s.cid}
    ).scalar()
    make_public_knowledge(
        s.connection,
        timeline,
        uuid.UUID(item["knowledge_item_id"]),
        uuid.UUID(place(s, f"Hall of {subject[:6]}")),
    )
    return str(item["knowledge_item_id"])


def subjects(s: ContentSetup) -> dict[str, dict]:
    """Each claim the player can list, by id, with its `subject` and `subject_entity_id`."""
    response = s.player.get(f"/campaigns/{s.cid}/knowledge", view="public", limit=100)
    assert response.status_code == 200, response.text
    return {i["knowledge_item_id"]: i for i in response.json()["items"]}


def knowledge_responses(s: ContentSetup, *claims: str) -> list[str]:
    """The complete text of the player's Knowledge list and of each claim's detail response."""
    listing = s.player.get(f"/campaigns/{s.cid}/knowledge", view="public", limit=100)
    assert listing.status_code == 200, listing.text
    texts = [listing.text]
    for claim in claims:
        found = s.player.get(f"/campaigns/{s.cid}/knowledge/{claim}")
        assert found.status_code == 200, found.text  # readable claims stay available
        texts.append(found.text)
    return texts


def assert_ids_absent(texts: list[str], *ids: str) -> None:
    for body in texts:
        for item in ids:
            assert item not in body, item


def test_a_knowledge_claim_carries_a_revealed_subject_and_only_while_revealed(
    s: ContentSetup,
) -> None:
    aldric, borin = pc(s, "Aldric"), pc(s, "Borin")
    about_aldric, about_borin = published_claim(s, aldric), published_claim(s, borin)
    rows = subjects(s)
    assert about_aldric in rows and about_borin in rows  # the claims are readable; subjects are not
    for row in rows.values():
        assert row["subject"] is None and row["subject_entity_id"] is None
    assert_ids_absent(knowledge_responses(s, about_aldric, about_borin), aldric, borin)

    revelation = reveal(s, aldric)
    rows = subjects(s)
    assert rows[about_aldric]["subject_entity_id"] == aldric
    assert rows[about_aldric]["subject"]["entity_id"] == aldric
    assert rows[about_aldric]["subject"]["name"] == "Aldric"
    assert rows[about_borin]["subject"] is None and rows[about_borin]["subject_entity_id"] is None
    texts = knowledge_responses(s, about_aldric, about_borin)
    assert_ids_absent(texts, borin, revelation)  # complete list and detail responses
    assert aldric in texts[0] and aldric in texts[1]  # the revealed subject, list and detail
    detail_row = s.player.get(f"/campaigns/{s.cid}/knowledge/{about_aldric}").json()
    assert detail_row["subject"]["name"] == "Aldric"
    assert_not_openable(s, aldric)  # a labelled subject is not a character page

    unreveal(s, aldric, revelation)
    rows = subjects(s)
    assert about_aldric in rows and about_borin in rows
    assert rows[about_aldric]["subject"] is None and rows[about_aldric]["subject_entity_id"] is None
    assert_ids_absent(knowledge_responses(s, about_aldric, about_borin), aldric, borin, revelation)


@pytest.mark.parametrize("deny", DENIES)
def test_a_deny_removes_a_revealed_knowledge_subject(s: ContentSetup, deny: str) -> None:
    aldric, borin = pc(s, "Aldric"), pc(s, "Borin")
    about_aldric, about_borin = published_claim(s, aldric), published_claim(s, borin)
    revelation = reveal(s, aldric)
    assert subjects(s)[about_aldric]["subject"]["name"] == "Aldric"
    live = knowledge_responses(s, about_aldric, about_borin)
    assert_ids_absent(live, borin, revelation)
    apply_deny(s, aldric, deny)
    rows = subjects(s)
    assert about_aldric in rows and about_borin in rows  # the claims stay readable
    row = rows[about_aldric]
    assert row["subject"] is None and row["subject_entity_id"] is None
    after = knowledge_responses(s, about_aldric, about_borin)
    assert s.player.get(f"/campaigns/{s.cid}/knowledge/{about_aldric}").json()["subject"] is None
    assert_ids_absent(after, aldric, borin, revelation)
