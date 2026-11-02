"""Real-PostgreSQL races for world-time sort-key allocation (checkpoint 15.2W-1).

Two narrative placements into the same gap must serialize on the per-world
advisory lock, so the second sees the first's committed key and allocates
strictly between its anchor and that key: both points exist and chronology stays
ordered. Nothing is mocked; committed fixtures are purged afterwards.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.world_time import create_calendar, create_world_time
from dnd_ai.domain.world_time import WorldTimeNoGapError
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

ADVISORY = "wait_event = 'advisory'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    world_id: uuid.UUID
    campaign_id: uuid.UUID

    def key(self, world_time_id: uuid.UUID) -> int:
        with self.engine.connect() as connection:
            value = connection.execute(
                text("SELECT sort_key FROM core.world_times WHERE world_time_id = :t"),
                {"t": world_time_id},
            ).scalar()
        assert isinstance(value, int)
        return value


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "World Time Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="World Time Race World")
        campaign_id = make_authored_campaign(setup, world, name="World Time Race Campaign")
    yield Fixture(postgres_engine, owner, world.world_id, campaign_id)
    _purge_user_worlds(postgres_engine, owner)


def _two_anchors(fx: Fixture) -> tuple[uuid.UUID, uuid.UUID]:
    """Two calendar points 1000 minutes apart: a gap for narrative placements."""
    with fx.engine.begin() as connection:
        calendar = create_calendar(
            connection,
            world_id=fx.world_id,
            actor_user_id=fx.owner,
            name="Race Calendar",
            description=None,
            days_per_week=None,
            epoch_label=None,
            months=[("Only", 400)],
        )
        first = create_world_time(
            connection,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            calendar_id=calendar.calendar_id,
            year=0,
        )
        later = create_world_time(
            connection,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            calendar_id=calendar.calendar_id,
            year=0,
            month_number=1,
            day=1,
            hour=16,
            minute=40,
        )
    assert fx.key(later.world_time_id) - fx.key(first.world_time_id) == 1000
    return first.world_time_id, later.world_time_id


def test_two_placements_in_one_gap_serialize_and_stay_ordered(fx: Fixture) -> None:
    anchor, upper = _two_anchors(fx)

    def place(connection, label):  # type: ignore[no-untyped-def]
        return create_world_time(
            connection,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            label=label,
            after_world_time_id=anchor,
        )

    held: dict[str, object] = {}

    def hold(connection) -> None:  # type: ignore[no-untyped-def]
        held["result"] = place(connection, "First placement")

    out = race(fx.engine, hold, lambda c: place(c, "Second placement"), ADVISORY)
    assert "error" not in out, out.get("error")
    first = held["result"]
    second = out["value"]
    keys = [
        fx.key(anchor),
        fx.key(second.world_time_id),
        fx.key(first.world_time_id),
        fx.key(upper),
    ]
    # The second saw the first's committed key as the next point after the anchor.
    assert keys == sorted(keys) and len(set(keys)) == 4


def test_a_closed_gap_is_refused_under_the_same_race(fx: Fixture) -> None:
    anchor, _upper = _two_anchors(fx)
    # Close the gap right after the anchor: a point one minute later.
    with fx.engine.begin() as connection:
        calendar_id = connection.execute(
            text("SELECT calendar_id FROM core.world_times WHERE world_time_id = :t"),
            {"t": anchor},
        ).scalar()
        create_world_time(
            connection,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            calendar_id=calendar_id,
            year=0,
            month_number=1,
            day=1,
            hour=0,
            minute=1,
        )
    with fx.engine.begin() as connection, pytest.raises(WorldTimeNoGapError):
        create_world_time(
            connection,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            label="No room",
            after_world_time_id=anchor,
        )
