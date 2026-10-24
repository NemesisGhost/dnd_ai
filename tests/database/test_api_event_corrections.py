"""Event void and correction (checkpoint 15.2E-1, migration 124)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.commands.character_state import _adjust_hit_points_impl
from dnd_ai.domain.access import FOUNDRY_ACCESS_AUTH_METHOD, AuthenticatedPrincipal
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times, _advance, _branch_campaign

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def events_url(s: ContentSetup, event_id: str, suffix: str = "", cid: str | None = None) -> str:
    return f"/campaigns/{cid or s.cid}/events/{event_id}{suffix}"


def record(s: ContentSetup, time_id: str, name: str = "The door opens", **extra: object) -> str:
    response = s.gm.post_raw(
        f"/campaigns/{s.cid}/events",
        {"world_time_id": time_id, "event_type_code": "other", "name": name, **extra},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 201, response.text
    return response.json()["event_id"]


def void(s: ContentSetup, event_id: str, reason: str = "Recorded by mistake", **kw: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        events_url(s, event_id, "/void"),
        {"reason": reason},
        key=s.gm.fresh_key(),
        **kw,  # type: ignore[arg-type]
    )


def correct(s: ContentSetup, event_id: str, replacement: dict, reason: str = "Wrong detail"):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        events_url(s, event_id, "/correct"),
        {"reason": reason, "replacement": replacement},
        key=s.gm.fresh_key(),
    )


def status_of(s: ContentSetup, event_id: str) -> str:
    return str(
        s.connection.execute(
            text(
                "SELECT es.code FROM narrative.events e JOIN narrative.event_statuses es "
                "ON es.event_status_id = e.event_status_id WHERE e.event_id = :e"
            ),
            {"e": event_id},
        ).scalar()
    )


def published_pc(s: ContentSetup, name: str = "Aldric") -> str:
    species = s.gm.get(s.url("player-characters/options")).json()["species"][0]["species_id"]
    created = s.gm.post(
        s.url("player-characters"),
        {"name": name, "species_id": species, "size_category": "medium"},
        key=s.gm.fresh_key(),
    ).json()
    s.publish(created["player_character_id"], created["row_version"])
    return created["player_character_id"]


def hp_state(s: ContentSetup, character: str) -> tuple[int, str | None]:
    row = s.connection.execute(
        text(
            "SELECT cs.current_hit_points, cs.last_event_id FROM campaign.character_state cs "
            "JOIN campaign.campaigns c ON c.timeline_id = cs.timeline_id "
            "WHERE c.campaign_id = :c AND cs.character_id = :ch"
        ),
        {"c": s.cid, "ch": character},
    ).one()
    return int(row.current_hit_points), None if row.last_event_id is None else str(
        row.last_event_id
    )


def hurt(s: ContentSetup, character: str, time_id: str, delta: int) -> str:
    timeline = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": s.cid}
    ).scalar()
    result = _adjust_hit_points_impl(
        s.connection,
        timeline_id=timeline,
        character_id=uuid.UUID(character),
        world_time_id=uuid.UUID(time_id),
        delta=delta,
        campaign_id=uuid.UUID(s.cid),
    )
    assert result.event_id is not None
    return str(result.event_id)


def character_with_hp(s: ContentSetup, maximum: int = 20) -> str:
    pc = published_pc(s)
    response = s.gm.post_raw(
        s.url(f"characters/{pc}/state/initialize"),
        {"maximum_hit_points": maximum},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 201, response.text
    return pc


# --- narrative events --------------------------------------------------------------------------


def test_voiding_a_narrative_event_links_a_correcting_event_and_keeps_the_original(
    s: ContentSetup,
) -> None:
    t1 = Times(s).at(1)
    event = record(s, t1, details="SECRET detail")
    preview = s.gm.get(events_url(s, event, "/correction-preview")).json()
    assert preview["can_correct"] is True and preview["effects"] == []
    response = void(s, event, reason="PRIVATE reason")
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["status"] == "voided" and "replacement_event_id" not in receipt
    assert status_of(s, event) == "voided"
    row = s.connection.execute(
        text("""
            SELECT c.correction_kind, c.reason, c.created_by_user_id, ct.code AS correcting_type,
                   cause.cause_event_id, e.world_time_id
            FROM narrative.event_corrections c
            JOIN narrative.events e ON e.event_id = c.correcting_event_id
            JOIN narrative.event_types ct ON ct.event_type_id = e.event_type_id
            LEFT JOIN narrative.event_causes cause ON cause.event_id = c.correcting_event_id
            WHERE c.corrected_event_id = :e
        """),
        {"e": event},
    ).one()
    assert (row.correction_kind, row.correcting_type) == ("void", "administrative_correction")
    assert str(row.cause_event_id) == event and str(row.world_time_id) == t1
    assert row.reason == "PRIVATE reason" and row.created_by_user_id == s.gm.user_id
    view = s.gm.get(events_url(s, event)).json()
    assert view["status"] == "voided" and view["details"] == "SECRET detail"
    assert view["correction"]["kind"] == "void"
    effective = s.connection.execute(
        text(
            "SELECT count(*) FROM campaign.effective_events("
            "(SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c)) "
            "WHERE event_id = :e"
        ),
        {"c": s.cid, "e": event},
    ).scalar()
    assert effective == 0
    statuses = [a.action for a in s.audit("void_event")]
    assert statuses == ["status_changed", "created"]
    for audit in s.audit("void_event"):
        assert "PRIVATE" not in str(audit.changed_fields)


def test_correcting_a_narrative_event_records_a_replacement(s: ContentSetup) -> None:
    times = Times(s)
    t1, t2 = times.at(1), times.at(2)
    event = record(s, t1, name="The door is locked")
    refused = correct(s, event, {"event_type_code": "quest_failed", "name": "x"})
    assert refused.status_code in (400, 422)
    assert status_of(s, event) == "recorded"
    ok = correct(
        s,
        event,
        {
            "event_type_code": "other",
            "name": "The door is stuck",
            "details": "Rusty",
            "world_time_id": t2,
        },
    )
    assert ok.status_code == 200, ok.text
    receipt = ok.json()
    assert receipt["status"] == "corrected" and receipt["replacement_event_id"]
    assert status_of(s, event) == "corrected"
    replacement = s.gm.get(events_url(s, receipt["replacement_event_id"])).json()
    assert replacement["name"] == "The door is stuck" and replacement["details"] == "Rusty"
    assert replacement["status"] == "recorded" and replacement["world_time_id"] == t2
    assert (
        s.gm.get(events_url(s, event)).json()["correction"]["replacement_event_id"]
        == receipt["replacement_event_id"]
    )


def test_a_correction_cannot_be_repeated_or_corrected_and_needs_a_reason(s: ContentSetup) -> None:
    event = record(s, Times(s).at(1))
    no_reason = s.gm.post_raw(events_url(s, event, "/void"), {}, key=s.gm.fresh_key())
    assert no_reason.status_code in (400, 422)
    first = void(s, event)
    assert first.status_code == 200
    again = void(s, event)
    assert again.status_code == 409 and again.json()["error"]["code"] == "event_already_corrected"
    correcting = first.json()["correcting_event_id"]
    nested = void(s, correcting)
    assert nested.status_code == 409 and nested.json()["error"]["code"] == "event_not_correctable"
    assert (
        s.gm.get(events_url(s, correcting, "/correction-preview")).json()["is_correction"] is True
    )


# --- reversible effects ------------------------------------------------------------------------


def test_voiding_a_hit_point_change_restores_the_hit_points(s: ContentSetup) -> None:
    t1 = Times(s).at(1)
    pc = character_with_hp(s, 20)
    event = hurt(s, pc, t1, -7)
    assert hp_state(s, pc)[0] == 13
    preview = s.gm.get(events_url(s, event, "/correction-preview")).json()
    assert preview["can_correct"] is True
    assert [(e["component"], e["reversible"]) for e in preview["effects"]] == [
        ("current_hit_points", True)
    ]
    response = void(s, event)
    assert response.status_code == 200, response.text
    hp, last_event = hp_state(s, pc)
    assert hp == 20 and last_event == response.json()["correcting_event_id"]
    compensating = s.connection.execute(
        text(
            "SELECT target_component, previous_value, new_value FROM narrative.event_effects "
            "WHERE event_id = :e"
        ),
        {"e": response.json()["correcting_event_id"]},
    ).one()
    assert (compensating.target_component, compensating.previous_value, compensating.new_value) == (
        "current_hit_points",
        13,
        20,
    )


def test_a_hit_point_correction_is_refused_once_the_state_has_moved_on(s: ContentSetup) -> None:
    times = Times(s)
    t1, t2 = times.at(1), times.at(2)
    pc = character_with_hp(s, 20)
    first = hurt(s, pc, t1, -5)
    later = hurt(s, pc, t2, -3)
    assert hp_state(s, pc)[0] == 12
    preview = s.gm.get(events_url(s, first, "/correction-preview")).json()
    assert preview["can_correct"] is False
    assert preview["effects"][0] == {
        "component": "current_hit_points",
        "target_entity_id": pc,
        "reversible": False,
        "reason": "state_changed",
    }
    refused = void(s, first)
    assert (
        refused.status_code == 409
        and refused.json()["error"]["code"] == "correction_not_reversible"
    )
    assert status_of(s, first) == "recorded" and hp_state(s, pc)[0] == 12
    # The later one is still the latest change, so it can be undone, and then the first.
    assert void(s, later).status_code == 200 and hp_state(s, pc)[0] == 15
    assert void(s, first).status_code == 200 and hp_state(s, pc)[0] == 20


def test_voiding_an_activation_event_restores_the_previous_build(s: ContentSetup) -> None:
    times = Times(s)
    clock = times.at(1)
    assert _advance(s, clock, 0).status_code == 200
    pc = published_pc(s)
    species_body = {"maximum_hit_points": 10}
    assert (
        s.gm.post_raw(
            s.url(f"characters/{pc}/state/initialize"), species_body, key=s.gm.fresh_key()
        ).status_code
        == 201
    )
    builds = []
    for label in ("One", "Two"):
        response = s.gm.post_raw(
            s.url(f"characters/{pc}/builds"), {"label": label}, key=s.gm.fresh_key()
        )
        assert response.status_code == 201, response.text
        builds.append(response.json()["character_build_id"])
    first = s.gm.post_raw(
        s.url(f"characters/{pc}/builds/{builds[0]}/activate"),
        {"expected_active_build_id": None},
        key=s.gm.fresh_key(),
    )
    assert first.status_code == 200
    second = s.gm.post_raw(
        s.url(f"characters/{pc}/builds/{builds[1]}/activate"),
        {"expected_active_build_id": builds[0]},
        key=s.gm.fresh_key(),
    )
    assert second.status_code == 200, second.text
    assert s.gm.get(s.url(f"characters/{pc}/builds")).json()["active_build_id"] == builds[1]
    response = void(s, second.json()["event_id"])
    assert response.status_code == 200, response.text
    assert s.gm.get(s.url(f"characters/{pc}/builds")).json()["active_build_id"] == builds[0]


def test_voiding_a_join_removes_the_membership_and_voiding_a_leave_restores_it(
    s: ContentSetup,
) -> None:
    times = Times(s)
    t1, t3 = times.at(1), times.at(3)
    pc = published_pc(s)
    party = s.gm.post_raw(
        f"/campaigns/{s.cid}/parties", {"name": "Crew"}, key=s.gm.fresh_key()
    ).json()
    members = f"/campaigns/{s.cid}/parties/{party['party_id']}/members"
    joined = s.gm.post_raw(
        members,
        {"character_id": pc, "effective_from_world_time_id": t1, "expected_party_row_version": 1},
        key=s.gm.fresh_key(),
    ).json()
    left = s.gm.post_raw(
        f"{members}/{joined['party_membership_id']}/end",
        {"effective_to_world_time_id": t3, "expected_party_row_version": joined["row_version"]},
        key=s.gm.fresh_key(),
    ).json()

    def count() -> tuple[int, int]:
        row = s.connection.execute(
            text(
                "SELECT count(*), count(*) FILTER (WHERE effective_to_world_time_id IS NULL) "
                "FROM campaign.party_memberships WHERE party_id = :p"
            ),
            {"p": party["party_id"]},
        ).one()
        return int(row[0]), int(row[1])

    # The join cannot be undone while the membership has ended; the leave can.
    assert void(s, joined["event_id"]).status_code == 409
    assert count() == (1, 0)
    assert void(s, left["event_id"]).status_code == 200
    assert count() == (1, 1)
    assert void(s, joined["event_id"]).status_code == 200
    assert count() == (0, 0)


def test_an_effect_without_a_safe_reversal_refuses_the_correction(s: ContentSetup) -> None:
    times = Times(s)
    t1 = times.at(1)
    response = _advance(s, t1, 0)
    assert response.status_code == 200
    refused = void(s, response.json()["event_id"])
    assert (
        refused.status_code == 409
        and refused.json()["error"]["code"] == "correction_not_reversible"
    )
    preview = s.gm.get(events_url(s, response.json()["event_id"], "/correction-preview")).json()
    assert preview["effects"][0]["reason"] == "unsupported_effect"
    assert status_of(s, response.json()["event_id"]) == "recorded"


# --- scope, authority, integrity ---------------------------------------------------------------


def test_events_of_other_timelines_and_missing_events_are_indistinguishable(
    s: ContentSetup,
) -> None:
    times = Times(s)
    t1 = times.at(1)
    event = record(s, t1)
    branch_cid = _branch_campaign(s, t1)
    seen = set()
    for cid, target in ((branch_cid, event), (s.cid, str(uuid.uuid4())), (s.other_cid, event)):
        for method, suffix, body in (
            ("get", "", None),
            ("get", "/correction-preview", None),
            ("post", "/void", {"reason": "x"}),
        ):
            url = events_url(s, target, suffix, cid=cid)
            actor = s.gm
            response = (
                actor.get(url)
                if method == "get"
                else actor.post_raw(url, body, key=actor.fresh_key())
            )
            assert response.status_code in (403, 404), (cid, suffix, response.status_code)
            if response.status_code == 404:
                seen.add((response.json()["error"]["code"], response.json()["error"]["message"]))
    assert len(seen) == 1
    assert status_of(s, event) == "recorded"


def test_only_editors_and_human_principals_can_correct(s: ContentSetup) -> None:
    event = record(s, Times(s).at(1))
    path = events_url(s, event, "/void")
    assert s.player.get(events_url(s, event)).status_code == 403
    assert s.player.post_raw(path, {"reason": "x"}).status_code == 403
    assert s.stranger.post_raw(path, {"reason": "x"}).status_code == 404
    assert s.gm.post_raw(path, {"reason": "x"}, csrf=False).status_code == 403
    foundry = AuthenticatedPrincipal(
        user_id=s.gm.user_id,
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=uuid.uuid4(),
        foundry_world_id=uuid.uuid4(),
        campaign_id=uuid.UUID(s.cid),
        foundry_connection_id=uuid.uuid4(),
        foundry_device_id=uuid.uuid4(),
        foundry_scopes=frozenset({"encounter_read"}),
    )
    client = s.harness.principal_client(foundry)
    assert client.post(path, json={"reason": "x"}).status_code == 403
    assert status_of(s, event) == "recorded"


def test_replay_returns_the_same_receipt_and_one_correction(s: ContentSetup) -> None:
    event = record(s, Times(s).at(1))
    key = s.gm.fresh_key()
    first = s.gm.post_raw(events_url(s, event, "/void"), {"reason": "x"}, key=key)
    again = s.gm.post_raw(events_url(s, event, "/void"), {"reason": "x"}, key=key)
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    count = s.connection.execute(text("SELECT count(*) FROM narrative.event_corrections")).scalar()
    assert count == 1


def test_a_failure_while_linking_leaves_the_event_recorded_and_no_correcting_event(
    s: ContentSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import Connection as Conn

    event = record(s, Times(s).at(1))
    real_execute = Conn.execute

    def failing(self: Conn, statement: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if "INSERT INTO narrative.event_corrections" in str(statement):
            raise RuntimeError("injected failure")
        return real_execute(self, statement, *args, **kwargs)  # type: ignore[arg-type]

    tables = ("narrative.events", "core.entities", "narrative.event_causes", "audit.change_log")
    before = {t: s.count(t) for t in tables}
    monkeypatch.setattr(Conn, "execute", failing)
    response = s.gm.post_raw(events_url(s, event, "/void"), {"reason": "x"}, key=s.gm.fresh_key())
    monkeypatch.undo()
    assert response.status_code == 500
    assert before == {t: s.count(t) for t in tables}
    assert status_of(s, event) == "recorded"


def test_the_database_refuses_a_status_change_without_its_link(s: ContentSetup) -> None:
    event = record(s, Times(s).at(1))
    with (
        pytest.raises(IntegrityError, match="without a matching correction"),
        s.connection.begin_nested(),
    ):
        s.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        s.connection.execute(
            text(
                "UPDATE narrative.events SET event_status_id = "
                "(SELECT event_status_id FROM narrative.event_statuses WHERE code = 'voided') "
                "WHERE event_id = :e"
            ),
            {"e": event},
        )


def test_corrections_are_append_only_and_cannot_correct_themselves(s: ContentSetup) -> None:
    times = Times(s)
    t1 = times.at(1)
    event = record(s, t1)
    receipt = void(s, event).json()
    with pytest.raises(IntegrityError, match="append-only"), s.connection.begin_nested():
        s.connection.execute(
            text(
                "UPDATE narrative.event_corrections SET reason = 'x' WHERE event_correction_id = :c"
            ),
            {"c": receipt["correction_id"]},
        )
    other = record(s, t1, name="Other")
    with pytest.raises(IntegrityError), s.connection.begin_nested():
        s.connection.execute(
            text(
                "INSERT INTO narrative.event_corrections "
                "(corrected_event_id, correcting_event_id, correction_kind, reason) "
                "VALUES (:a, :a, 'void', 'self')"
            ),
            {"a": other},
        )
