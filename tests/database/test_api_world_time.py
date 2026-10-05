"""Calendar and world-time endpoints (checkpoint 15.2W-1)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.domain.access import FOUNDRY_ACCESS_AUTH_METHOD, AuthenticatedPrincipal
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup

pytestmark = pytest.mark.database

SENTINEL = "ZQX-WORLD-TIME-LABEL-9921"
CALENDAR = {
    "name": "Common Reckoning",
    "description": "The reckoning of the Republic",
    "days_per_week": 7,
    "epoch_label": "Founding",
    "months": [
        {"name": "Frost", "day_count": 30},
        {"name": "Bloom", "day_count": 28},
        {"name": "Harvest", "day_count": 31},
    ],
}


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def _calendars_url(s: ContentSetup) -> str:
    return f"/worlds/{s.world_id}/calendars"


def _times_url(s: ContentSetup, cid: str | None = None) -> str:
    return f"/campaigns/{cid or s.cid}/world-times"


def _world_count(s: ContentSetup, table: str) -> int:
    """Rows of a world-scoped table in this setup's own world (the shared test
    database may hold other committed worlds)."""
    value = s.connection.execute(
        text(f"SELECT count(*) FROM {table} WHERE world_id = :w"), {"w": s.world_id}
    ).scalar()
    assert isinstance(value, int)
    return value


def _create_calendar(s: ContentSetup) -> dict:
    response = s.gm.post_raw(_calendars_url(s), CALENDAR, key=s.gm.fresh_key())
    assert response.status_code == 201, response.text
    return response.json()


def _create_time(s: ContentSetup, **body: object) -> dict:
    response = s.gm.post_raw(_times_url(s), body, key=s.gm.fresh_key())
    assert response.status_code == 201, response.text
    return response.json()


def _key(s: ContentSetup, world_time_id: str) -> int:
    value = s.connection.execute(
        text("SELECT sort_key FROM core.world_times WHERE world_time_id = :t"),
        {"t": world_time_id},
    ).scalar()
    assert isinstance(value, int)
    return value


# --- calendars ---------------------------------------------------------------------------


def test_a_world_owner_creates_and_lists_a_calendar(s: ContentSetup) -> None:
    receipt = _create_calendar(s)
    assert set(receipt) == {"calendar_id", "created", "changed"}
    listed = s.gm.get(_calendars_url(s)).json()["calendars"]
    (calendar,) = listed
    assert calendar["calendar_id"] == receipt["calendar_id"]
    assert calendar["code"] == "common_reckoning" and calendar["name"] == "Common Reckoning"
    assert [(m["month_number"], m["name"], m["day_count"]) for m in calendar["months"]] == [
        (1, "Frost", 30),
        (2, "Bloom", 28),
        (3, "Harvest", 31),
    ]
    # The campaign-scoped list (what the portal picker reads) shows the same.
    assert s.gm.get(f"/campaigns/{s.cid}/calendars").json()["calendars"] == listed


def test_calendar_codes_stay_unique_within_a_world(s: ContentSetup) -> None:
    _create_calendar(s)
    _create_calendar(s)
    codes = [c["code"] for c in s.gm.get(_calendars_url(s)).json()["calendars"]]
    assert sorted(codes) == ["common_reckoning", "common_reckoning_2"]


def test_calendar_creation_is_audited_without_content_and_replays_by_key(s: ContentSetup) -> None:
    key = s.gm.fresh_key()
    first = s.gm.post_raw(_calendars_url(s), CALENDAR, key=key)
    again = s.gm.post_raw(_calendars_url(s), CALENDAR, key=key)
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    rows = s.audit("create_calendar")
    assert len(rows) == 1 and rows[0].action == "created"
    assert rows[0].changed_fields["name"] == "Common Reckoning"
    assert rows[0].changed_fields["description"] == {"redacted": True}
    assert "Republic" not in str(rows[0].changed_fields)
    other = s.gm.post_raw(_calendars_url(s), {**CALENDAR, "name": "Other"}, key=key)
    assert other.status_code == 409


@pytest.mark.parametrize(
    "override",
    [
        {"months": []},
        {"months": [{"name": "A", "day_count": 0}]},
        {"months": [{"name": "A", "day_count": 5}, {"name": "a", "day_count": 5}]},
        {"days_per_week": 99},
        {"name": ""},
    ],
)
def test_an_invalid_calendar_is_refused_and_writes_nothing(s: ContentSetup, override: dict) -> None:
    before = _world_count(s, "core.calendars")
    response = s.gm.post_raw(_calendars_url(s), {**CALENDAR, **override}, key=s.gm.fresh_key())
    assert response.status_code in (400, 422)
    assert _world_count(s, "core.calendars") == before


def test_calendar_authority_is_per_world_and_non_disclosing(s: ContentSetup) -> None:
    assert s.player.post_raw(_calendars_url(s), CALENDAR).status_code == 404
    assert s.player.get(_calendars_url(s)).status_code == 404
    assert s.stranger.post_raw(_calendars_url(s), CALENDAR).status_code == 404
    missing = s.gm.post_raw(f"/worlds/{uuid.uuid4()}/calendars", CALENDAR)
    assert missing.status_code == 404
    assert s.stranger.get(_calendars_url(s)).status_code == 404
    assert _world_count(s, "core.calendars") == 0


def test_calendar_writes_enforce_csrf_origin_and_refuse_foundry(s: ContentSetup) -> None:
    assert s.gm.post_raw(_calendars_url(s), CALENDAR, csrf=False).status_code == 403
    assert s.gm.post_raw(_calendars_url(s), CALENDAR, origin=False).status_code == 403
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
    assert client.post(_calendars_url(s), json=CALENDAR).status_code == 403
    assert (
        client.post(_times_url(s), json={"label": "x", "after_world_time_id": None}).status_code
        == 403
    )
    assert client.get(_times_url(s)).status_code == 403
    assert s.harness.anonymous_client().get(_calendars_url(s)).status_code == 401


# --- world-time points -----------------------------------------------------------------------


def test_calendar_points_get_minute_sort_keys_and_precision(s: ContentSetup) -> None:
    calendar = _create_calendar(s)["calendar_id"]
    base = {"calendar_id": calendar}
    a = _create_time(s, **base, year=0)
    b = _create_time(s, **base, year=0, month_number=2, day=3, hour=4, minute=5)
    c = _create_time(s, **base, year=1, approximate=True)
    assert _key(s, a["world_time_id"]) == 0
    assert _key(s, b["world_time_id"]) == ((30 + 2) * 24 + 4) * 60 + 5
    assert _key(s, c["world_time_id"]) == 89 * 24 * 60
    precisions = dict(
        s.connection.execute(
            text("""
                SELECT wt.world_time_id::text, p.code FROM core.world_times wt
                JOIN core.world_time_precisions p
                  ON p.world_time_precision_id = wt.world_time_precision_id
                WHERE wt.world_id = :w
            """),
            {"w": s.world_id},
        ).all()
    )
    assert precisions[b["world_time_id"]] == "exact"
    assert precisions[a["world_time_id"]] == "partial"
    assert precisions[c["world_time_id"]] == "approximate"


def test_the_list_is_latest_first_paged_and_names_each_point(s: ContentSetup) -> None:
    calendar = _create_calendar(s)["calendar_id"]
    ids = [
        _create_time(s, calendar_id=calendar, year=y, month_number=2, day=1)["world_time_id"]
        for y in (1, 2, 3)
    ]
    first = s.gm.get(_times_url(s), limit=2).json()
    assert [i["world_time_id"] for i in first["items"]] == [ids[2], ids[1]]
    assert first["items"][0]["display"] == "Year 3 (Founding), Bloom 1"
    assert first["next_cursor"]
    second = s.gm.get(_times_url(s), limit=2, cursor=first["next_cursor"]).json()
    assert [i["world_time_id"] for i in second["items"]] == [ids[0]]
    assert second["next_cursor"] is None


def test_narrative_points_are_placed_after_and_before_neighbours(s: ContentSetup) -> None:
    calendar = _create_calendar(s)["calendar_id"]
    early = _create_time(s, calendar_id=calendar, year=0)["world_time_id"]
    late = _create_time(s, calendar_id=calendar, year=5)["world_time_id"]
    middle = _create_time(s, label="After the siege", after_world_time_id=early)
    k = _key(s, middle["world_time_id"])
    assert _key(s, early) < k < _key(s, late)
    narrower = _create_time(
        s,
        label="Just before dawn",
        after_world_time_id=early,
        before_world_time_id=middle["world_time_id"],
    )
    assert _key(s, early) < _key(s, narrower["world_time_id"]) < k
    # With nothing later, a point sits one day after the last one.
    last = _create_time(s, label="Epilogue", after_world_time_id=late)
    assert _key(s, last["world_time_id"]) == _key(s, late) + 1440


def test_a_closed_gap_is_a_409_and_writes_nothing(s: ContentSetup) -> None:
    calendar = _create_calendar(s)["calendar_id"]
    a = _create_time(s, calendar_id=calendar, year=0)["world_time_id"]
    # A point exactly one minute later leaves no whole key between them.
    b = _create_time(s, calendar_id=calendar, year=0, month_number=1, day=1, hour=0, minute=1)
    assert _key(s, b["world_time_id"]) == _key(s, a) + 1
    before = _world_count(s, "core.world_times")
    refused = s.gm.post_raw(
        _times_url(s), {"label": "No room", "after_world_time_id": a}, key=s.gm.fresh_key()
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "world_time_no_gap"
    assert _world_count(s, "core.world_times") == before


@pytest.mark.parametrize(
    "body",
    [
        {"label": "x"},  # narrative without an anchor
        {"label": "x", "after_world_time_id": None, "year": 3},
        {"year": 3},  # a date needs a calendar
        {"calendar_id": "CAL", "month_number": 2},  # a calendar time needs a year
        {"calendar_id": "CAL", "year": 1, "month_number": 9},
        {"calendar_id": "CAL", "year": 1, "month_number": 2, "day": 29},
        {"calendar_id": "CAL", "year": 1, "label": "x", "after_world_time_id": "AFTER"},
    ],
)
def test_invalid_time_requests_are_refused_and_write_nothing(s: ContentSetup, body: dict) -> None:
    calendar = _create_calendar(s)["calendar_id"]
    anchor = _create_time(s, calendar_id=calendar, year=0)["world_time_id"]
    payload = {
        k: (calendar if v == "CAL" else anchor if v == "AFTER" else v) for k, v in body.items()
    }
    before = _world_count(s, "core.world_times")
    response = s.gm.post_raw(_times_url(s), payload, key=s.gm.fresh_key())
    assert response.status_code in (400, 422), response.text
    assert _world_count(s, "core.world_times") == before


def test_foreign_ids_look_like_missing_ones(s: ContentSetup) -> None:
    foreign_calendar = s.stranger.post_raw(
        f"/worlds/{s.other_world_id}/calendars", CALENDAR, key=s.stranger.fresh_key()
    ).json()["calendar_id"]
    foreign_time = s.stranger.post_raw(
        _times_url(s, s.other_cid),
        {"calendar_id": foreign_calendar, "year": 1},
        key=s.stranger.fresh_key(),
    ).json()["world_time_id"]
    missing_calendar = s.gm.post_raw(
        _times_url(s), {"calendar_id": str(uuid.uuid4()), "year": 1}, key=s.gm.fresh_key()
    )
    foreign = s.gm.post_raw(
        _times_url(s), {"calendar_id": foreign_calendar, "year": 1}, key=s.gm.fresh_key()
    )
    assert missing_calendar.status_code == foreign.status_code == 400
    assert missing_calendar.json()["error"]["code"] == foreign.json()["error"]["code"]
    anchor_missing = s.gm.post_raw(
        _times_url(s),
        {"label": "x", "after_world_time_id": str(uuid.uuid4())},
        key=s.gm.fresh_key(),
    )
    anchor_foreign = s.gm.post_raw(
        _times_url(s), {"label": "x", "after_world_time_id": foreign_time}, key=s.gm.fresh_key()
    )
    assert anchor_missing.status_code == anchor_foreign.status_code == 400
    assert anchor_missing.json()["error"]["code"] == anchor_foreign.json()["error"]["code"]


def test_the_list_never_includes_another_worlds_points(s: ContentSetup) -> None:
    foreign_calendar = s.stranger.post_raw(
        f"/worlds/{s.other_world_id}/calendars", CALENDAR, key=s.stranger.fresh_key()
    ).json()["calendar_id"]
    s.stranger.post_raw(
        _times_url(s, s.other_cid),
        {"calendar_id": foreign_calendar, "year": 7},
        key=s.stranger.fresh_key(),
    )
    assert s.gm.get(_times_url(s)).json()["items"] == []
    assert s.gm.get(f"/campaigns/{s.cid}/calendars").json()["calendars"] == []


def test_a_player_or_stranger_cannot_read_or_write_world_times(s: ContentSetup) -> None:
    body = {"label": "x", "after_world_time_id": None}
    assert s.player.get(_times_url(s)).status_code == 403
    assert s.player.post_raw(_times_url(s), body).status_code == 403
    assert s.stranger.get(_times_url(s)).status_code == 404
    assert s.stranger.post_raw(_times_url(s), body).status_code == 404


def test_a_time_write_is_audited_with_structural_values_only_and_replays(s: ContentSetup) -> None:
    calendar = _create_calendar(s)["calendar_id"]
    anchor = _create_time(s, calendar_id=calendar, year=0)["world_time_id"]
    key = s.gm.fresh_key()
    body = {"label": SENTINEL, "after_world_time_id": anchor}
    first = s.gm.post_raw(_times_url(s), body, key=key)
    again = s.gm.post_raw(_times_url(s), body, key=key)
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    rows = [r for r in s.audit("create_world_time") if r.changed_fields.get("label")]
    assert len(rows) == 1
    assert rows[0].changed_fields["label"] == {"redacted": True}
    assert rows[0].changed_fields["precision"] == "narrative"
    assert SENTINEL not in str(rows[0].changed_fields)
    assert SENTINEL not in str(
        s.connection.execute(
            text(
                "SELECT response_body FROM security.idempotent_requests WHERE idempotency_key = :k"
            ),
            {"k": key},
        ).scalar()
    )


def test_an_archived_campaign_refuses_time_writes(s: ContentSetup) -> None:
    calendar = _create_calendar(s)["calendar_id"]
    s.connection.execute(
        text(
            "UPDATE campaign.campaigns SET lifecycle_status_id = "
            "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
            "WHERE campaign_id = :c"
        ),
        {"c": s.cid},
    )
    response = s.gm.post_raw(
        _times_url(s), {"calendar_id": calendar, "year": 1}, key=s.gm.fresh_key()
    )
    assert response.status_code in (404, 409)
    assert _world_count(s, "core.world_times") == 0
