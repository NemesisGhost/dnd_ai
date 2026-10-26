"""Optional clock cause and member-safe explanation (Phase 15 checkpoint CP-9b, revision 140).

Advances are recorded through the production route and read back through the explanation surfaces
the CP-9a tests use. The member-safe explanation lives in `narrative.clock_advance_details`, never
in the GM-only `narrative.events.details`.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times, _branch_campaign, _clock
from tests.database.test_api_event_explanations import (
    event_count,
    explanation,
    record_event,
    start_clock,
    world_event,
)

pytestmark = pytest.mark.database

PRIVATE = "PRIVATE-CAUSE-DETAILS-4417"
SAFE = "The caravan reached the pass at dusk."


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def advance(
    s: ContentSetup,
    time_id: str,
    version: int,
    *,
    cid: str | None = None,
    key: str | None = None,
    actor: Actor | None = None,
    **fields: object,
):  # type: ignore[no-untyped-def]
    who = actor or s.gm
    return who.post_raw(
        f"/campaigns/{cid or s.cid}/clock/advance",
        {"world_time_id": time_id, "expected_row_version": version, **fields},
        key=key or who.fresh_key(),
    )


def counts(s: ContentSetup) -> dict[str, int]:
    def one(sql: str) -> int:
        return int(s.connection.execute(text(sql)).scalar() or 0)

    return {
        "events": event_count(s),
        "causes": one("SELECT count(*) FROM narrative.event_causes"),
        "details": one("SELECT count(*) FROM narrative.clock_advance_details"),
        "audit": len(s.audit("advance_campaign_clock")),
        "version": int(_clock(s)["row_version"]),
    }


def details_row(s: ContentSetup, event_id: str) -> tuple[bool, str | None]:
    row = s.connection.execute(
        text("SELECT member_explanation FROM narrative.clock_advance_details WHERE event_id = :e"),
        {"e": event_id},
    ).one_or_none()
    return (row is not None, None if row is None else row.member_explanation)


def relations(s: ContentSetup, actor: Actor, event_id: str) -> dict[str, dict]:
    return {r["relation"]: r for r in explanation(s, actor, event_id)["relations"]}


def setup_cause(s: ContentSetup, times: Times) -> tuple[str, str]:
    """A started clock (year 1) and a recorded gameplay event at year 2 carrying private details."""
    start_clock(s, times, 1)
    return times.at(3), record_event(s, times.at(2), "The bridge falls", details=PRIVATE)


# --- delivered behaviour ------------------------------------------------------------------


def test_a_plain_advance_is_recorded_as_a_manual_advance(s: ContentSetup) -> None:
    times = Times(s)
    first = advance(s, times.at(1), 0)
    assert first.status_code == 200, first.text
    # The receipt stays minimal: ids, version and flags only.
    assert set(first.json()) == {"world_time_id", "event_id", "row_version", "created", "changed"}
    shown = explanation(s, s.player, first.json()["event_id"])
    assert shown["advance_origin"] == "manual" and shown["member_explanation"] is None
    assert details_row(s, first.json()["event_id"]) == (True, None)


def test_a_cause_and_explanation_are_kept_apart_from_the_chain_and_from_gm_details(
    s: ContentSetup,
) -> None:
    times = Times(s)
    target, cause = setup_cause(s, times)
    previous = _clock(s)["last_event_id"]
    response = advance(s, target, 1, cause_event_id=cause, explanation=f"  {SAFE}  ")
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert set(receipt) == {"world_time_id", "event_id", "row_version", "created", "changed"}
    assert SAFE not in response.text and cause not in response.text
    event = receipt["event_id"]
    assert details_row(s, event) == (True, SAFE)
    # GM-only `details` is untouched; the explanation is not stored there.
    assert (
        s.connection.execute(
            text("SELECT details FROM narrative.events WHERE event_id = :e"), {"e": event}
        ).scalar()
        is None
    )
    # Two cause rows: the chain row (previous clock event) and the gameplay cause.
    causes = {
        str(r.cause_event_id)
        for r in s.connection.execute(
            text("SELECT cause_event_id FROM narrative.event_causes WHERE event_id = :e"),
            {"e": event},
        )
    }
    assert causes == {str(previous), cause}
    for actor in (s.gm, s.player):
        shown = explanation(s, actor, event)
        assert shown["advance_origin"] == "event_cause"
        assert shown["member_explanation"] == SAFE
        labelled = relations(s, actor, event)
        assert set(labelled) == {"follows_previous_clock_change", "caused_by"}
        assert labelled["follows_previous_clock_change"]["event"]["entity_id"] == str(previous)
        assert labelled["caused_by"]["event"]["entity_id"] == cause
    # Audit holds no explanation text.
    assert SAFE not in str(s.audit("advance_campaign_clock")[-1].changed_fields)


def test_the_two_inputs_are_independent(s: ContentSetup) -> None:
    times = Times(s)
    target, cause = setup_cause(s, times)
    only_cause = advance(s, target, 1, cause_event_id=cause)
    assert only_cause.status_code == 200, only_cause.text
    shown = explanation(s, s.player, only_cause.json()["event_id"])
    assert shown["advance_origin"] == "event_cause" and shown["member_explanation"] is None
    only_text = advance(s, times.at(5), 2, explanation=SAFE)
    assert only_text.status_code == 200, only_text.text
    shown = explanation(s, s.player, only_text.json()["event_id"])
    # Words without a gameplay cause are still a manual advance.
    assert shown["advance_origin"] == "manual" and shown["member_explanation"] == SAFE
    assert [r["relation"] for r in shown["relations"]] == ["follows_previous_clock_change"]
    blank = advance(s, times.at(6), 3, explanation="   ", cause_event_id=None)
    assert blank.status_code == 200
    assert details_row(s, blank.json()["event_id"]) == (True, None)


def test_a_cause_at_the_new_time_exactly_is_allowed(s: ContentSetup) -> None:
    times = Times(s)
    start_clock(s, times, 1)
    target = times.at(3)
    cause = record_event(s, target, "Arrival")
    assert advance(s, target, 1, cause_event_id=cause).status_code == 200


def test_a_non_clock_event_caused_by_a_clock_event_keeps_its_caused_by_label(
    s: ContentSetup,
) -> None:
    times = Times(s)
    target, cause = setup_cause(s, times)
    advanced = advance(s, target, 1, cause_event_id=cause).json()["event_id"]
    other = record_event(s, times.at(4), "Because of the new time")
    s.connection.execute(
        text("INSERT INTO narrative.event_causes (event_id, cause_event_id) VALUES (:e, :c)"),
        {"e": other, "c": advanced},
    )
    (recorded,) = explanation(s, s.gm, other)["relations"]
    assert recorded["relation"] == "caused_by"
    # The cause stays labelled as a cause; the correction reads as a correction.
    corrected = s.gm.post_raw(
        f"/campaigns/{s.cid}/clock/correct",
        {
            "world_time_id": times.at(9),
            "expected_row_version": _clock(s)["row_version"],
            "corrects_event_id": advanced,
        },
        key=s.gm.fresh_key(),
    )
    assert corrected.status_code == 200, corrected.text
    on_correction = explanation(s, s.player, corrected.json()["event_id"])
    assert [r["relation"] for r in on_correction["relations"]] == ["corrects_clock_change"]
    assert on_correction["advance_origin"] is None and on_correction["member_explanation"] is None
    assert [r["relation"] for r in explanation(s, s.gm, advanced)["relations"]] == [
        "follows_previous_clock_change",
        "caused_by",
        "corrected_by_clock_change",
    ]


# --- validation ---------------------------------------------------------------------------


def invalid_event_ids(s: ContentSetup, times: Times) -> dict[str, str]:
    """Candidate causes that must all be refused with the same safe answer."""
    clock_event = _clock(s)["last_event_id"]
    voided = record_event(s, times.at(2), "Voided one")
    done = s.gm.post_raw(
        f"/campaigns/{s.cid}/events/{voided}/void",
        {"reason": "oops"},
        key=s.gm.fresh_key(),
    )
    assert done.status_code == 200, done.text
    corrected = record_event(s, times.at(2), "Corrected one")
    fixed = s.gm.post_raw(
        f"/campaigns/{s.cid}/events/{corrected}/correct",
        {
            "reason": "wrong",
            "replacement": {
                "event_type_code": "other",
                "name": "Right one",
                "world_time_id": times.at(2),
            },
        },
        key=s.gm.fresh_key(),
    )
    assert fixed.status_code == 200, fixed.text
    foreign = _foreign_event(s)
    return {
        "missing": str(uuid.uuid4()),
        "clock": str(clock_event),
        "voided": voided,
        "corrected": corrected,
        "foreign": foreign,
    }


def _foreign_event(s: ContentSetup) -> str:
    calendar = s.stranger.post_raw(
        f"/worlds/{s.other_world_id}/calendars",
        {
            "name": "Other",
            "description": None,
            "days_per_week": None,
            "epoch_label": None,
            "months": [{"name": "Only", "day_count": 100}],
        },
        key=s.stranger.fresh_key(),
    ).json()["calendar_id"]
    time_id = s.stranger.post_raw(
        f"/campaigns/{s.other_cid}/world-times",
        {"calendar_id": calendar, "year": 1},
        key=s.stranger.fresh_key(),
    ).json()["world_time_id"]
    response = s.stranger.post_raw(
        f"/campaigns/{s.other_cid}/events",
        {"world_time_id": time_id, "event_type_code": "other", "name": "Foreign"},
        key=s.stranger.fresh_key(),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["event_id"])


def test_an_ineligible_cause_is_refused_alike_and_leaves_nothing_behind(s: ContentSetup) -> None:
    times = Times(s)
    start_clock(s, times, 1)
    candidates = invalid_event_ids(s, times)
    before = counts(s)
    target = times.at(5)
    for reason, candidate in candidates.items():
        refused = advance(s, target, before["version"], cause_event_id=candidate, explanation=SAFE)
        assert refused.status_code == 422, (reason, refused.text)
        assert refused.json()["error"]["code"] == "clock_cause_invalid", reason
        # One answer for every reason: nothing about the candidate is echoed back.
        assert candidate not in refused.text and "Foreign" not in refused.text
        assert counts(s) == before, reason
    assert _clock(s)["current"]["display"].endswith("Year 1")


def test_a_cause_after_the_new_time_is_refused(s: ContentSetup) -> None:
    times = Times(s)
    start_clock(s, times, 1)
    later = record_event(s, times.at(8), "Much later")
    before = counts(s)
    refused = advance(s, times.at(3), 1, cause_event_id=later)
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "clock_cause_after_target"
    assert counts(s) == before


def test_an_overlong_explanation_is_a_validation_error_and_writes_nothing(
    s: ContentSetup,
) -> None:
    times = Times(s)
    start_clock(s, times, 1)
    before = counts(s)
    refused = advance(s, times.at(3), 1, explanation="x" * 501)
    assert refused.status_code == 422
    assert counts(s) == before
    assert advance(s, times.at(3), 1, explanation="x" * 500).status_code == 200


def test_the_strictly_later_rule_and_stale_version_still_apply_with_a_cause(
    s: ContentSetup,
) -> None:
    times = Times(s)
    target, cause = setup_cause(s, times)
    before = counts(s)
    same = advance(s, times.at(1), 1, cause_event_id=cause)
    assert same.status_code == 409 and same.json()["error"]["code"] == "clock_not_advanced"
    stale = advance(s, target, 0, cause_event_id=cause, explanation=SAFE)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"
    assert counts(s) == before


def test_a_branch_can_not_name_its_parents_events_but_can_name_its_own(s: ContentSetup) -> None:
    times = Times(s)
    y1, y2, y3, y5 = times.at(1), times.at(2), times.at(3), times.at(5)
    assert advance(s, y1, 0).status_code == 200
    parent_event = record_event(s, y1, "Parent history")
    parent_later = record_event(s, y2, "Parent later")
    branch = _branch_campaign(s, y1)
    refused = advance(s, y3, 0, cid=branch, cause_event_id=parent_event)
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "clock_cause_invalid"
    assert advance(s, y3, 0, cid=branch, cause_event_id=parent_later).status_code == 422
    own = s.gm.post_raw(
        f"/campaigns/{branch}/events",
        {"world_time_id": y3, "event_type_code": "other", "name": "Branch event"},
        key=s.gm.fresh_key(),
    )
    assert own.status_code == 201, own.text
    allowed = advance(s, y5, 0, cid=branch, cause_event_id=own.json()["event_id"])
    assert allowed.status_code == 200, allowed.text
    # The parent cannot name the branch's event either.
    assert advance(s, y5, 1, cause_event_id=own.json()["event_id"]).status_code == 422


def test_only_a_campaign_gm_may_name_a_cause(s: ContentSetup) -> None:
    times = Times(s)
    target, cause = setup_cause(s, times)
    before = counts(s)
    assert advance(s, target, 1, actor=s.player, cause_event_id=cause).status_code == 403
    assert advance(s, target, 1, actor=s.stranger, cause_event_id=cause).status_code == 404
    assert counts(s) == before


# --- idempotency --------------------------------------------------------------------------


def test_an_identical_retry_replays_and_a_changed_input_conflicts(s: ContentSetup) -> None:
    times = Times(s)
    target, cause = setup_cause(s, times)
    other_cause = record_event(s, times.at(2), "Another")
    key = s.gm.fresh_key()
    first = advance(s, target, 1, key=key, cause_event_id=cause, explanation=SAFE)
    again = advance(s, target, 1, key=key, cause_event_id=cause, explanation=SAFE)
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert counts(s)["details"] == 2  # the starting advance and this one
    for changed in (
        {"cause_event_id": other_cause, "explanation": SAFE},
        {"cause_event_id": cause, "explanation": "Something else"},
        {"cause_event_id": cause},
        {"explanation": SAFE},
        {},
    ):
        conflict = advance(s, target, 1, key=key, **changed)
        assert conflict.status_code == 409, changed
    assert counts(s)["version"] == 2


# --- audience -----------------------------------------------------------------------------


def test_the_explanation_needs_event_access_and_gm_private_text_never_reaches_members(
    s: ContentSetup,
) -> None:
    times = Times(s)
    target, cause = setup_cause(s, times)
    event = advance(s, target, 1, cause_event_id=cause, explanation=SAFE).json()["event_id"]
    member = world_event(s, s.player, event)
    assert member.status_code == 200, member.text
    assert SAFE in member.text and PRIVATE not in member.text
    summary = s.player.get(f"/campaigns/{s.cid}/summary")
    assert summary.status_code == 200, summary.text
    assert PRIVATE not in summary.text
    recent = {e["event_id"]: e for e in summary.json()["recent_events"]}
    assert recent[event]["explanation"]["member_explanation"] == SAFE
    assert recent[event]["details"] is None
    # No event access, no explanation: the same refusal as any unreadable event.
    assert world_event(s, s.stranger, event).status_code == 404
    from tests.database.test_api_event_explanations import deny_entity

    deny_entity(s, event)
    denied = world_event(s, s.player, event)
    assert denied.status_code == 404 and SAFE not in denied.text
    assert SAFE not in s.player.get(f"/campaigns/{s.cid}/summary").text


def test_a_hidden_cause_leaks_no_id_name_or_link(s: ContentSetup) -> None:
    times = Times(s)
    target, cause = setup_cause(s, times)
    event = advance(s, target, 1, cause_event_id=cause).json()["event_id"]
    from tests.database.test_api_event_explanations import deny_entity

    deny_entity(s, cause)
    shown = world_event(s, s.player, event)
    assert shown.status_code == 200, shown.text
    assert cause not in shown.text and "The bridge falls" not in shown.text
    assert PRIVATE not in shown.text
    labelled = {r["relation"] for r in shown.json()["explanation"]["relations"]}
    assert "caused_by" not in labelled
    # The advance is still known to have had a gameplay cause, never mislabelled manual.
    assert shown.json()["explanation"]["advance_origin"] == "event_cause"


def test_earlier_advances_and_their_private_text_stay_unlabelled_and_private(
    s: ContentSetup,
) -> None:
    times = Times(s)
    start_clock(s, times, 1)
    legacy = _clock(s)["last_event_id"]
    # An advance recorded before the contract had no details row; remove the one the route made.
    s.connection.execute(
        text("DELETE FROM narrative.clock_advance_details WHERE event_id = :e"), {"e": legacy}
    )
    s.connection.execute(
        text("INSERT INTO narrative.event_causes (event_id, cause_description) VALUES (:e, :d)"),
        {"e": legacy, "d": PRIVATE},
    )
    for actor in (s.gm, s.player):
        shown = explanation(s, actor, legacy)
        assert shown["advance_origin"] is None and shown["member_explanation"] is None
    member = world_event(s, s.player, legacy)
    assert PRIVATE not in member.text
    assert PRIVATE not in s.player.get(f"/campaigns/{s.cid}/summary").text


# --- picker -------------------------------------------------------------------------------


def choices(s: ContentSetup, actor: Actor | None = None, cid: str | None = None, **q: str):  # type: ignore[no-untyped-def]
    query = "&".join(f"{k}={v}" for k, v in q.items())
    return (actor or s.gm).get(f"/campaigns/{cid or s.cid}/clock/cause-choices?{query}")


def test_the_picker_lists_only_events_the_advance_could_name(s: ContentSetup) -> None:
    times = Times(s)
    year1 = start_clock(s, times, 1)
    empty = choices(s)
    assert empty.status_code == 200 and empty.json() == {"choices": []}
    early = record_event(s, times.at(2), "Early event")
    late = record_event(s, times.at(7), "Late event")
    voided = record_event(s, times.at(2), "Voided event")
    s.gm.post_raw(f"/campaigns/{s.cid}/events/{voided}/void", {"reason": "x"}, key=s.gm.fresh_key())
    parent_only = record_event(s, times.at(1), "Parent event")
    branch = _branch_campaign(s, year1)
    listed = choices(s).json()["choices"]
    names = [c["name"] for c in listed]
    assert names == ["Late event", "Early event", "Parent event"]
    assert {c["event_id"] for c in listed} == {early, late, parent_only}
    assert all(c["in_world_time"] for c in listed)
    bounded = choices(s, world_time_id=times.at(3)).json()["choices"]
    assert [c["name"] for c in bounded] == ["Early event", "Parent event"]
    searched = choices(s, q="late").json()["choices"]
    assert [c["name"] for c in searched] == ["Late event"]
    assert choices(s, q="%25").json()["choices"] == []
    assert choices(s, cid=branch).json() == {"choices": []}
    assert choices(s, actor=s.player).status_code == 403
    assert choices(s, actor=s.stranger).status_code == 404


# --- database -----------------------------------------------------------------------------


def test_the_details_table_accepts_only_advance_events_and_is_append_only(
    s: ContentSetup,
) -> None:
    times = Times(s)
    start_clock(s, times, 1)
    other = record_event(s, times.at(1), "Not an advance")
    with pytest.raises(DBAPIError, match="not a time_advanced event"), s.connection.begin_nested():
        s.connection.execute(
            text("INSERT INTO narrative.clock_advance_details (event_id) VALUES (:e)"),
            {"e": other},
        )
    advanced = _clock(s)["last_event_id"]
    with pytest.raises(DBAPIError, match="append-only"), s.connection.begin_nested():
        s.connection.execute(
            text(
                "UPDATE narrative.clock_advance_details SET member_explanation = 'x' "
                "WHERE event_id = :e"
            ),
            {"e": advanced},
        )
    s.connection.execute(
        text("DELETE FROM narrative.clock_advance_details WHERE event_id = :e"), {"e": advanced}
    )
    with pytest.raises(DBAPIError, match="ck_clock_advance_details"), s.connection.begin_nested():
        s.connection.execute(
            text(
                "INSERT INTO narrative.clock_advance_details (event_id, member_explanation) "
                "SELECT event_id, '' FROM narrative.events WHERE event_id = :e"
            ),
            {"e": advanced},
        )
