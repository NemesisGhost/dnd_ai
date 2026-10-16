"""Campaign clock endpoints (checkpoint 15.2W-2, migration 118)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.domain.access import FOUNDRY_ACCESS_AUTH_METHOD, AuthenticatedPrincipal
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.builders import dnd5e_ids
from tests.content_support import ContentSetup

pytestmark = pytest.mark.database

CALENDAR = {
    "name": "Common Reckoning",
    "description": None,
    "days_per_week": None,
    "epoch_label": None,
    "months": [{"name": "Only", "day_count": 100}],
}


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


class Times:
    """World-time points created through the production routes."""

    def __init__(self, s: ContentSetup) -> None:
        self.s = s
        calendar = s.gm.post_raw(
            f"/worlds/{s.world_id}/calendars", CALENDAR, key=s.gm.fresh_key()
        ).json()
        self.calendar_id = calendar["calendar_id"]

    def at(self, year: int, cid: str | None = None) -> str:
        response = self.s.gm.post_raw(
            f"/campaigns/{cid or self.s.cid}/world-times",
            {"calendar_id": self.calendar_id, "year": year},
            key=self.s.gm.fresh_key(),
        )
        assert response.status_code == 201, response.text
        return response.json()["world_time_id"]


def _advance(s: ContentSetup, time_id: str, version: int, cid: str | None = None, **kw: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        f"/campaigns/{cid or s.cid}/clock/advance",
        {"world_time_id": time_id, "expected_row_version": version},
        key=s.gm.fresh_key(),
        **kw,  # type: ignore[arg-type]
    )


def _clock(s: ContentSetup, cid: str | None = None) -> dict:
    response = s.gm.get(f"/campaigns/{cid or s.cid}/clock")
    assert response.status_code == 200, response.text
    return response.json()


def _event(s: ContentSetup, event_id: str) -> dict:
    row = s.connection.execute(
        text("""
            SELECT et.code AS event_type, e.timeline_id, e.campaign_id, e.world_time_id,
                   ec.cause_event_id,
                   (SELECT count(*) FROM narrative.event_effects f WHERE f.event_id = e.event_id)
                       AS effects
            FROM narrative.events e
            JOIN narrative.event_types et ON et.event_type_id = e.event_type_id
            LEFT JOIN narrative.event_causes ec ON ec.event_id = e.event_id
            WHERE e.event_id = :e
        """),
        {"e": event_id},
    ).one()
    return dict(row._mapping)


def test_a_new_campaign_has_no_clock(s: ContentSetup) -> None:
    assert _clock(s) == {
        "current": None,
        "row_version": 0,
        "inherited": False,
        "last_event_id": None,
    }


def test_the_first_advance_creates_the_clock_with_an_event_and_an_effect(s: ContentSetup) -> None:
    year3 = Times(s).at(3)
    response = _advance(s, year3, 0)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert set(receipt) == {"world_time_id", "event_id", "row_version", "created", "changed"}
    assert receipt["created"] is True and receipt["row_version"] == 1
    clock = _clock(s)
    assert clock["current"]["world_time_id"] == year3
    # The display keeps the calendar and date, not just a label.
    assert clock["current"]["display"] == "Common Reckoning: Year 3"
    assert clock["row_version"] == 1 and clock["inherited"] is False
    assert clock["last_event_id"] == receipt["event_id"]
    event = _event(s, receipt["event_id"])
    assert event["event_type"] == "time_advanced" and event["effects"] == 1
    assert str(event["campaign_id"]) == s.cid and event["cause_event_id"] is None
    audit = s.audit("advance_campaign_clock")
    assert len(audit) == 1 and audit[0].action == "created"
    assert str(audit[0].world_id) == str(s.world_id)


def test_a_later_advance_updates_the_clock_and_chains_its_cause(s: ContentSetup) -> None:
    times = Times(s)
    first = _advance(s, times.at(3), 0).json()
    second = _advance(s, times.at(5), 1)
    assert second.status_code == 200 and second.json()["created"] is False
    assert second.json()["row_version"] == 2
    assert _event(s, second.json()["event_id"])["cause_event_id"] == uuid.UUID(first["event_id"])


@pytest.mark.parametrize("year", [3, 2])
def test_the_clock_cannot_move_to_the_same_or_an_earlier_time(s: ContentSetup, year: int) -> None:
    times = Times(s)
    assert _advance(s, times.at(3), 0).status_code == 200
    target = times.at(year)
    refused = _advance(s, target, 1)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "clock_not_advanced"
    assert _clock(s)["row_version"] == 1
    assert len(s.audit("advance_campaign_clock")) == 1


def test_a_stale_version_is_a_409_and_writes_nothing(s: ContentSetup) -> None:
    times = Times(s)
    assert _advance(s, times.at(3), 0).status_code == 200
    stale = _advance(s, times.at(5), 0)  # still expects "no clock"
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"
    wrong_first = _advance(s, times.at(6), 7)
    assert wrong_first.status_code == 409
    assert _clock(s)["row_version"] == 1


def test_a_retry_with_the_same_key_replays_the_receipt_once(s: ContentSetup) -> None:
    year3 = Times(s).at(3)
    key = s.gm.fresh_key()
    body = {"world_time_id": year3, "expected_row_version": 0}
    path = f"/campaigns/{s.cid}/clock/advance"
    first = s.gm.post_raw(path, body, key=key)
    again = s.gm.post_raw(path, body, key=key)
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert len(s.audit("advance_campaign_clock")) == 1
    assert _clock(s)["row_version"] == 1
    other = s.gm.post_raw(path, {**body, "expected_row_version": 1}, key=key)
    assert other.status_code == 409


def test_a_correction_sets_a_different_time_and_cites_the_event_it_corrects(
    s: ContentSetup,
) -> None:
    times = Times(s)
    advance = _advance(s, times.at(9), 0).json()
    earlier = times.at(4)
    response = s.gm.post_raw(
        f"/campaigns/{s.cid}/clock/correct",
        {
            "world_time_id": earlier,
            "expected_row_version": 1,
            "corrects_event_id": advance["event_id"],
        },
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 200, response.text
    receipt = response.json()
    clock = _clock(s)
    assert clock["current"]["world_time_id"] == earlier and clock["row_version"] == 2
    event = _event(s, receipt["event_id"])
    assert event["event_type"] == "time_corrected"
    assert event["cause_event_id"] == uuid.UUID(advance["event_id"])
    # The original advance stays in history.
    assert _event(s, advance["event_id"])["event_type"] == "time_advanced"
    # Correcting again with the now-superseded event is a stale write.
    stale = s.gm.post_raw(
        f"/campaigns/{s.cid}/clock/correct",
        {
            "world_time_id": times.at(2),
            "expected_row_version": 2,
            "corrects_event_id": advance["event_id"],
        },
        key=s.gm.fresh_key(),
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"


def test_correction_edge_cases(s: ContentSetup) -> None:
    times = Times(s)
    path = f"/campaigns/{s.cid}/clock/correct"
    nothing = s.gm.post_raw(
        path,
        {
            "world_time_id": times.at(1),
            "expected_row_version": 0,
            "corrects_event_id": str(uuid.uuid4()),
        },
        key=s.gm.fresh_key(),
    )
    assert nothing.status_code == 409 and nothing.json()["error"]["code"] == "clock_not_set"
    year5 = times.at(5)
    advance = _advance(s, year5, 0).json()
    same = s.gm.post_raw(
        path,
        {
            "world_time_id": year5,
            "expected_row_version": 1,
            "corrects_event_id": advance["event_id"],
        },
        key=s.gm.fresh_key(),
    )
    assert same.status_code == 409 and same.json()["error"]["code"] == "clock_unchanged"


def test_foreign_and_missing_world_times_are_the_same_400(s: ContentSetup) -> None:
    foreign_calendar = s.stranger.post_raw(
        f"/worlds/{s.other_world_id}/calendars", CALENDAR, key=s.stranger.fresh_key()
    ).json()["calendar_id"]
    foreign = s.stranger.post_raw(
        f"/campaigns/{s.other_cid}/world-times",
        {"calendar_id": foreign_calendar, "year": 1},
        key=s.stranger.fresh_key(),
    ).json()["world_time_id"]
    for target in (foreign, str(uuid.uuid4())):
        response = _advance(s, target, 0)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "world_time_id_invalid"
    assert _clock(s)["current"] is None


def test_authority_csrf_origin_and_principals(s: ContentSetup) -> None:
    year3 = Times(s).at(3)
    body = {"world_time_id": year3, "expected_row_version": 0}
    path = f"/campaigns/{s.cid}/clock/advance"
    # A player may read the clock but never write it; a stranger sees nothing.
    assert s.player.get(f"/campaigns/{s.cid}/clock").status_code == 200
    assert s.player.post_raw(path, body).status_code == 403
    assert s.stranger.get(f"/campaigns/{s.cid}/clock").status_code == 404
    assert s.stranger.post_raw(path, body).status_code == 404
    assert s.gm.post_raw(path, body, csrf=False).status_code == 403
    assert s.gm.post_raw(path, body, origin=False).status_code == 403
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
    assert client.get(f"/campaigns/{s.cid}/clock").status_code == 403
    assert client.post(path, json=body).status_code == 403
    assert s.harness.anonymous_client().get(f"/campaigns/{s.cid}/clock").status_code == 401
    assert _clock(s)["current"] is None


def test_an_archived_campaign_refuses_clock_writes(s: ContentSetup) -> None:
    year3 = Times(s).at(3)
    s.connection.execute(
        text(
            "UPDATE campaign.campaigns SET lifecycle_status_id = "
            "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
            "WHERE campaign_id = :c"
        ),
        {"c": s.cid},
    )
    assert _advance(s, year3, 0).status_code in (404, 409)


# --- branches ----------------------------------------------------------------------------


def _branch_campaign(s: ContentSetup, branch_point: str) -> str:
    primary = s.connection.execute(
        text("SELECT timeline_id FROM campaign.timelines WHERE world_id = :w AND is_primary"),
        {"w": s.world_id},
    ).scalar()
    branch = s.gm.post_raw(
        f"/worlds/{s.world_id}/timelines/{primary}/branches",
        {
            "name": "What if",
            "description": None,
            "branch_point": {"kind": "existing_world_time", "world_time_id": branch_point},
        },
        key=s.gm.fresh_key(),
    )
    assert branch.status_code == 201, branch.text
    _, version_id = dnd5e_ids(s.connection)
    campaign = s.gm.post_raw(
        "/campaigns",
        {
            "timeline_id": branch.json()["timeline_id"],
            "ruleset_version_id": str(version_id),
            "name": "Branch campaign",
            "description": None,
        },
        key=s.gm.fresh_key(),
    )
    assert campaign.status_code == 201, campaign.text
    return campaign.json()["campaign_id"]


def test_a_branch_inherits_its_parents_clock_bounded_by_the_branch_point_and_diverges(
    s: ContentSetup,
) -> None:
    times = Times(s)
    year2, year4, year9 = times.at(2), times.at(4), times.at(9)
    assert _advance(s, year4, 0).status_code == 200  # parent clock at year 4
    assert _advance(s, year9, 1).status_code == 200  # parent clock at year 9
    branch_cid = _branch_campaign(s, year4)  # branch at year 4: an advance event exists there

    inherited = _clock(s, branch_cid)
    # The parent is at year 9, but the branch never sees time after its branch point.
    assert inherited["inherited"] is True and inherited["row_version"] == 0
    assert inherited["current"]["world_time_id"] == year4

    # The branch advances on its own (to a time before the parent's clock) and diverges.
    assert _advance(s, times.at(6), 0, cid=branch_cid).status_code == 200
    assert _clock(s, branch_cid)["inherited"] is False
    assert _clock(s)["current"]["world_time_id"] == year9
    assert _clock(s)["row_version"] == 2
    # A branch cannot go back to or before what it already inherited.
    refused = _advance(s, year2, 1, cid=branch_cid)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "clock_not_advanced"


def test_the_clock_row_enforces_its_invariants_in_the_database(s: ContentSetup) -> None:
    times = Times(s)
    year3 = times.at(3)
    assert _advance(s, year3, 0).status_code == 200
    foreign_calendar = s.stranger.post_raw(
        f"/worlds/{s.other_world_id}/calendars", CALENDAR, key=s.stranger.fresh_key()
    ).json()["calendar_id"]
    foreign_time = s.stranger.post_raw(
        f"/campaigns/{s.other_cid}/world-times",
        {"calendar_id": foreign_calendar, "year": 1},
        key=s.stranger.fresh_key(),
    ).json()["world_time_id"]
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError, match="is in world"), s.connection.begin_nested():
        s.connection.execute(
            text(
                "UPDATE campaign.timeline_clocks SET current_world_time_id = :t "
                "WHERE timeline_id = (SELECT timeline_id FROM campaign.campaigns "
                "WHERE campaign_id = :c)"
            ),
            {"t": foreign_time, "c": s.cid},
        )
    # The row version bumps on every update.
    version = s.connection.execute(
        text(
            "SELECT row_version FROM campaign.timeline_clocks WHERE timeline_id = "
            "(SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c)"
        ),
        {"c": s.cid},
    ).scalar()
    assert version == 1
