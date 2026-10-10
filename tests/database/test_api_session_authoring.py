"""Session definition endpoints (checkpoint 15.2D-1, migration 122)."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.factories import make_session

pytestmark = pytest.mark.database

SOON = (datetime.now(UTC) + timedelta(days=3)).replace(microsecond=0)


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def sessions_url(s: ContentSetup, suffix: str = "", cid: str | None = None) -> str:
    return f"/campaigns/{cid or s.cid}/sessions{suffix}"


def schedule(s: ContentSetup, **body: object) -> dict:
    response = s.gm.post_raw(sessions_url(s), {**body}, key=s.gm.fresh_key())
    assert response.status_code == 201, response.text
    return response.json()


def act(s: ContentSetup, session: dict, action: str, **body: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        sessions_url(s, f"/{session['session_id']}/{action}"),
        {"expected_row_version": session["row_version"], **body},
        key=s.gm.fresh_key(),
    )


def detail(s: ContentSetup, session_id: str, who: str = "gm") -> dict:
    actor = s.gm if who == "gm" else s.player
    response = actor.get(sessions_url(s, f"/{session_id}"))
    assert response.status_code == 200, response.text
    return response.json()


def test_schedule_assigns_consecutive_numbers_and_records_the_creator(s: ContentSetup) -> None:
    first = schedule(s, title="The Hollow Road", scheduled_for=SOON.isoformat(), summary="PLAN")
    second = schedule(s)
    assert set(first) == {"session_id", "session_number", "row_version", "created", "changed"}
    assert (first["session_number"], second["session_number"]) == (1, 2)
    assert first["row_version"] == 1 and first["created"] is True
    row = s.connection.execute(
        text(
            "SELECT created_by_user_id, scheduled_for, archived_at FROM campaign.sessions "
            "WHERE session_id = :s"
        ),
        {"s": first["session_id"]},
    ).one()
    assert row.created_by_user_id == s.gm.user_id and row.scheduled_for == SOON
    assert row.archived_at is None
    (audit, _) = s.audit("schedule_session")
    assert audit.changed_fields["sequence_number"] == 1
    assert "PLAN" not in str(audit.changed_fields) and "Hollow" not in str(audit.changed_fields)


@pytest.mark.parametrize(
    "body", [{"title": "x" * 5000}, {"summary": "x" * 50000}, {"scheduled_for": "not a date"}]
)
def test_invalid_bodies_are_refused_and_write_nothing(s: ContentSetup, body: dict) -> None:
    before = s.count("campaign.sessions")
    response = s.gm.post_raw(sessions_url(s), body, key=s.gm.fresh_key())
    assert response.status_code in (400, 422)
    assert s.count("campaign.sessions") == before


def test_play_status_is_derived_never_stored(s: ContentSetup) -> None:
    bare = schedule(s)
    planned = schedule(s, scheduled_for=SOON.isoformat())
    playing = make_session(
        s.connection, uuid.UUID(s.cid), 3, started_at=datetime.now(UTC) - timedelta(hours=1)
    )
    done = make_session(
        s.connection,
        uuid.UUID(s.cid),
        4,
        started_at=datetime.now(UTC) - timedelta(hours=3),
        ended_at=datetime.now(UTC) - timedelta(hours=1),
    )
    by_number = {i["session_number"]: i for i in s.gm.get(sessions_url(s)).json()}
    assert [by_number[n]["play_status"] for n in (1, 2, 3, 4)] == [
        "unscheduled",
        "scheduled",
        "in_progress",
        "completed",
    ]
    assert by_number[2]["scheduled_for"] is not None
    assert detail(s, planned["session_id"])["play_status"] == "scheduled"
    # Editors get the version and the actions; players do not.
    assert by_number[1]["available_actions"] == [
        "update",
        "start",
        "manage_participants",
        "archive",
    ]
    assert by_number[3]["available_actions"] == [
        "update",
        "manage_participants",
        "log",
        "end",
    ]  # cannot archive while played
    player_view = {i["session_number"]: i for i in s.player.get(sessions_url(s)).json()}
    assert player_view[1]["row_version"] is None and player_view[1]["available_actions"] is None
    assert str(playing) in {i["session_id"] for i in s.gm.get(sessions_url(s)).json()}
    assert str(done) in {i["session_id"] for i in s.gm.get(sessions_url(s)).json()}
    assert bare["session_number"] == 1


def test_players_and_strangers_cannot_write(s: ContentSetup) -> None:
    session = schedule(s)
    for actor in (s.player, s.stranger):
        assert actor.post_raw(
            sessions_url(s), {"title": "x"}, key=actor.fresh_key()
        ).status_code in (403, 404)
        assert actor.post_raw(
            sessions_url(s, f"/{session['session_id']}/archive"),
            {"expected_row_version": 1},
            key=actor.fresh_key(),
        ).status_code in (403, 404)


def test_update_changes_the_session_and_audits_a_bounded_diff(s: ContentSetup) -> None:
    session = schedule(s, title="Old")
    updated = act(
        s, session, "update", title="New", scheduled_for=SOON.isoformat(), summary="Recap SECRET"
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["row_version"] == 2 and updated.json()["changed"] is True
    view = detail(s, session["session_id"])
    assert (view["title"], view["summary"], view["row_version"]) == ("New", "Recap SECRET", 2)
    (audit,) = s.audit("update_session")
    assert "scheduled_for" in audit.changed_fields
    assert "Recap SECRET" not in str(audit.changed_fields) and "New" not in str(
        audit.changed_fields.get("title")
    )


def test_a_no_op_update_and_a_stale_one(s: ContentSetup) -> None:
    session = schedule(s, title="Same")
    same = act(s, session, "update", title="Same")
    assert same.status_code == 200 and same.json()["changed"] is False
    assert same.json()["row_version"] == 1 and s.audit("update_session") == []
    assert act(s, session, "update", title="Other").status_code == 200
    stale = act(s, session, "update", title="Third")
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"


def test_a_started_session_keeps_its_plan_but_can_be_retitled(s: ContentSetup) -> None:
    started = make_session(
        s.connection,
        uuid.UUID(s.cid),
        1,
        title="Live",
        started_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    view = detail(s, str(started))
    body = {"session_id": str(started), "row_version": view["row_version"]}
    retitled = act(s, body, "update", title="Live (renamed)")
    assert retitled.status_code == 200, retitled.text
    body["row_version"] = retitled.json()["row_version"]
    moved = act(s, body, "update", title="Live (renamed)", scheduled_for=SOON.isoformat())
    assert moved.status_code == 409 and moved.json()["error"]["code"] == "session_already_started"
    refused = act(s, body, "archive")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "session_in_progress"


def test_archive_hides_the_session_from_players_and_restore_brings_it_back(
    s: ContentSetup,
) -> None:
    session = schedule(s, title="Gone")
    archived = act(s, session, "archive", reason="cancelled")
    assert archived.status_code == 200 and archived.json()["row_version"] == 2
    assert s.player.get(sessions_url(s)).json() == []
    assert s.player.get(sessions_url(s, f"/{session['session_id']}")).status_code == 404
    gm_item = s.gm.get(sessions_url(s)).json()[0]
    assert gm_item["status_code"] == "archived" and gm_item["available_actions"] == ["restore"]
    assert detail(s, session["session_id"])["status_code"] == "archived"

    current = {"session_id": session["session_id"], "row_version": 2}
    assert act(s, current, "archive").status_code == 409
    closed = act(s, current, "update", title="x")
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "session_not_active"
    no_reason = s.gm.post_raw(
        sessions_url(s, f"/{session['session_id']}/restore"),
        {"expected_row_version": 2},
        key=s.gm.fresh_key(),
    )
    assert no_reason.status_code in (400, 422)
    restored = act(s, current, "restore", reason="back on")
    assert restored.status_code == 200 and restored.json()["row_version"] == 3
    assert [i["title"] for i in s.player.get(sessions_url(s)).json()] == ["Gone"]
    again = act(s, {"session_id": session["session_id"], "row_version": 3}, "restore", reason="x")
    assert again.status_code == 409 and again.json()["error"]["code"] == "session_not_archived"
    actions = [a.action for a in s.audit("archive_session")] + [
        a.action for a in s.audit("restore_session")
    ]
    assert actions == ["archived", "restored"]


def test_a_session_of_another_campaign_is_indistinguishable_from_missing(s: ContentSetup) -> None:
    foreign = s.stranger.post_raw(
        sessions_url(s, cid=s.other_cid), {"title": "Elsewhere"}, key=s.stranger.fresh_key()
    ).json()
    missing = {"session_id": str(uuid.uuid4()), "row_version": 1}
    seen = set()
    for target in (foreign, missing):
        for action, extra in (("update", {"title": "x"}), ("archive", {})):
            response = act(s, target, action, **extra)
            assert response.status_code == 404, (action, response.text)
            seen.add((response.json()["error"]["code"], response.json()["error"]["message"]))
    assert len(seen) == 1


def test_replay_and_conflict(s: ContentSetup) -> None:
    key = s.gm.fresh_key()
    first = s.gm.post_raw(sessions_url(s), {"title": "Once"}, key=key)
    again = s.gm.post_raw(sessions_url(s), {"title": "Once"}, key=key)
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    assert s.gm.post_raw(sessions_url(s), {"title": "Other"}, key=key).status_code == 409
    count = s.connection.execute(
        text("SELECT count(*) FROM campaign.sessions WHERE campaign_id = :c"), {"c": s.cid}
    ).scalar()
    assert count == 1


def test_a_failure_while_writing_leaves_nothing(
    s: ContentSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import Connection as Conn

    real_execute = Conn.execute

    def failing(self: Conn, statement: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if "INSERT INTO campaign.sessions" in str(statement):
            raise RuntimeError("injected failure")
        return real_execute(self, statement, *args, **kwargs)  # type: ignore[arg-type]

    tables = ("campaign.sessions", "audit.change_log", "security.idempotent_requests")
    before = {t: s.count(t) for t in tables}
    monkeypatch.setattr(Conn, "execute", failing)
    response = s.gm.post_raw(sessions_url(s), {"title": "Doomed"}, key=s.gm.fresh_key())
    monkeypatch.undo()
    assert response.status_code == 500
    assert before == {t: s.count(t) for t in tables}


def test_the_numbering_continues_after_gaps_and_archives(s: ContentSetup) -> None:
    make_session(s.connection, uuid.UUID(s.cid), 7, lifecycle_status_code="archived")
    assert schedule(s)["session_number"] == 8


def test_existing_sessions_keep_working_with_the_new_columns(s: ContentSetup) -> None:
    legacy = make_session(s.connection, uuid.UUID(s.cid), 1, title="Legacy")
    row = s.connection.execute(
        text(
            "SELECT row_version, scheduled_for, archived_at FROM campaign.sessions WHERE session_id = :s"
        ),
        {"s": legacy},
    ).one()
    assert (row.row_version, row.scheduled_for, row.archived_at) == (1, None, None)
    assert detail(s, str(legacy))["play_status"] == "unscheduled"
