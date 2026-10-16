"""Session play: participants, start, log, and end (checkpoint 15.2D-2, migration 123)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times, _advance, _branch_campaign
from tests.factories import make_character, make_session

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def base(s: ContentSetup, session_id: str, suffix: str = "") -> str:
    return f"/campaigns/{s.cid}/sessions/{session_id}{suffix}"


def new_session(s: ContentSetup, **body: object) -> dict:
    response = s.gm.post_raw(f"/campaigns/{s.cid}/sessions", body, key=s.gm.fresh_key())
    assert response.status_code == 201, response.text
    return response.json()


def detail(s: ContentSetup, session_id: str, who: str = "gm") -> dict:
    actor = s.gm if who == "gm" else s.player
    response = actor.get(base(s, session_id))
    assert response.status_code == 200, response.text
    return response.json()


def version(s: ContentSetup, session_id: str) -> int:
    return int(detail(s, session_id)["row_version"])


def post(s: ContentSetup, session_id: str, suffix: str, body: dict, *, versioned: bool = True):  # type: ignore[no-untyped-def]
    payload = {"expected_row_version": version(s, session_id), **body} if versioned else body
    return s.gm.post_raw(base(s, session_id, suffix), payload, key=s.gm.fresh_key())


def published_pc(s: ContentSetup, name: str = "Aldric") -> str:
    species = s.gm.get(s.url("player-characters/options")).json()["species"][0]["species_id"]
    created = s.gm.post(
        s.url("player-characters"),
        {"name": name, "species_id": species, "size_category": "medium"},
        key=s.gm.fresh_key(),
    ).json()
    s.publish(created["player_character_id"], created["row_version"])
    return created["player_character_id"]


def published_npc(s: ContentSetup, name: str = "Mira") -> str:
    species = s.gm.get(s.url("npcs/options")).json()["species"][0]["species_id"]
    created = s.gm.post(
        s.url("npcs"),
        {"name": name, "species_id": species, "size_category": "medium"},
        key=s.gm.fresh_key(),
    ).json()
    s.publish(created["npc_id"], created["row_version"])
    return created["npc_id"]


def set_clock(s: ContentSetup, year: int = 1) -> str:
    time_id = Times(s).at(year)
    assert _advance(s, time_id, 0).status_code == 200
    return time_id


# --- start ------------------------------------------------------------------------------------------


def test_start_needs_a_time_then_uses_the_clock_or_an_explicit_one(s: ContentSetup) -> None:
    session = new_session(s, title="One")
    refused = post(s, session["session_id"], "/start", {})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "clock_required"
    assert detail(s, session["session_id"])["play_status"] == "unscheduled"

    clock_time = set_clock(s)
    started = post(s, session["session_id"], "/start", {})
    assert started.status_code == 200, started.text
    view = detail(s, session["session_id"])
    assert view["play_status"] == "in_progress" and view["started_at"] is not None
    assert view["start_world_time_id"] == clock_time
    assert view["available_actions"] == ["update", "manage_participants", "log", "end"]
    (audit,) = s.audit("start_session")
    assert audit.changed_fields["start_world_time_id"]["to"] == clock_time

    explicit = new_session(s)
    other_time = Times(s).at(3)
    blocked = post(s, explicit["session_id"], "/start", {"start_world_time_id": other_time})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "another_session_in_progress"


def test_a_second_start_and_a_second_session_in_progress_are_refused(s: ContentSetup) -> None:
    set_clock(s)
    first, second = new_session(s), new_session(s)
    assert post(s, first["session_id"], "/start", {}).status_code == 200
    again = post(s, first["session_id"], "/start", {})
    assert again.status_code == 409 and again.json()["error"]["code"] == "session_already_started"
    other = post(s, second["session_id"], "/start", {})
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "another_session_in_progress"
    assert detail(s, second["session_id"])["play_status"] == "unscheduled"
    # Once the first ends, the second can start.
    assert (
        post(s, first["session_id"], "/end", {"end_world_time_id": Times(s).at(5)}).status_code
        == 200
    )
    assert post(s, second["session_id"], "/start", {}).status_code == 200


def test_start_checks_version_and_state(s: ContentSetup) -> None:
    set_clock(s)
    session = new_session(s)
    stale = s.gm.post_raw(
        base(s, session["session_id"], "/start"),
        {"expected_row_version": 99},
        key=s.gm.fresh_key(),
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"
    archived = s.gm.post_raw(
        base(s, session["session_id"], "/archive"),
        {"expected_row_version": version(s, session["session_id"])},
        key=s.gm.fresh_key(),
    )
    assert archived.status_code == 200
    closed = post(s, session["session_id"], "/start", {})
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "session_not_active"


def test_a_pending_session_offers_no_actions_and_refuses_participants(s: ContentSetup) -> None:
    # A seeded session can be `pending` (not `active`). Every play command refuses it
    # with `session_not_active`, so the read model must not advertise actions that
    # can only fail (the Run Session page keys its controls off `available_actions`).
    pending = make_session(s.connection, uuid.UUID(s.cid), 90, lifecycle_status_code="pending")
    view = detail(s, str(pending))
    assert view["status_code"] == "pending" and view["available_actions"] == []
    character = published_pc(s)
    refused = post(
        s,
        str(pending),
        "/participants",
        {"character_id": character, "participation_role": "player_character"},
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "session_not_active"


# --- participants -----------------------------------------------------------------------------------


def test_participants_are_published_characters_with_a_matching_role(s: ContentSetup) -> None:
    session = new_session(s)
    sid = session["session_id"]
    pc, npc = published_pc(s), published_npc(s)
    added = post(
        s, sid, "/participants", {"character_id": pc, "participation_role": "player_character"}
    )
    assert added.status_code == 201, added.text
    assert set(added.json()) == {"session_id", "row_version", "changed", "session_participant_id"}
    assert (
        post(
            s, sid, "/participants", {"character_id": npc, "participation_role": "npc"}
        ).status_code
        == 201
    )
    guest = published_npc(s, "Visitor")
    assert (
        post(
            s, sid, "/participants", {"character_id": guest, "participation_role": "guest"}
        ).status_code
        == 201
    )

    mismatch = post(
        s,
        sid,
        "/participants",
        {"character_id": published_pc(s, "Bryn"), "participation_role": "npc"},
    )
    assert (
        mismatch.status_code == 400
        and mismatch.json()["error"]["code"] == "session_participant_invalid"
    )
    bad_role = post(
        s, sid, "/participants", {"character_id": pc, "participation_role": "spectator"}
    )
    assert bad_role.status_code in (400, 422)

    species = s.gm.get(s.url("player-characters/options")).json()["species"][0]["species_id"]
    draft = s.gm.post(
        s.url("player-characters"),
        {"name": "Draft", "species_id": species, "size_category": "medium"},
        key=s.gm.fresh_key(),
    ).json()["player_character_id"]
    for character in (
        draft,
        str(make_character(s.connection, s.world_id, name="Bare")),
        str(make_character(s.connection, s.other_world_id, name="Elsewhere")),
    ):
        refused = post(
            s, sid, "/participants", {"character_id": character, "participation_role": "guest"}
        )
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"]["code"] == "session_participant_invalid"

    view = detail(s, sid)
    assert [(p["character_name"], p["participation_role"]) for p in view["participants"]] == [
        ("Aldric", "player_character"),
        ("Mira", "npc"),
        ("Visitor", "guest"),
    ]
    assert detail(s, sid, who="player")["participants"] is None
    (audit, *_) = s.audit("add_session_participant")
    assert audit.changed_fields["participation_role"] == "player_character"


def test_a_participant_can_be_removed_once_and_added_again(s: ContentSetup) -> None:
    session = new_session(s)
    sid = session["session_id"]
    pc = published_pc(s)
    body = {"character_id": pc, "participation_role": "player_character"}
    first = post(s, sid, "/participants", body).json()
    again = post(s, sid, "/participants", body)
    assert (
        again.status_code == 409 and again.json()["error"]["code"] == "session_participant_exists"
    )
    removed = post(s, sid, f"/participants/{first['session_participant_id']}/remove", {})
    assert removed.status_code == 200, removed.text
    twice = post(s, sid, f"/participants/{first['session_participant_id']}/remove", {})
    assert (
        twice.status_code == 409 and twice.json()["error"]["code"] == "session_participant_removed"
    )
    assert post(s, sid, "/participants", body).status_code == 201
    participants = detail(s, sid)["participants"]
    assert [p["removed_at"] is None for p in participants] == [True, False]
    missing = post(s, sid, f"/participants/{uuid.uuid4()}/remove", {})
    assert missing.status_code == 404


def test_participants_cannot_change_once_the_session_has_ended(s: ContentSetup) -> None:
    set_clock(s)
    session = new_session(s)
    sid = session["session_id"]
    pc = published_pc(s)
    joined = post(
        s, sid, "/participants", {"character_id": pc, "participation_role": "player_character"}
    ).json()
    assert post(s, sid, "/start", {}).status_code == 200
    assert post(s, sid, "/end", {"end_world_time_id": Times(s).at(4)}).status_code == 200
    late = post(
        s,
        sid,
        "/participants",
        {"character_id": published_pc(s, "Late"), "participation_role": "guest"},
    )
    assert late.status_code == 409 and late.json()["error"]["code"] == "session_not_open"
    gone = post(s, sid, f"/participants/{joined['session_participant_id']}/remove", {})
    assert gone.status_code == 409 and gone.json()["error"]["code"] == "session_not_open"


# --- log --------------------------------------------------------------------------------------------


def test_a_log_entry_is_a_session_event_with_gm_only_details(s: ContentSetup) -> None:
    clock_time = set_clock(s)
    session = new_session(s)
    sid = session["session_id"]
    early = post(s, sid, "/log", {"entry": "Too soon"}, versioned=False)
    assert early.status_code == 409 and early.json()["error"]["code"] == "session_not_in_progress"
    assert post(s, sid, "/start", {}).status_code == 200
    pc = published_pc(s)
    logged = post(
        s,
        sid,
        "/log",
        {
            "entry": "The party enters the crypt.",
            "details": "SECRET: the door is trapped",
            "character_ids": [pc],
        },
        versioned=False,
    )
    assert logged.status_code == 201, logged.text
    assert set(logged.json()) == {"session_id", "row_version", "changed", "event_id"}
    row = s.connection.execute(
        text("""
            SELECT et.code AS type_code, es.code AS status_code, e.session_id, e.campaign_id,
                   e.timeline_id, e.world_time_id, e.details, ce.canonical_name,
                   (SELECT count(*) FROM narrative.event_participants p WHERE p.event_id = e.event_id) AS participants
            FROM narrative.events e
            JOIN narrative.event_types et ON et.event_type_id = e.event_type_id
            JOIN narrative.event_statuses es ON es.event_status_id = e.event_status_id
            JOIN core.entities ce ON ce.entity_id = e.event_id
            WHERE e.event_id = :e
        """),
        {"e": logged.json()["event_id"]},
    ).one()
    assert (row.type_code, row.status_code, str(row.session_id), str(row.campaign_id)) == (
        "session_narrative",
        "recorded",
        sid,
        s.cid,
    )
    assert str(row.world_time_id) == clock_time and row.participants == 1
    assert row.canonical_name == "The party enters the crypt." and "SECRET" in row.details

    gm_events = detail(s, sid)["events"]
    assert gm_events[0]["details"] == "SECRET: the door is trapped"
    player_events = detail(s, sid, who="player")["events"]
    assert [e["name"] for e in player_events] == ["The party enters the crypt."]
    assert player_events[0]["details"] is None
    (audit,) = s.audit("record_session_log_entry")
    assert "crypt" not in str(audit.changed_fields) and "SECRET" not in str(audit.changed_fields)


@pytest.mark.parametrize(
    "body",
    [{"entry": ""}, {"entry": "   "}, {"entry": "x" * 501}, {"entry": "ok", "details": "x" * 5000}],
)
def test_invalid_log_entries_are_refused(s: ContentSetup, body: dict) -> None:
    set_clock(s)
    session = new_session(s)
    assert post(s, session["session_id"], "/start", {}).status_code == 200
    before = s.count("narrative.events")
    response = post(s, session["session_id"], "/log", body, versioned=False)
    assert response.status_code in (400, 422)
    assert s.count("narrative.events") == before


def test_a_log_entry_needs_a_time_and_a_valid_one(s: ContentSetup) -> None:
    session = new_session(s)
    sid = session["session_id"]
    other_calendar = s.stranger.post_raw(
        f"/worlds/{s.other_world_id}/calendars",
        {
            "name": "C",
            "description": None,
            "days_per_week": None,
            "epoch_label": None,
            "months": [{"name": "M", "day_count": 10}],
        },
        key=s.stranger.fresh_key(),
    ).json()["calendar_id"]
    foreign_time = s.stranger.post_raw(
        f"/campaigns/{s.other_cid}/world-times",
        {"calendar_id": other_calendar, "year": 1},
        key=s.stranger.fresh_key(),
    ).json()["world_time_id"]
    explicit = Times(s).at(2)
    assert post(s, sid, "/start", {"start_world_time_id": explicit}).status_code == 200
    no_clock = post(s, sid, "/log", {"entry": "x"}, versioned=False)
    assert no_clock.status_code == 409 and no_clock.json()["error"]["code"] == "clock_required"
    foreign = post(s, sid, "/log", {"entry": "x", "world_time_id": foreign_time}, versioned=False)
    assert foreign.status_code == 400 and foreign.json()["error"]["code"] == "world_time_id_invalid"
    ok = post(s, sid, "/log", {"entry": "x", "world_time_id": explicit}, versioned=False)
    assert ok.status_code == 201, ok.text


def test_log_replay_records_one_event(s: ContentSetup) -> None:
    set_clock(s)
    session = new_session(s)
    sid = session["session_id"]
    assert post(s, sid, "/start", {}).status_code == 200
    key = s.gm.fresh_key()
    first = s.gm.post_raw(base(s, sid, "/log"), {"entry": "Once"}, key=key)
    again = s.gm.post_raw(base(s, sid, "/log"), {"entry": "Once"}, key=key)
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    count = s.connection.execute(
        text("SELECT count(*) FROM narrative.events WHERE session_id = :s"), {"s": sid}
    ).scalar()
    assert count == 1


def test_a_failure_while_logging_leaves_no_event(
    s: ContentSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import Connection as Conn

    set_clock(s)
    session = new_session(s)
    sid = session["session_id"]
    assert post(s, sid, "/start", {}).status_code == 200
    real_execute = Conn.execute

    def failing(self: Conn, statement: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if "INSERT INTO narrative.events" in str(statement):
            raise RuntimeError("injected failure")
        return real_execute(self, statement, *args, **kwargs)  # type: ignore[arg-type]

    tables = ("core.entities", "narrative.events", "audit.change_log")
    before = {t: s.count(t) for t in tables}
    monkeypatch.setattr(Conn, "execute", failing)
    response = s.gm.post_raw(base(s, sid, "/log"), {"entry": "Doomed"}, key=s.gm.fresh_key())
    monkeypatch.undo()
    assert response.status_code == 500
    assert before == {t: s.count(t) for t in tables}


# --- end --------------------------------------------------------------------------------------------


def test_end_needs_a_session_in_progress_and_a_later_time(s: ContentSetup) -> None:
    clock_time = set_clock(s, 2)
    session = new_session(s)
    sid = session["session_id"]
    early = post(s, sid, "/end", {})
    assert early.status_code == 409 and early.json()["error"]["code"] == "session_not_in_progress"
    assert post(s, sid, "/start", {}).status_code == 200
    same = post(s, sid, "/end", {})  # the clock still shows the start time
    assert same.status_code == 409 and same.json()["error"]["code"] == "session_end_not_after_start"
    before = post(s, sid, "/end", {"end_world_time_id": Times(s).at(1)})
    assert before.status_code == 409
    assert _advance(s, Times(s).at(5), 1).status_code == 200
    ended = post(s, sid, "/end", {"summary": "They survived."})
    assert ended.status_code == 200, ended.text
    view = detail(s, sid)
    assert view["play_status"] == "completed" and view["summary"] == "They survived."
    assert view["start_world_time_id"] == clock_time and view["end_world_time_id"] is not None
    again = post(s, sid, "/end", {})
    assert again.status_code == 409 and again.json()["error"]["code"] == "session_not_in_progress"
    late_log = post(s, sid, "/log", {"entry": "Too late"}, versioned=False)
    assert (
        late_log.status_code == 409
        and late_log.json()["error"]["code"] == "session_not_in_progress"
    )
    assert [a.action for a in s.audit("end_session")] == ["updated"]


# --- authority, isolation, database guards -----------------------------------------------------------


def test_players_and_strangers_cannot_run_a_session(s: ContentSetup) -> None:
    session = new_session(s)
    sid = session["session_id"]
    for actor in (s.player, s.stranger):
        for suffix, body in (
            ("/start", {"expected_row_version": 1}),
            ("/end", {"expected_row_version": 1}),
            ("/log", {"entry": "x"}),
            (
                "/participants",
                {
                    "expected_row_version": 1,
                    "character_id": str(uuid.uuid4()),
                    "participation_role": "guest",
                },
            ),
        ):
            assert actor.post_raw(
                base(s, sid, suffix), body, key=actor.fresh_key()
            ).status_code in (403, 404)


def test_a_session_of_another_campaign_is_indistinguishable_from_missing(s: ContentSetup) -> None:
    foreign = s.stranger.post_raw(
        f"/campaigns/{s.other_cid}/sessions", {"title": "Elsewhere"}, key=s.stranger.fresh_key()
    ).json()
    missing = str(uuid.uuid4())
    seen = set()
    for sid in (foreign["session_id"], missing):
        for suffix, body in (
            ("/start", {"expected_row_version": 1}),
            ("/end", {"expected_row_version": 1}),
            ("/log", {"entry": "x"}),
            (
                "/participants",
                {
                    "expected_row_version": 1,
                    "character_id": str(uuid.uuid4()),
                    "participation_role": "guest",
                },
            ),
        ):
            response = s.gm.post_raw(base(s, sid, suffix), body, key=s.gm.fresh_key())
            assert response.status_code == 404, (suffix, response.text)
            seen.add((response.json()["error"]["code"], response.json()["error"]["message"]))
    assert len(seen) == 1


def test_log_events_belong_to_the_campaign_timeline_and_a_branch_has_none(s: ContentSetup) -> None:
    clock_time = set_clock(s)
    session = new_session(s)
    sid = session["session_id"]
    assert post(s, sid, "/start", {}).status_code == 200
    assert post(s, sid, "/log", {"entry": "Parent only"}, versioned=False).status_code == 201
    branch_cid = _branch_campaign(s, clock_time)
    in_branch = s.connection.execute(
        text(
            "SELECT count(*) FROM narrative.events e JOIN narrative.event_types t "
            "ON t.event_type_id = e.event_type_id WHERE e.campaign_id = :c "
            "AND t.code = 'session_narrative'"
        ),
        {"c": branch_cid},
    ).scalar()
    assert in_branch == 0
    assert s.gm.get(f"/campaigns/{branch_cid}/sessions").json() == []


def test_the_database_allows_one_session_in_progress_and_same_world_participants(
    s: ContentSetup,
) -> None:
    from datetime import UTC, datetime, timedelta

    cid = uuid.UUID(s.cid)
    now = datetime.now(UTC)
    make_session(s.connection, cid, 1, started_at=now - timedelta(hours=1))
    with (
        pytest.raises(IntegrityError, match="ux_sessions_one_in_progress"),
        s.connection.begin_nested(),
    ):
        make_session(s.connection, cid, 2, started_at=now - timedelta(hours=2))
    done = make_session(
        s.connection, cid, 3, started_at=now - timedelta(hours=3), ended_at=now - timedelta(hours=2)
    )
    assert done is not None
    foreign = make_character(s.connection, s.other_world_id, name="Elsewhere")
    with pytest.raises(IntegrityError, match="belongs to world"), s.connection.begin_nested():
        s.connection.execute(
            text(
                "INSERT INTO campaign.session_participants (session_id, character_id, participation_role) "
                "VALUES (:s, :c, 'guest')"
            ),
            {"s": done, "c": foreign},
        )
