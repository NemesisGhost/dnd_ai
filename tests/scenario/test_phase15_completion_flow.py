"""Phase 15 completion exit scenario (PLANv2 15.8, built incrementally).

A GM sets up and runs a campaign using only the HTTP API with a real cookie
session, CSRF token, and Origin check on every write: no SQL, no seed script, no
Foundry, no importer, no AI. Each Phase 15 completion checkpoint appends its
steps to this one flow and keeps the earlier steps green; checkpoint 15.4 runs the
whole flow against a freshly migrated database.

Steps implemented so far (numbering follows the plan's §11 table):

  1  create a world (owner)                 -- Phase 14, via the shared setup
  2  create a campaign                      -- Phase 14, via the shared setup
  3  calendar and world times               -- 15.2W-1
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup

pytestmark = pytest.mark.scenario


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


def test_a_gm_sets_up_and_runs_a_campaign(
    harness: AuthoringHarness, db_connection: Connection
) -> None:
    # Steps 1-2: the shared setup creates the world, timeline, and campaign through
    # the production routes (a GM who owns the world, a player, and an outsider).
    s = ContentSetup(harness, db_connection)

    def write(path: str, body: dict, status: int = 201) -> dict:
        response = s.gm.post_raw(path, body, key=s.gm.fresh_key())
        assert response.status_code == status, (path, response.text)
        return response.json()

    # --- Step 3 (15.2W-1): a calendar, calendar dates, and a narrative moment ----------
    calendar = write(
        f"/worlds/{s.world_id}/calendars",
        {
            "name": "Common Reckoning",
            "description": None,
            "days_per_week": 7,
            "epoch_label": "Founding",
            "months": [{"name": "Frost", "day_count": 30}, {"name": "Bloom", "day_count": 30}],
        },
    )
    times = f"/campaigns/{s.cid}/world-times"
    opening = write(
        times, {"calendar_id": calendar["calendar_id"], "year": 1, "month_number": 1, "day": 1}
    )
    siege = write(
        times, {"label": "After the siege", "after_world_time_id": opening["world_time_id"]}
    )
    listed = s.gm.get(times).json()["items"]
    assert [i["world_time_id"] for i in listed] == [
        siege["world_time_id"],
        opening["world_time_id"],
    ]
    assert listed[1]["display"] == "Year 1 (Founding), Frost 1"
    # The player sees none of this authoring surface.
    assert s.player.get(times).status_code == 403
    assert s.player.post_raw(times, {"label": "x", "after_world_time_id": None}).status_code == 403
