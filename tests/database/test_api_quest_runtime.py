"""Quest runtime: activate, progress, finish, suspend and abandon (checkpoint 15.2E-2b)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times, _advance
from tests.database.test_api_quest_completion import ids, quest_with_objectives
from tests.factories import make_campaign_party, make_party

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def published_quest(s: ContentSetup, objectives: int = 2) -> dict:
    quest = quest_with_objectives(s, objectives)
    s.publish(quest["quest_id"], quest["row_version"])
    return quest


def set_clock(s: ContentSetup) -> str:
    time_id = Times(s).at(1)
    assert _advance(s, time_id, 0).status_code == 200
    return time_id


def runtime(s: ContentSetup, quest_id: str, action: str, expected: str | None, **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        f"/campaigns/{s.cid}/quests/{quest_id}/{action}",
        {"expected_status": expected, **extra},
        key=s.gm.fresh_key(),
    )


def objective(
    s: ContentSetup, objective_id: str, status: str, expected: str | None, **extra: object
):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        f"/campaigns/{s.cid}/quests/objectives/{objective_id}/status",
        {"new_status": status, "expected_status": expected, **extra},
        key=s.gm.fresh_key(),
    )


def progress(s: ContentSetup, quest_id: str) -> dict:
    response = s.gm.get(f"/campaigns/{s.cid}/quests/{quest_id}/progress")
    assert response.status_code == 200, response.text
    return response.json()


def campaign_scope(view: dict) -> dict:
    return next(scope for scope in view["scopes"] if scope["party_id"] is None)


def code(response) -> str:  # type: ignore[no-untyped-def]
    return str(response.json()["error"]["code"])


def event_types(s: ContentSetup) -> list[str]:
    return list(
        s.connection.execute(
            text("""
                SELECT et.code FROM narrative.events ev
                JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
                JOIN audit.change_log cl ON cl.event_id = ev.event_id
                WHERE ev.campaign_id = :c AND et.code <> 'time_advanced'
                ORDER BY cl.change_log_id
            """),
            {"c": s.cid},
        ).scalars()
    )


def test_a_quest_runs_from_activation_to_completion(s: ContentSetup) -> None:
    quest = published_quest(s)
    qid = quest["quest_id"]
    clock = set_clock(s)
    before = progress(s, qid)
    assert campaign_scope(before)["status"] is None
    assert campaign_scope(before)["actions"] == ["activate"]

    assert runtime(s, qid, "activate", None).status_code == 200
    assert campaign_scope(progress(s, qid))["actions"] == ["complete", "fail", "suspend", "abandon"]
    assert runtime(s, qid, "suspend", "active").status_code == 200
    assert runtime(s, qid, "resume", "suspended").status_code == 200
    done = runtime(s, qid, "complete", "active", note="GM only: the amulet was fake")
    assert done.status_code == 200
    assert done.json()["previous_status"] == "active" and done.json()["status"] == "completed"
    view = progress(s, qid)
    assert campaign_scope(view)["status"] == "completed" and campaign_scope(view)["actions"] == []
    assert event_types(s) == [
        "quest_activated",
        "quest_suspended",
        "quest_resumed",
        "quest_completed",
    ]
    effects = s.connection.execute(
        text("""
            SELECT target_component, previous_value, new_value, effective_world_time_id
            FROM narrative.event_effects ef
            JOIN narrative.events ev ON ev.event_id = ef.event_id
            JOIN audit.change_log cl ON cl.event_id = ev.event_id
            WHERE ev.campaign_id = :c AND ef.target_entity_id = :q ORDER BY cl.change_log_id
        """),
        {"c": s.cid, "q": qid},
    ).all()
    assert [(e.previous_value, e.new_value) for e in effects] == [
        (None, "active"),
        ("active", "suspended"),
        ("suspended", "active"),
        ("active", "completed"),
    ]
    assert all(str(e.effective_world_time_id) == clock for e in effects)
    audit = s.audit("quest_complete")
    assert len(audit) == 1 and audit[0].changed_fields["quest_status"]["to"] == "completed"
    assert "amulet" not in str(audit[0].changed_fields)
    assert [a.action for a in s.audit("quest_activate")] == ["created"]


def test_the_transition_matrix_refuses_what_does_not_apply(s: ContentSetup) -> None:
    qid = published_quest(s)["quest_id"]
    set_clock(s)
    for action in ("complete", "fail", "suspend", "resume", "abandon"):
        response = runtime(s, qid, action, None)
        assert response.status_code == 409 and code(response) == "quest_transition_invalid", action
    assert runtime(s, qid, "activate", None).status_code == 200
    again = runtime(s, qid, "activate", "active")
    assert again.status_code == 409 and code(again) == "quest_transition_invalid"
    resume = runtime(s, qid, "resume", "active")
    assert resume.status_code == 409 and code(resume) == "quest_transition_invalid"
    assert runtime(s, qid, "fail", "active").status_code == 200
    for action in ("activate", "complete", "suspend", "resume", "abandon", "fail"):
        response = runtime(s, qid, action, "failed")
        assert response.status_code == 409 and code(response) == "quest_transition_invalid", action
    assert event_types(s) == ["quest_activated", "quest_failed"]


def test_a_stale_expected_status_is_refused_and_nothing_changes(s: ContentSetup) -> None:
    qid = published_quest(s)["quest_id"]
    set_clock(s)
    assert runtime(s, qid, "activate", None).status_code == 200
    stale = runtime(s, qid, "suspend", None)
    assert stale.status_code == 409 and code(stale) == "stale_write"
    wrong = runtime(s, qid, "suspend", "suspended")
    assert wrong.status_code == 409 and code(wrong) == "stale_write"
    assert campaign_scope(progress(s, qid))["status"] == "active"
    assert event_types(s) == ["quest_activated"]


def test_only_a_published_quest_of_this_world_can_run(s: ContentSetup) -> None:
    draft = quest_with_objectives(s, 1)
    other = published_quest(s)
    set_clock(s)
    assert runtime(s, draft["quest_id"], "activate", None).status_code == 404
    assert runtime(s, str(uuid.uuid4()), "activate", None).status_code == 404
    # A quest of another world is the same 404.
    foreign = s.stranger.post(
        s.url("quests", s.other_cid),
        {"name": "Elsewhere", "summary": None},
        key=s.stranger.fresh_key(),
    ).json()
    assert runtime(s, foreign["quest_id"], "activate", None).status_code == 404
    assert s.gm.get(f"/campaigns/{s.cid}/quests/{draft['quest_id']}/progress").status_code == 200
    assert s.gm.get(f"/campaigns/{s.cid}/quests/{foreign['quest_id']}/progress").status_code == 404
    assert event_types(s) == []
    assert runtime(s, other["quest_id"], "activate", None).status_code == 200


def test_time_comes_from_the_clock_or_the_request(s: ContentSetup) -> None:
    qid = published_quest(s)["quest_id"]
    needs = runtime(s, qid, "activate", None)
    assert needs.status_code == 409 and code(needs) == "clock_required"
    explicit = Times(s).at(3)
    assert runtime(s, qid, "activate", None, world_time_id=explicit).status_code == 200
    foreign = Times(s).at(4, s.other_cid) if False else str(uuid.uuid4())
    bad = runtime(s, qid, "suspend", "active", world_time_id=foreign)
    assert bad.status_code == 400
    assert event_types(s) == ["quest_activated"]


def test_progress_is_kept_per_party(s: ContentSetup) -> None:
    qid = published_quest(s)["quest_id"]
    set_clock(s)
    world = s.world_id
    red = make_party(s.connection, world, "Red")
    blue = make_party(s.connection, world, "Blue")
    stranger_party = make_party(s.connection, world, "Not in this campaign")
    make_campaign_party(s.connection, uuid.UUID(s.cid), red)
    make_campaign_party(s.connection, uuid.UUID(s.cid), blue)
    assert runtime(s, qid, "activate", None, party_id=str(red)).status_code == 200
    view = progress(s, qid)
    by_party = {scope["party_name"]: scope for scope in view["scopes"]}
    assert by_party["Red"]["status"] == "active"
    assert by_party["Blue"]["status"] is None and by_party[None]["status"] is None
    assert runtime(s, qid, "activate", None, party_id=str(blue)).status_code == 200
    assert runtime(s, qid, "complete", "active", party_id=str(red)).status_code == 200
    by_party = {scope["party_name"]: scope for scope in progress(s, qid)["scopes"]}
    assert by_party["Red"]["status"] == "completed" and by_party["Blue"]["status"] == "active"
    assert runtime(s, qid, "activate", None, party_id=str(stranger_party)).status_code == 404


def test_objectives_move_only_while_the_quest_is_active(s: ContentSetup) -> None:
    quest = published_quest(s)
    qid = quest["quest_id"]
    first, second = ids(quest)
    set_clock(s)
    early = objective(s, first, "active", None)
    assert early.status_code == 409 and code(early) == "quest_not_active"
    assert runtime(s, qid, "activate", None).status_code == 200

    assert objective(s, first, "active", None).status_code == 200
    assert objective(s, first, "completed", "active").status_code == 200
    assert objective(s, second, "skipped", None).status_code == 200
    view = campaign_scope(progress(s, qid))
    statuses = {o["quest_objective_id"]: o["status"] for o in view["objectives"]}
    assert statuses == {first: "completed", second: "skipped"}
    assert view["all_required_complete"] is False  # one required objective was skipped
    for target in ("active", "failed"):
        response = objective(s, first, target, "completed")
        assert response.status_code == 409 and code(response) == "objective_transition_invalid"
    stale = objective(s, second, "completed", "active")
    assert stale.status_code == 409 and code(stale) == "stale_write"

    assert runtime(s, qid, "suspend", "active").status_code == 200
    paused = objective(s, second, "completed", "skipped")
    assert paused.status_code == 409 and code(paused) == "quest_not_active"
    assert [e for e in event_types(s) if e.startswith("objective")] == [
        "objective_activated",
        "objective_completed",
        "objective_skipped",
    ]


def test_all_required_complete_is_a_hint_not_an_automatic_completion(s: ContentSetup) -> None:
    quest = published_quest(s)
    qid = quest["quest_id"]
    set_clock(s)
    assert runtime(s, qid, "activate", None).status_code == 200
    for oid in ids(quest):
        assert objective(s, oid, "completed", None).status_code == 200
    scope = campaign_scope(progress(s, qid))
    assert scope["all_required_complete"] is True and scope["status"] == "active"
    assert "quest_completed" not in event_types(s)


def test_the_adapter_advance_route_respects_a_finished_quest(s: ContentSetup) -> None:
    quest = published_quest(s)
    qid = quest["quest_id"]
    oid = ids(quest)[0]
    time_id = set_clock(s)
    assert runtime(s, qid, "activate", None).status_code == 200
    assert runtime(s, qid, "suspend", "active").status_code == 200
    advance = s.gm.post_raw(
        f"/campaigns/{s.cid}/quests/objectives/{oid}/advance",
        {"world_time_id": time_id, "new_status_code": "completed"},
        key=s.gm.fresh_key(),
    )
    assert advance.status_code == 409 and code(advance) == "quest_not_active"
    assert runtime(s, qid, "resume", "suspended").status_code == 200
    ok = s.gm.post_raw(
        f"/campaigns/{s.cid}/quests/objectives/{oid}/advance",
        {"world_time_id": time_id, "new_status_code": "completed"},
        key=s.gm.fresh_key(),
    )
    assert ok.status_code == 200, ok.text
    # The new command sees what the adapter route wrote.
    again = objective(s, oid, "failed", "completed")
    assert again.status_code == 409 and code(again) == "objective_transition_invalid"


def test_an_untracked_quest_still_takes_adapter_progress(s: ContentSetup) -> None:
    quest = published_quest(s)
    time_id = set_clock(s)
    oid = ids(quest)[0]
    ok = s.gm.post_raw(
        f"/campaigns/{s.cid}/quests/objectives/{oid}/advance",
        {"world_time_id": time_id, "new_status_code": "completed"},
        key=s.gm.fresh_key(),
    )
    assert ok.status_code == 200, ok.text


def test_authority_replay_and_audit(s: ContentSetup) -> None:
    qid = published_quest(s)["quest_id"]
    set_clock(s)
    denied = s.player.post_raw(
        f"/campaigns/{s.cid}/quests/{qid}/activate",
        {"expected_status": None},
        key=s.player.fresh_key(),
    )
    assert denied.status_code == 403
    assert s.player.get(f"/campaigns/{s.cid}/quests/{qid}/progress").status_code == 403
    key = s.gm.fresh_key()
    path = f"/campaigns/{s.cid}/quests/{qid}/activate"
    first = s.gm.post_raw(path, {"expected_status": None}, key=key)
    replay = s.gm.post_raw(path, {"expected_status": None}, key=key)
    assert first.status_code == replay.status_code == 200 and first.json() == replay.json()
    assert event_types(s) == ["quest_activated"]
    assert len(s.audit("quest_activate")) == 1
    missing = s.gm.post_raw(path, {}, key=s.gm.fresh_key())
    assert missing.status_code == 422


def test_correcting_a_quest_event_restores_the_earlier_status(s: ContentSetup) -> None:
    quest = published_quest(s)
    qid = quest["quest_id"]
    oid = ids(quest)[0]
    set_clock(s)
    assert runtime(s, qid, "activate", None).status_code == 200
    assert objective(s, oid, "completed", None).status_code == 200
    completed = runtime(s, qid, "complete", "active").json()["event_id"]

    def void(event_id: str, reason: str = "Marked too early"):  # type: ignore[no-untyped-def]
        return s.gm.post_raw(
            f"/campaigns/{s.cid}/events/{event_id}/void", {"reason": reason}, key=s.gm.fresh_key()
        )

    voided = void(completed)
    assert voided.status_code == 200, voided.text
    assert campaign_scope(progress(s, qid))["status"] == "active"
    # The objective event cannot be undone any more than its quest-level state allows:
    # undoing it is allowed because nothing wrote the objective since.
    objective_event = s.connection.execute(
        text("""
            SELECT ef.event_id FROM narrative.event_effects ef
            JOIN narrative.events ev ON ev.event_id = ef.event_id
            WHERE ef.target_quest_objective_id = :o AND ev.campaign_id = :c
              AND ev.event_id NOT IN (SELECT correcting_event_id FROM narrative.event_corrections)
        """),
        {"o": oid, "c": s.cid},
    ).scalar()
    voided = void(str(objective_event))
    assert voided.status_code == 200, voided.text
    scope = campaign_scope(progress(s, qid))
    assert [o["status"] for o in scope["objectives"] if o["quest_objective_id"] == oid] == [None]


def test_correcting_the_first_activation_removes_the_state_it_created(s: ContentSetup) -> None:
    qid = published_quest(s)["quest_id"]
    set_clock(s)
    activated = runtime(s, qid, "activate", None).json()["event_id"]
    voided = s.gm.post_raw(
        f"/campaigns/{s.cid}/events/{activated}/void",
        {"reason": "Wrong quest"},
        key=s.gm.fresh_key(),
    )
    assert voided.status_code == 200, voided.text
    scope = campaign_scope(progress(s, qid))
    assert scope["status"] is None and scope["actions"] == ["activate"]
    # The quest can be activated afresh.
    assert runtime(s, qid, "activate", None).status_code == 200


def test_a_correction_is_refused_once_the_state_moved_on(s: ContentSetup) -> None:
    qid = published_quest(s)["quest_id"]
    set_clock(s)
    first = runtime(s, qid, "activate", None).json()["event_id"]
    assert runtime(s, qid, "suspend", "active").status_code == 200
    refused = s.gm.post_raw(
        f"/campaigns/{s.cid}/events/{first}/void", {"reason": "Oops"}, key=s.gm.fresh_key()
    )
    assert refused.status_code == 409 and code(refused) == "correction_not_reversible"
    assert campaign_scope(progress(s, qid))["status"] == "suspended"


def test_an_archived_or_unpublished_quest_stops_running(s: ContentSetup) -> None:
    quest = published_quest(s)
    qid = quest["quest_id"]
    set_clock(s)
    assert runtime(s, qid, "activate", None).status_code == 200
    s.set_status(qid, canon="draft")
    refused = runtime(s, qid, "complete", "active")
    assert refused.status_code == 404
    assert campaign_scope(progress(s, qid))["actions"] == []
    assert progress(s, qid)["published"] is False
