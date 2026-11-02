"""Event explanations, read side (Phase 15 checkpoint CP-9a).

Fresh party join/leave, build activation and clock events are recorded through the production
routes and read back through every surface that carries an explanation: the world event page, the
GM event view, the session detail and the campaign summary. Audience cases cover a GM, a full-tier
reader, a summary-tier reader, a reader with no discovery of the character and a denied reader.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import (
    CALENDAR,
    Times,
    _advance,
    _branch_campaign,
    _clock,
)
from tests.database.test_api_character_builds import activate, create_build, initialize
from tests.database.test_api_party_members import add, end, members, new_party, published_pc
from tests.database.test_api_routes_travel import place
from tests.database.test_api_session_play import detail, new_session, post
from tests.database.test_api_session_travel import session_travel
from tests.factories import lookup_id, make_resource_grant

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def world_event(s: ContentSetup, actor: Actor, event_id: str):  # type: ignore[no-untyped-def]
    return actor.get(f"/campaigns/{s.cid}/world/events/{event_id}")


def explanation(s: ContentSetup, actor: Actor, event_id: str) -> dict:
    response = world_event(s, actor, event_id)
    assert response.status_code == 200, response.text
    found = response.json()["explanation"]
    assert found is not None
    return found


def player_membership(s: ContentSetup) -> uuid.UUID:
    value = s.connection.execute(
        text(
            "SELECT campaign_membership_id FROM security.campaign_memberships "
            "WHERE campaign_id = :c AND user_id = :u"
        ),
        {"c": s.cid, "u": s.player.user_id},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def grant(s: ContentSetup, capability: str, character: str, effect: str = "allow") -> None:
    make_resource_grant(
        s.connection,
        uuid.UUID(s.cid),
        lookup_id(s.connection, "security", "capabilities", "capability_id", capability),
        grantee_campaign_membership_id=player_membership(s),
        character_id=uuid.UUID(character),
        effect=effect,
    )


def deny_entity(s: ContentSetup, entity: str) -> None:
    make_resource_grant(
        s.connection,
        uuid.UUID(s.cid),
        lookup_id(s.connection, "security", "capabilities", "capability_id", "campaign.view"),
        grantee_campaign_membership_id=player_membership(s),
        entity_id=uuid.UUID(entity),
        effect="deny",
    )


def event_count(s: ContentSetup) -> int:
    return int(
        s.connection.execute(
            text("SELECT count(*) FROM narrative.events WHERE campaign_id = :c"), {"c": s.cid}
        ).scalar()
        or 0
    )


def join(s: ContentSetup, party: dict, character: str, time_id: str) -> str:
    response = add(s, party["party_id"], character, time_id)
    assert response.status_code == 201, response.text
    return str(response.json()["event_id"])


def start_clock(s: ContentSetup, times: Times, year: int = 1) -> str:
    time_id = times.at(year)
    assert _advance(s, time_id, 0).status_code == 200
    return time_id


def clock_version(s: ContentSetup) -> int:
    return int(_clock(s)["row_version"])


def two_builds(s: ContentSetup, character: str) -> tuple[str, str]:
    """A character with two builds: the first is the administrative baseline (no event); the
    second activation records the event under test. Returns (first, second) build ids."""
    assert initialize(s, character).status_code == 201
    first = create_build(s, character, label="Fighter 1")["character_build_id"]
    second = create_build(s, character, label="Fighter 2")["character_build_id"]
    assert activate(s, character, first, None).status_code == 200
    return str(first), str(second)


def activation_event(s: ContentSetup, character: str, first: str, second: str) -> str:
    response = activate(s, character, second, first)
    assert response.status_code == 200, response.text
    return str(response.json()["event_id"])


# --- party join and leave -------------------------------------------------------------------


def test_party_join_and_leave_name_the_character_the_party_and_both_times(s: ContentSetup) -> None:
    times = Times(s)
    start_clock(s, times)
    y1, y2 = times.at(1), times.at(2)
    party, aldric = new_party(s, "The Company"), published_pc(s, "Aldric")
    joined = join(s, party, aldric, y1)
    left = end(
        s, party["party_id"], members(s, party["party_id"])["members"][0]["party_membership_id"], y2
    )
    assert left.status_code == 200, left.text

    on_join = explanation(s, s.gm, joined)
    assert on_join["family"] == "party_member_joined"
    assert on_join["subject"] == {
        "state": "named",
        "kind": "character",
        "entity_id": aldric,
        "name": "Aldric",
        "openable": True,
    }
    assert on_join["party"]["name"] == "The Company" and on_join["party"]["openable"] is True
    assert "Year 1" in on_join["in_world_time"]
    assert on_join["recorded_at"] and on_join["in_world_time"] != on_join["recorded_at"]
    assert on_join["session"] is None and on_join["relations"] == []

    on_leave = explanation(s, s.gm, left.json()["event_id"])
    assert on_leave["family"] == "party_member_left"
    assert on_leave["subject"]["name"] == "Aldric" and on_leave["party"]["name"] == "The Company"
    assert "Year 2" in on_leave["in_world_time"]


def test_a_renamed_party_reads_with_its_current_name_and_an_archived_one_is_withheld(
    s: ContentSetup,
) -> None:
    times = Times(s)
    start_clock(s, times)
    party, aldric = new_party(s, "Old Name"), published_pc(s, "Aldric")
    joined = join(s, party, aldric, times.at(1))
    grant(s, "character.discover", aldric)
    renamed = s.gm.post_raw(
        f"/campaigns/{s.cid}/parties/{party['party_id']}/update",
        {"name": "New Name", "description": None, "expected_row_version": 2},
        key=s.gm.fresh_key(),
    )
    assert renamed.status_code == 200, renamed.text
    assert explanation(s, s.player, joined)["party"]["name"] == "New Name"
    archived = s.gm.post_raw(
        f"/campaigns/{s.cid}/parties/{party['party_id']}/archive",
        {"expected_row_version": 3},
        key=s.gm.fresh_key(),
    )
    assert archived.status_code == 200, archived.text
    for_player = explanation(s, s.player, joined)
    assert for_player["party"] == {
        "state": "unavailable",
        "kind": "party",
        "entity_id": None,
        "name": None,
        "openable": False,
    }
    assert "New Name" not in world_event(s, s.player, joined).text
    assert explanation(s, s.gm, joined)["party"]["name"] == "New Name"


def test_a_reader_who_cannot_discover_the_character_gets_no_name_id_or_link(
    s: ContentSetup,
) -> None:
    times = Times(s)
    start_clock(s, times)
    party, aldric = new_party(s), published_pc(s, "Aldric")
    joined = join(s, party, aldric, times.at(1))
    grant(s, "character.discover", aldric, "deny")
    response = world_event(s, s.player, joined)
    assert response.status_code == 200, response.text
    body = response.json()["explanation"]
    assert body["subject"] == {
        "state": "unavailable",
        "kind": "character",
        "entity_id": None,
        "name": None,
        "openable": False,
    }
    assert "Aldric" not in response.text and aldric not in response.text
    # Entity-level deny of the character is the same.
    deny_entity(s, aldric)
    assert aldric not in world_event(s, s.player, joined).text


def test_a_discoverable_character_is_named_but_opens_only_with_a_view_tier(
    s: ContentSetup,
) -> None:
    times = Times(s)
    start_clock(s, times)
    party, aldric = new_party(s), published_pc(s, "Aldric")
    joined = join(s, party, aldric, times.at(1))
    grant(s, "character.discover", aldric)
    discovered = explanation(s, s.player, joined)["subject"]
    assert discovered["name"] == "Aldric" and discovered["openable"] is False
    grant(s, "character.view_summary", aldric)
    assert explanation(s, s.player, joined)["subject"]["openable"] is True


# --- build activation -----------------------------------------------------------------------


def test_build_activation_shows_labels_to_the_gm_and_a_full_tier_reader_only(
    s: ContentSetup,
) -> None:
    times = Times(s)
    start_clock(s, times)
    aldric = published_pc(s, "Aldric")
    first, second = two_builds(s, aldric)
    event = activation_event(s, aldric, first, second)

    gm = explanation(s, s.gm, event)
    assert gm["family"] == "character_build_activated" and gm["build_detail"] == "full"
    assert gm["previous_build"]["name"] == "Fighter 1" and gm["new_build"]["name"] == "Fighter 2"
    assert gm["previous_build"]["entity_id"] is None  # builds expose labels, never ids
    assert gm["subject"]["name"] == "Aldric"

    grant(s, "character.view_summary", aldric)
    summary_tier = world_event(s, s.player, event)
    assert summary_tier.json()["explanation"]["build_detail"] == "generic"
    assert summary_tier.json()["explanation"]["previous_build"] is None
    assert "Fighter" not in summary_tier.text and first not in summary_tier.text
    assert summary_tier.json()["explanation"]["subject"]["name"] == "Aldric"

    grant(s, "character.view_full", aldric)
    full = explanation(s, s.player, event)
    assert full["build_detail"] == "full" and full["new_build"]["name"] == "Fighter 2"


def test_a_discover_only_or_denied_reader_sees_a_generic_build_change(s: ContentSetup) -> None:
    times = Times(s)
    start_clock(s, times)
    aldric = published_pc(s, "Aldric")
    first, second = two_builds(s, aldric)
    event = activation_event(s, aldric, first, second)
    grant(s, "character.discover", aldric)
    discover = world_event(s, s.player, event)
    assert discover.json()["explanation"]["build_detail"] == "generic"
    assert "Fighter" not in discover.text
    grant(s, "character.view_full", aldric, "deny")
    assert world_event(s, s.player, event).json()["explanation"]["build_detail"] == "generic"


def test_the_first_activation_is_administrative_and_a_deleted_build_is_unavailable(
    s: ContentSetup,
) -> None:
    times = Times(s)
    start_clock(s, times)
    aldric = published_pc(s, "Aldric")
    first, second = two_builds(s, aldric)
    after_baseline = event_count(s)
    event = activation_event(s, aldric, first, second)
    assert event_count(s) == after_baseline + 1
    s.connection.execute(
        text("DELETE FROM character.character_builds WHERE character_build_id = :b"),
        {"b": first},
    )
    gm = explanation(s, s.gm, event)
    assert gm["previous_build"] == {
        "state": "unavailable",
        "kind": "build",
        "entity_id": None,
        "name": None,
        "openable": False,
    }
    assert gm["new_build"]["name"] == "Fighter 2"


# --- clock ----------------------------------------------------------------------------------


def test_clock_advance_and_correction_show_previous_new_and_the_chain(s: ContentSetup) -> None:
    times = Times(s)
    y1, y2, y3 = times.at(1), times.at(2), times.at(3)
    first = _advance(s, y1, 0)
    assert first.status_code == 200, first.text
    second = _advance(s, y2, 1)
    assert second.status_code == 200, second.text
    on_first = explanation(s, s.gm, first.json()["event_id"])
    assert on_first["family"] == "campaign_clock_advanced"
    assert on_first["previous_time"] == {"state": "unrecorded", "text": None}
    assert "Year 1" in on_first["new_time"]["text"]
    assert on_first["relations"] == []

    on_second = explanation(s, s.gm, second.json()["event_id"])
    assert "Year 1" in on_second["previous_time"]["text"]
    assert "Year 2" in on_second["new_time"]["text"]
    assert "Year 2" in on_second["in_world_time"]
    (follows,) = on_second["relations"]
    assert follows["relation"] == "follows_previous_clock_change"
    assert (
        follows["event"]["entity_id"] == first.json()["event_id"] and follows["event"]["openable"]
    )

    corrected = s.gm.post_raw(
        f"/campaigns/{s.cid}/clock/correct",
        {
            "world_time_id": y3,
            "expected_row_version": clock_version(s),
            "corrects_event_id": second.json()["event_id"],
        },
        key=s.gm.fresh_key(),
    )
    assert corrected.status_code == 200, corrected.text
    on_correction = explanation(s, s.player, corrected.json()["event_id"])
    assert on_correction["family"] == "campaign_clock_corrected"
    assert "Year 2" in on_correction["previous_time"]["text"]
    assert "Year 3" in on_correction["new_time"]["text"]
    assert [r["relation"] for r in on_correction["relations"]] == ["corrects_clock_change"]
    again = explanation(s, s.gm, second.json()["event_id"])
    assert [r["relation"] for r in again["relations"]] == [
        "follows_previous_clock_change",
        "corrected_by_clock_change",
    ]


def test_a_clock_time_outside_the_world_is_unavailable_not_an_id(s: ContentSetup) -> None:
    event = _advance(s, Times(s).at(1), 0).json()["event_id"]
    calendar = s.stranger.post_raw(
        f"/worlds/{s.other_world_id}/calendars", CALENDAR, key=s.stranger.fresh_key()
    ).json()
    foreign = s.stranger.post_raw(
        f"/campaigns/{s.other_cid}/world-times",
        {"calendar_id": calendar["calendar_id"], "year": 1},
        key=s.stranger.fresh_key(),
    ).json()["world_time_id"]
    s.connection.execute(
        text(
            "UPDATE narrative.event_effects SET new_value = to_jsonb(CAST(:v AS text)) "
            "WHERE event_id = :e"
        ),
        {"v": foreign, "e": event},
    )
    shown = explanation(s, s.gm, event)
    assert shown["new_time"] == {"state": "unavailable", "text": None}
    assert foreign not in world_event(s, s.gm, event).text


# --- GM view, corrections, sessions, summary ------------------------------------------------


def record_event(
    s: ContentSetup, time_id: str, name: str = "The door opens", **extra: object
) -> str:
    response = s.gm.post_raw(
        f"/campaigns/{s.cid}/events",
        {"world_time_id": time_id, "event_type_code": "other", "name": name, **extra},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["event_id"])


def test_the_gm_event_view_carries_the_same_explanation_as_the_world_page(s: ContentSetup) -> None:
    times = Times(s)
    start_clock(s, times)
    party, aldric = new_party(s, "The Company"), published_pc(s, "Aldric")
    joined = join(s, party, aldric, times.at(1))
    authoring = s.gm.get(f"/campaigns/{s.cid}/events/{joined}")
    assert authoring.status_code == 200, authoring.text
    assert authoring.json()["explanation"] == explanation(s, s.gm, joined)
    # The raw effect rows stay for the correction preview.
    assert authoring.json()["effects"][0]["component"] == "party_membership"


def test_an_event_without_an_adapter_has_a_safe_generic_explanation(s: ContentSetup) -> None:
    times = Times(s)
    start_clock(s, times)
    event = record_event(s, times.at(1), details="GM only")
    shown = explanation(s, s.player, event)
    assert shown["family"] == "other" and "Year 1" in shown["in_world_time"]
    assert shown["subject"] is None and shown["relations"] == [] and shown["travel"] is None
    assert "GM only" not in world_event(s, s.player, event).text


def test_correction_links_name_events_for_the_gm_and_withhold_the_voided_one_from_readers(
    s: ContentSetup,
) -> None:
    times = Times(s)
    start_clock(s, times)
    y1, y2 = times.at(1), times.at(2)
    voided = record_event(s, y1, "The door is locked")
    response = s.gm.post_raw(
        f"/campaigns/{s.cid}/events/{voided}/void",
        {"reason": "PRIVATE reason"},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 200, response.text
    correcting = response.json()["correcting_event_id"]
    as_gm = s.gm.get(f"/campaigns/{s.cid}/events/{correcting}").json()["explanation"]
    (relation,) = as_gm["relations"]
    assert relation["relation"] == "corrects" and relation["reason"] == "PRIVATE reason"
    assert relation["event"]["name"] == "The door is locked" and relation["event"]["openable"]
    on_original = s.gm.get(f"/campaigns/{s.cid}/events/{voided}").json()["explanation"]
    assert [r["relation"] for r in on_original["relations"]] == ["corrected_by"]
    as_player = world_event(s, s.player, correcting)
    assert as_player.status_code == 200, as_player.text
    (hidden,) = as_player.json()["explanation"]["relations"]
    assert hidden["event"] == {
        "state": "unavailable",
        "kind": "event",
        "entity_id": None,
        "name": None,
        "openable": False,
    }
    assert hidden["reason"] is None
    assert "PRIVATE" not in as_player.text and "The door is locked" not in as_player.text

    original = record_event(s, y1, "The window is open")
    fixed = s.gm.post_raw(
        f"/campaigns/{s.cid}/events/{original}/correct",
        {
            "reason": "Wrong detail",
            "replacement": {
                "event_type_code": "other",
                "name": "The window is shut",
                "world_time_id": y2,
            },
        },
        key=s.gm.fresh_key(),
    )
    assert fixed.status_code == 200, fixed.text
    replacement = explanation(s, s.player, fixed.json()["replacement_event_id"])
    by_relation = {r["relation"]: r for r in replacement["relations"]}
    # The replacement was caused by the correcting event and replaces the original.
    assert set(by_relation) == {"caused_by", "replaces"}
    replaces = by_relation["replaces"]
    assert replaces["reason"] is None
    # A corrected (not voided) original stays readable and openable.
    assert replaces["event"]["name"] == "The window is open" and replaces["event"]["openable"]


def test_session_detail_carries_explanations_and_leaves_travel_to_the_travel_entries(
    s: ContentSetup,
) -> None:
    times = Times(s)
    clock = start_clock(s, times)
    town, aldric = place(s, "Stonebridge"), published_pc(s, "Aldric")
    session = new_session(s, title="Run")
    sid = str(session["session_id"])
    assert post(s, sid, "/start", {}).status_code == 200
    note = record_event(s, clock, "A quiet moment", session_id=sid)
    moved = session_travel(s, sid, town, character_ids=[aldric])
    assert moved.status_code == 200, moved.text
    view = detail(s, sid)
    assert [t["event_id"] for t in view["travel"]] == [moved.json()["event_id"]]
    assert [e["event_id"] for e in view["explanations"]] == [note]
    (shown,) = view["explanations"]
    assert shown["session"]["session_id"] == sid and shown["session"]["session_number"] == 1
    # The same travel event read on its own page shares the travel explanation.
    travel = explanation(s, s.gm, moved.json()["event_id"])
    assert travel["family"] == "travel" and travel["session"]["session_id"] == sid
    (leg,) = travel["travel"]["legs"]
    assert leg["traveler"]["name"] == "Aldric" and leg["to"]["name"] == "Stonebridge"
    assert leg["from"]["state"] == "unrecorded"


def test_a_session_the_reader_may_not_view_is_not_linked(s: ContentSetup) -> None:
    times = Times(s)
    clock = start_clock(s, times)
    session = new_session(s, title="Run")
    sid = str(session["session_id"])
    assert post(s, sid, "/start", {}).status_code == 200
    event = record_event(s, clock, "In the session", session_id=sid)
    assert explanation(s, s.player, event)["session"]["session_id"] == sid
    make_resource_grant(
        s.connection,
        uuid.UUID(s.cid),
        lookup_id(s.connection, "security", "capabilities", "capability_id", "campaign.view"),
        grantee_campaign_membership_id=player_membership(s),
        session_id=uuid.UUID(sid),
        effect="deny",
    )
    shown = world_event(s, s.player, event)
    assert shown.status_code == 200 and shown.json()["explanation"]["session"] is None
    assert sid not in shown.text


def test_a_recorded_move_that_is_not_travel_shares_the_location_explanation(
    s: ContentSetup,
) -> None:
    times = Times(s)
    clock = start_clock(s, times)
    town, aldric = place(s, "Stonebridge"), published_pc(s, "Aldric")
    moved = s.gm.post_raw(
        f"/campaigns/{s.cid}/characters/{aldric}/location",
        {"world_time_id": clock, "location_id": town},
        key=s.gm.fresh_key(),
    )
    assert moved.status_code == 200, moved.text
    shown = explanation(s, s.gm, moved.json()["event_id"])
    assert shown["family"] == "location"
    (leg,) = shown["travel"]["legs"]
    assert leg["traveler"]["name"] == "Aldric" and leg["to"]["name"] == "Stonebridge"


def test_the_campaign_summary_recent_events_carry_the_explanation(s: ContentSetup) -> None:
    times = Times(s)
    start_clock(s, times)
    party, aldric = new_party(s, "The Company"), published_pc(s, "Aldric")
    joined = join(s, party, aldric, times.at(1))
    grant(s, "character.discover", aldric)
    for actor in (s.gm, s.player):
        recent = actor.get(f"/campaigns/{s.cid}/summary").json()["recent_events"]
        found = next(e for e in recent if e["event_id"] == joined)
        assert found["explanation"]["subject"]["name"] == "Aldric"
        assert found["explanation"]["party"]["name"] == "The Company"
    grant(s, "character.discover", aldric, "deny")
    hidden = s.player.get(f"/campaigns/{s.cid}/summary")
    assert "Aldric" not in hidden.text and aldric not in hidden.text


def test_a_replayed_join_adds_no_event_and_explains_the_one_it_has(s: ContentSetup) -> None:
    times = Times(s)
    start_clock(s, times)
    party, aldric = new_party(s), published_pc(s, "Aldric")
    body = {
        "character_id": aldric,
        "effective_from_world_time_id": times.at(1),
        "expected_party_row_version": 1,
    }
    path = f"/campaigns/{s.cid}/parties/{party['party_id']}/members"
    key = s.gm.fresh_key()
    first = s.gm.post_raw(path, body, key=key)
    before = event_count(s)
    replay = s.gm.post_raw(path, body, key=key)
    assert first.status_code == 201 and replay.status_code == first.status_code
    assert replay.json()["event_id"] == first.json()["event_id"]
    assert event_count(s) == before
    assert explanation(s, s.gm, first.json()["event_id"])["family"] == "party_member_joined"


def test_a_branch_never_explains_or_links_the_parents_later_history(s: ContentSetup) -> None:
    times = Times(s)
    y1, y2, y3 = times.at(1), times.at(2), times.at(3)
    first = _advance(s, y1, 0).json()["event_id"]
    parent_later = _advance(s, y2, 1).json()["event_id"]
    branch = _branch_campaign(s, y1)
    branch_advance = s.gm.post_raw(
        f"/campaigns/{branch}/clock/advance",
        {"world_time_id": y3, "expected_row_version": 0},
        key=s.gm.fresh_key(),
    )
    assert branch_advance.status_code == 200, branch_advance.text
    assert s.gm.get(f"/campaigns/{branch}/world/events/{parent_later}").status_code == 404
    assert s.gm.get(f"/campaigns/{branch}/world/events/{first}").status_code == 404
    own = s.gm.get(f"/campaigns/{branch}/world/events/{branch_advance.json()['event_id']}").json()
    assert own["explanation"]["relations"] == []
    assert "Year 3" in own["explanation"]["new_time"]["text"]
    assert parent_later not in str(own) and first not in str(own)


def test_an_event_of_another_campaign_is_not_explained_here(s: ContentSetup) -> None:
    times = Times(s)
    event = _advance(s, times.at(1), 0).json()["event_id"]
    assert s.stranger.get(f"/campaigns/{s.other_cid}/world/events/{event}").status_code == 404


def test_the_summary_withholds_gm_only_event_details_from_members(s: ContentSetup) -> None:
    times = Times(s)
    start_clock(s, times)
    marker = "PRIVATE-DETAILS-MARKER-7731"
    event = record_event(s, times.at(1), "A quiet moment", details=marker)
    member = s.player.get(f"/campaigns/{s.cid}/summary")
    assert member.status_code == 200, member.text
    assert marker not in member.text
    shown = next(e for e in member.json()["recent_events"] if e["event_id"] == event)
    assert shown["name"] == "A quiet moment" and shown["details"] is None
    assert shown["explanation"]["family"] == "other"
    editor = s.gm.get(f"/campaigns/{s.cid}/summary").json()["recent_events"]
    assert next(e for e in editor if e["event_id"] == event)["details"] == marker


def test_only_a_clock_events_own_chain_row_reads_as_a_clock_chain_link(s: ContentSetup) -> None:
    times = Times(s)
    first = _advance(s, times.at(1), 0).json()["event_id"]
    second = _advance(s, times.at(2), 1).json()["event_id"]
    other = record_event(s, times.at(2), "Because of the new time")
    s.connection.execute(
        text("INSERT INTO narrative.event_causes (event_id, cause_event_id) VALUES (:e, :c)"),
        {"e": other, "c": second},
    )
    (recorded,) = explanation(s, s.gm, other)["relations"]
    assert recorded["relation"] == "caused_by" and recorded["event"]["entity_id"] == second
    # The clock event's own chain row keeps its label.
    (chain,) = explanation(s, s.gm, second)["relations"][:1]
    assert chain["relation"] == "follows_previous_clock_change"
    assert chain["event"]["entity_id"] == first
