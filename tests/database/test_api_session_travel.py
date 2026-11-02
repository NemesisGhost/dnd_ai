"""Travel recorded through a session in progress (session travel fix, checkpoints C1 and C2).

The session-scoped route links the `characters_traveled` event to the session in the same
transaction as the location history; the plain route stays standalone. The session detail then
carries readable travel entries, filtered for the audience.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.api.sessions import _actions
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times
from tests.database.test_api_routes_travel import clock_at, history, pc, place
from tests.database.test_api_routes_travel import travel as standalone_travel
from tests.database.test_api_session_play import base, detail, new_session, post, published_npc
from tests.factories import make_resource_grant

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def started_session(s: ContentSetup, times: Times, year: int = 1) -> str:
    clock_at(s, year, times)
    session = new_session(s, title="Run")
    assert post(s, session["session_id"], "/start", {}).status_code == 200
    return str(session["session_id"])


def session_travel(s: ContentSetup, session_id: str, destination: str, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        base(s, session_id, "/travel"),
        {"destination_location_id": destination, **extra},
        key=s.gm.fresh_key(),
    )


def code(response) -> str:  # type: ignore[no-untyped-def]
    return str(response.json()["error"]["code"])


def travel_event_count(s: ContentSetup) -> int:
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


def history_rows(s: ContentSetup) -> int:
    return s.count("campaign.character_location_history")


def event_session(s: ContentSetup, event_id: str) -> tuple[object, object, object]:
    row = s.connection.execute(
        text(
            "SELECT session_id, campaign_id, timeline_id FROM narrative.events WHERE event_id = :e"
        ),
        {"e": event_id},
    ).one()
    return row.session_id, row.campaign_id, row.timeline_id


def clock_state(s: ContentSetup) -> tuple[object, int]:
    row = s.connection.execute(
        text("""
            SELECT tc.current_world_time_id, tc.row_version FROM campaign.timeline_clocks tc
            JOIN campaign.campaigns c ON c.timeline_id = tc.timeline_id WHERE c.campaign_id = :c
        """),
        {"c": s.cid},
    ).one()
    return str(row.current_world_time_id), int(row.row_version)


# --- linkage -------------------------------------------------------------------------------------


def test_session_travel_links_the_event_and_the_standalone_route_does_not(s: ContentSetup) -> None:
    town, keep = place(s, "Stonebridge"), place(s, "The Keep")
    aldric, mira = pc(s, "Aldric"), pc(s, "Mira")
    times = Times(s)
    sid = started_session(s, times)

    linked = session_travel(s, sid, town, character_ids=[aldric], note="GM only: at dawn")
    assert linked.status_code == 200, linked.text
    receipt = linked.json()
    assert receipt["changed"] is True and receipt["session_id"] == sid
    session_id, campaign_id, timeline_id = event_session(s, receipt["event_id"])
    assert str(session_id) == sid and str(campaign_id) == s.cid
    assert (
        timeline_id
        == s.connection.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": s.cid}
        ).scalar()
    )
    assert history(s, aldric) == [("Stonebridge", True)]
    (audit,) = s.audit("record_travel")
    assert audit.changed_fields["session_id"]["to"] == sid

    clock_at(s, 2, times)
    plain = standalone_travel(s, keep, character_ids=[mira])
    assert plain.status_code == 200 and "session_id" not in plain.json()
    assert event_session(s, plain.json()["event_id"])[0] is None

    view = detail(s, sid)
    assert [e["event_id"] for e in view["events"]] == [receipt["event_id"]]
    assert [t["event_id"] for t in view["travel"]] == [receipt["event_id"]]
    (entry,) = view["travel"]
    (leg,) = entry["legs"]
    assert leg["traveler"]["name"] == "Aldric"
    assert leg["from"] == {"state": "unrecorded", "entity_id": None, "name": None}
    assert leg["to"]["state"] == "named" and leg["to"]["name"] == "Stonebridge"
    assert entry["world_time"] and entry["note"] == "GM only: at dawn"
    assert view["events"][0]["world_time"] == entry["world_time"]


def test_a_no_op_session_travel_writes_nothing(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    aldric, mira = pc(s, "Aldric"), pc(s, "Mira")
    times = Times(s)
    sid = started_session(s, times)
    assert session_travel(s, sid, town, character_ids=[aldric]).status_code == 200
    clock_at(s, 2, times)
    events, rows, audits = travel_event_count(s), history_rows(s), len(s.audit("record_travel"))
    nothing = session_travel(s, sid, town, character_ids=[aldric])
    assert nothing.status_code == 200
    assert nothing.json()["changed"] is False and "event_id" not in nothing.json()
    assert nothing.json()["already_there"] == [aldric]
    mixed = session_travel(s, sid, town, character_ids=[aldric, mira])
    assert mixed.json()["moved"] == [mira] and mixed.json()["already_there"] == [aldric]
    assert travel_event_count(s) == events + 1 and history_rows(s) == rows + 1
    assert len(s.audit("record_travel")) == audits + 1


# --- session validation --------------------------------------------------------------------------


def test_travel_needs_a_session_in_progress_in_this_campaign(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    aldric = pc(s, "Aldric")
    times = Times(s)
    clock_at(s, 1, times)
    unstarted = new_session(s)["session_id"]
    foreign = s.stranger.post_raw(
        f"/campaigns/{s.other_cid}/sessions", {"title": "Theirs"}, key=s.stranger.fresh_key()
    ).json()["session_id"]
    ended = new_session(s)["session_id"]
    archived = new_session(s)["session_id"]
    # Only one session may be in progress at a time: end it before the next starts.
    assert post(s, ended, "/start", {}).status_code == 200
    clock_at(s, 2, times)
    assert post(s, ended, "/end", {}).status_code == 200
    arch = s.gm.post_raw(
        base(s, archived, "/archive"),
        {"expected_row_version": detail(s, archived)["row_version"]},
        key=s.gm.fresh_key(),
    )
    assert arch.status_code == 200

    events, rows = travel_event_count(s), history_rows(s)
    expected = {
        unstarted: ("session_not_in_progress", 409),
        ended: ("session_not_in_progress", 409),
        archived: ("session_not_active", 409),
        foreign: ("not_found", 404),
        str(uuid.uuid4()): ("not_found", 404),
    }
    for session_id, (error, status) in expected.items():
        refused = session_travel(s, session_id, town, character_ids=[aldric])
        assert (refused.status_code, code(refused)) == (status, error), session_id
    # A foreign session is indistinguishable from a missing one.
    foreign_refused = session_travel(s, foreign, town, character_ids=[aldric])
    missing = session_travel(s, str(uuid.uuid4()), town, character_ids=[aldric])
    assert foreign_refused.json()["error"]["code"] == missing.json()["error"]["code"]
    assert foreign_refused.status_code == missing.status_code
    assert travel_event_count(s) == events and history_rows(s) == rows


def test_travel_eligibility_matches_the_log_available_action(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    aldric = pc(s, "Aldric")
    times = Times(s)
    clock_at(s, 1, times)
    scheduled = new_session(s, scheduled_for="2099-01-01T00:00:00Z")["session_id"]
    unscheduled = new_session(s)["session_id"]
    running = new_session(s)["session_id"]
    done = new_session(s)["session_id"]
    assert post(s, done, "/start", {}).status_code == 200
    clock_at(s, 2, times)
    assert post(s, done, "/end", {}).status_code == 200
    assert post(s, running, "/start", {}).status_code == 200
    for session_id in (scheduled, unscheduled, running, done):
        view = detail(s, session_id)
        allowed = "log" in _actions(view["status_code"], view["play_status"])
        assert ("log" in view["available_actions"]) == allowed
        response = session_travel(s, session_id, town, character_ids=[aldric])
        assert (response.status_code == 200) == allowed, (view["play_status"], response.text)


def test_a_stale_session_fails_even_when_everyone_is_already_there(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    aldric = pc(s, "Aldric")
    times = Times(s)
    sid = started_session(s, times)
    assert session_travel(s, sid, town, character_ids=[aldric]).status_code == 200
    clock_at(s, 2, times)
    assert post(s, sid, "/end", {}).status_code == 200
    stale = session_travel(s, sid, town, character_ids=[aldric])
    assert stale.status_code == 409 and code(stale) == "session_not_in_progress"


def test_travel_authority(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    aldric = pc(s, "Aldric")
    sid = started_session(s, Times(s))
    body = {"destination_location_id": town, "character_ids": [aldric]}
    assert (
        s.player.post_raw(base(s, sid, "/travel"), body, key=s.player.fresh_key()).status_code
        == 403
    )
    outsider = s.stranger.post_raw(base(s, sid, "/travel"), body, key=s.stranger.fresh_key())
    assert outsider.status_code in (403, 404)
    assert travel_event_count(s) == 0


# --- atomicity and idempotency -------------------------------------------------------------------


def test_a_failure_after_the_event_insert_rolls_everything_back(
    s: ContentSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import Connection as Conn

    town = place(s, "Stonebridge")
    aldric, mira = pc(s, "Aldric"), pc(s, "Mira")
    sid = started_session(s, Times(s))
    real_execute = Conn.execute

    def failing(self: Conn, statement: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if "INSERT INTO campaign.character_location_history" in str(statement):
            raise RuntimeError("injected failure")
        return real_execute(self, statement, *args, **kwargs)  # type: ignore[arg-type]

    tables = (
        "core.entities",
        "narrative.events",
        "narrative.event_effects",
        "campaign.character_location_history",
        "audit.change_log",
    )
    before = {t: s.count(t) for t in tables}
    monkeypatch.setattr(Conn, "execute", failing)
    response = session_travel(s, sid, town, character_ids=[aldric, mira])
    monkeypatch.undo()
    assert response.status_code == 500
    assert before == {t: s.count(t) for t in tables}
    assert detail(s, sid)["events"] == []


def test_an_invalid_traveler_in_a_session_journey_leaves_nothing(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    aldric, draft = pc(s, "Aldric"), pc(s, "Unpublished", publish=False)
    sid = started_session(s, Times(s))
    refused = session_travel(s, sid, town, character_ids=[aldric, draft])
    assert refused.status_code == 400 and code(refused) == "travel_invalid"
    assert travel_event_count(s) == 0 and history(s, aldric) == []


def test_replays_record_one_event_and_a_different_session_is_a_mismatch(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    aldric = pc(s, "Aldric")
    times = Times(s)
    sid = started_session(s, times)
    other = new_session(s)["session_id"]
    body = {"destination_location_id": town, "character_ids": [aldric]}
    key = s.gm.fresh_key()
    first = s.gm.post_raw(base(s, sid, "/travel"), body, key=key)
    again = s.gm.post_raw(base(s, sid, "/travel"), body, key=key)
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert travel_event_count(s) == 1 and len(s.audit("record_travel")) == 1
    assert history(s, aldric) == [("Stonebridge", True)]
    mismatch = s.gm.post_raw(base(s, other, "/travel"), body, key=key)
    assert mismatch.status_code == 409 and travel_event_count(s) == 1
    clock_at(s, 2, times)
    assert post(s, sid, "/end", {}).status_code == 200
    after_end = s.gm.post_raw(base(s, sid, "/travel"), body, key=key)
    assert after_end.status_code == 200 and after_end.json() == first.json()
    assert travel_event_count(s) == 1


# --- time ----------------------------------------------------------------------------------------


def test_an_explicit_time_does_not_move_the_clock_and_must_follow_the_arrival(
    s: ContentSetup,
) -> None:
    north, south = place(s, "Northmark"), place(s, "Southmark")
    aldric = pc(s, "Aldric")
    times = Times(s)
    sid = started_session(s, times, year=5)
    clock_before = clock_state(s)
    explicit = times.at(3)
    ok = session_travel(s, sid, north, character_ids=[aldric], world_time_id=explicit)
    assert ok.status_code == 200, ok.text
    assert clock_state(s) == clock_before
    assert detail(s, sid)["travel"][0]["world_time_id"] == explicit
    # At or before the arrival the journey is refused and nothing is written.
    events, rows = travel_event_count(s), history_rows(s)
    same = session_travel(s, sid, south, character_ids=[aldric], world_time_id=explicit)
    assert same.status_code == 409 and code(same) == "travel_time_invalid"
    earlier = session_travel(s, sid, south, character_ids=[aldric], world_time_id=times.at(2))
    assert earlier.status_code == 409 and code(earlier) == "travel_time_invalid"
    assert travel_event_count(s) == events and history_rows(s) == rows
    # Default time is the campaign clock.
    default = session_travel(s, sid, south, character_ids=[aldric])
    assert default.status_code == 200
    assert detail(s, sid)["travel"][-1]["world_time_id"] == clock_before[0]


def test_session_history_is_in_world_order_with_log_entries(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    aldric, mira = pc(s, "Aldric"), pc(s, "Mira")
    times = Times(s)
    sid = started_session(s, times, year=1)
    late = session_travel(s, sid, town, character_ids=[aldric], world_time_id=times.at(9))
    early = session_travel(s, sid, town, character_ids=[mira], world_time_id=times.at(3))
    log = post(
        s, sid, "/log", {"entry": "Middle", "world_time_id": times.at(5)}, versioned=False
    ).json()
    assert late.status_code == early.status_code == 200
    view = detail(s, sid)
    assert [e["event_id"] for e in view["events"]] == [
        early.json()["event_id"],
        log["event_id"],
        late.json()["event_id"],
    ]
    assert [t["event_id"] for t in view["travel"]] == [
        early.json()["event_id"],
        late.json()["event_id"],
    ]


# --- differing origins -----------------------------------------------------------------------------


def test_travelers_keep_their_own_origins(s: ContentSetup) -> None:
    north, east, south = place(s, "Northmark"), place(s, "Eastwatch"), place(s, "Southmark")
    aldric, mira, tovin, newcomer = (pc(s, n) for n in ("Aldric", "Mira", "Tovin", "Newcomer"))
    times = Times(s)
    sid = started_session(s, times)
    assert session_travel(s, sid, north, character_ids=[aldric, mira]).status_code == 200
    clock_at(s, 2, times)
    assert session_travel(s, sid, east, character_ids=[tovin]).status_code == 200
    clock_at(s, 3, times)
    group = session_travel(s, sid, south, character_ids=[aldric, mira, tovin, newcomer])
    assert group.status_code == 200 and len(group.json()["moved"]) == 4
    entry = detail(s, sid)["travel"][-1]
    legs = {
        leg["traveler"]["name"]: (leg["from"]["state"], leg["from"]["name"], leg["to"]["name"])
        for leg in entry["legs"]
    }
    assert legs == {
        "Aldric": ("named", "Northmark", "Southmark"),
        "Mira": ("named", "Northmark", "Southmark"),
        "Tovin": ("named", "Eastwatch", "Southmark"),
        "Newcomer": ("unrecorded", None, "Southmark"),
    }
    assert [leg["traveler"]["name"] for leg in entry["legs"]] == sorted(legs)


def test_party_and_individuals_are_unioned_once(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    aldric, mira = pc(s, "Aldric"), pc(s, "Mira")
    times = Times(s)
    year1 = clock_at(s, 1, times)
    party = s.gm.post_raw(
        f"/campaigns/{s.cid}/parties", {"name": "The Company"}, key=s.gm.fresh_key()
    ).json()
    for member in (aldric, mira):
        version = s.gm.get(f"/campaigns/{s.cid}/parties/{party['party_id']}").json()["row_version"]
        added = s.gm.post_raw(
            f"/campaigns/{s.cid}/parties/{party['party_id']}/members",
            {
                "character_id": member,
                "effective_from_world_time_id": year1,
                "expected_party_row_version": version,
            },
            key=s.gm.fresh_key(),
        )
        assert added.status_code == 201, added.text
    session = new_session(s)["session_id"]
    assert post(s, session, "/start", {}).status_code == 200
    clock_at(s, 2, times)
    result = session_travel(
        s, session, town, party_id=party["party_id"], character_ids=[aldric, aldric]
    )
    assert sorted(result.json()["moved"]) == sorted([aldric, mira])
    assert [leg["traveler"]["name"] for leg in detail(s, session)["travel"][0]["legs"]] == [
        "Aldric",
        "Mira",
    ]


# --- audience --------------------------------------------------------------------------------------


def _player_membership(s: ContentSetup) -> uuid.UUID:
    value = s.connection.execute(
        text(
            "SELECT campaign_membership_id FROM security.campaign_memberships "
            "WHERE campaign_id = :c AND user_id = :u"
        ),
        {"c": s.cid, "u": s.player.user_id},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def _capability(s: ContentSetup, code: str) -> uuid.UUID:
    value = s.connection.execute(
        text("SELECT capability_id FROM security.capabilities WHERE code = :c"), {"c": code}
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def _grant(s: ContentSetup, capability: str, **target: uuid.UUID) -> None:
    make_resource_grant(
        s.connection,
        uuid.UUID(s.cid),
        _capability(s, capability),
        grantee_campaign_membership_id=_player_membership(s),
        effect=str(target.pop("effect", "allow")),  # type: ignore[arg-type]
        **target,
    )


def test_players_see_authorized_names_only_and_never_the_gm_note(s: ContentSetup) -> None:
    north, south = place(s, "Northmark"), place(s, "Southmark")
    aldric, mira = pc(s, "Aldric"), pc(s, "Mira")
    times = Times(s)
    sid = started_session(s, times)
    assert session_travel(s, sid, north, character_ids=[aldric, mira]).status_code == 200
    clock_at(s, 2, times)
    secret = session_travel(
        s, sid, south, character_ids=[aldric, mira], note="GM only: ambush ahead"
    )
    assert secret.status_code == 200
    # The player can discover characters, but not Mira, and not the destination.
    _grant(s, "character.discover", character_id=uuid.UUID(aldric))
    _grant(s, "character.discover", character_id=uuid.UUID(mira))
    _grant(s, "campaign.view", entity_id=uuid.UUID(mira), effect="deny")
    _grant(s, "campaign.view", entity_id=uuid.UUID(south), effect="deny")

    tables_before = _knowledge_and_access_rows(s)
    player = detail(s, sid, who="player")
    assert _knowledge_and_access_rows(s) == tables_before
    for entry in player["travel"]:
        assert entry["note"] is None
        assert [leg["traveler"]["name"] for leg in entry["legs"]] == ["Aldric"]
    first, last = player["travel"]
    assert first["legs"][0]["to"]["name"] == "Northmark"
    assert last["legs"][0]["to"] == {"state": "unavailable", "entity_id": None, "name": None}
    assert last["legs"][0]["from"]["name"] == "Northmark"
    assert "Mira" not in str(player["travel"]) and "Southmark" not in str(player["travel"])
    assert "GM only" not in str(player) and player["participants"] == []
    gm = detail(s, sid)
    assert gm["travel"][-1]["note"] == "GM only: ambush ahead"
    assert [leg["traveler"]["name"] for leg in gm["travel"][-1]["legs"]] == ["Aldric", "Mira"]


def test_a_travel_event_with_no_authorized_travelers_is_a_bare_entry(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    hidden = published_npc(s, "Hidden Mira")
    sid = started_session(s, Times(s))
    assert session_travel(s, sid, town, character_ids=[hidden]).status_code == 200
    _grant(s, "campaign.view", entity_id=uuid.UUID(hidden), effect="deny")
    (entry,) = detail(s, sid, who="player")["travel"]
    assert entry["legs"] == [] and entry["note"] is None
    assert "Hidden" not in str(entry)


def test_a_denied_session_and_draft_or_voided_travel_are_not_listed(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    aldric = pc(s, "Aldric")
    sid = started_session(s, Times(s))
    event = session_travel(s, sid, town, character_ids=[aldric]).json()["event_id"]
    _grant(s, "character.discover", character_id=uuid.UUID(aldric))
    assert [t["event_id"] for t in detail(s, sid, who="player")["travel"]] == [event]
    s.connection.execute(
        text(
            "UPDATE narrative.events SET event_status_id = "
            "(SELECT event_status_id FROM narrative.event_statuses WHERE code = 'voided') "
            "WHERE event_id = :e"
        ),
        {"e": event},
    )
    assert detail(s, sid, who="player")["travel"] == []
    assert detail(s, sid)["travel"] == []
    _grant(s, "campaign.view", session_id=uuid.UUID(sid), effect="deny")
    assert s.player.get(base(s, sid)).status_code == 404


def _knowledge_and_access_rows(s: ContentSetup) -> dict[str, int]:
    tables = s.connection.execute(
        text(
            "SELECT table_schema || '.' || table_name FROM information_schema.tables "
            "WHERE table_schema IN ('knowledge', 'security') AND table_type = 'BASE TABLE' "
            "AND (table_schema = 'knowledge' OR table_name = 'resource_grants')"
        )
    ).scalars()
    return {str(t): s.count(str(t)) for t in tables}


def test_recording_travel_adds_no_knowledge_or_access(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    aldric = pc(s, "Aldric")
    sid = started_session(s, Times(s))
    before = _knowledge_and_access_rows(s)
    assert before
    assert session_travel(s, sid, town, character_ids=[aldric]).status_code == 200
    assert _knowledge_and_access_rows(s) == before


# --- event detail ----------------------------------------------------------------------------------


def test_event_detail_names_the_locations_and_links_the_session(s: ContentSetup) -> None:
    north, south = place(s, "Northmark"), place(s, "Southmark")
    aldric = pc(s, "Aldric")
    times = Times(s)
    sid = started_session(s, times)
    first = session_travel(s, sid, north, character_ids=[aldric]).json()["event_id"]
    clock_at(s, 2, times)
    second = session_travel(s, sid, south, character_ids=[aldric]).json()["event_id"]
    old = None
    clock_at(s, 3, times)
    standalone = standalone_travel(s, north, character_ids=[aldric]).json()["event_id"]
    old = standalone
    one = s.gm.get(f"/campaigns/{s.cid}/events/{first}").json()
    (effect,) = one["effects"]
    assert effect["target_name"] == "Aldric" and effect["previous_name"] is None
    assert effect["previous"] is None and effect["new_name"] == "Northmark"
    assert one["session_id"] == sid
    two = s.gm.get(f"/campaigns/{s.cid}/events/{second}").json()
    assert two["effects"][0]["previous_name"] == "Northmark"
    assert two["effects"][0]["new_name"] == "Southmark"
    unlinked = s.gm.get(f"/campaigns/{s.cid}/events/{old}").json()
    assert unlinked["session_id"] is None
    assert unlinked["effects"][0]["previous_name"] == "Southmark"
    # An id that no longer resolves in this world is never printed as a name.
    s.connection.execute(
        text(
            "UPDATE narrative.event_effects SET new_value = to_jsonb(CAST(:ghost AS text)) "
            "WHERE event_id = :e"
        ),
        {"ghost": str(uuid.uuid4()), "e": second},
    )
    ghost = s.gm.get(f"/campaigns/{s.cid}/events/{second}").json()["effects"][0]
    assert ghost["new_name"] is None
