"""Real-PostgreSQL races for the campaign clock (checkpoint 15.2W-2).

A holder transaction runs a clock command and stays uncommitted; a racer thread
issues the competing command and blocks on the real lock; the holder commits and
the racer's classified outcome is checked. Nothing is mocked; committed fixtures
are purged afterwards.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.campaign_clock import advance_campaign_clock
from dnd_ai.commands.world_time import create_calendar, create_world_time
from dnd_ai.domain.authoring import StaleWriteError
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

CLOCK_ROW_LOCK = "query LIKE '%timeline_clocks%FOR UPDATE%'"
TRANSACTION_WAIT = "wait_event = 'transactionid'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    years: list[uuid.UUID]

    def advance(self, connection, year_index: int, version: int):  # type: ignore[no-untyped-def]
        return advance_campaign_clock(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            world_time_id=self.years[year_index],
            expected_row_version=version,
        )

    def clock(self) -> tuple[uuid.UUID, int]:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT k.current_world_time_id, k.row_version FROM campaign.timeline_clocks k "
                    "JOIN campaign.campaigns c ON c.timeline_id = k.timeline_id "
                    "WHERE c.campaign_id = :c"
                ),
                {"c": self.campaign_id},
            ).one()
        return row.current_world_time_id, int(row.row_version)

    def events(self) -> int:
        with self.engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT count(*) FROM narrative.events e "
                    "JOIN narrative.event_types t ON t.event_type_id = e.event_type_id "
                    "WHERE e.campaign_id = :c AND t.code = 'time_advanced'"
                ),
                {"c": self.campaign_id},
            ).scalar()
        assert isinstance(value, int)
        return value


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Clock Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Clock Race World")
        campaign_id = make_authored_campaign(setup, world, name="Clock Race Campaign")
        calendar = create_calendar(
            setup,
            world_id=world.world_id,
            actor_user_id=owner,
            name="Race Calendar",
            description=None,
            days_per_week=None,
            epoch_label=None,
            months=[("Only", 100)],
        )
        years = [
            create_world_time(
                setup,
                campaign_id=campaign_id,
                actor_user_id=owner,
                calendar_id=calendar.calendar_id,
                year=year,
            ).world_time_id
            for year in (1, 2, 3)
        ]
    yield Fixture(postgres_engine, owner, campaign_id, years)
    _purge_user_worlds(postgres_engine, owner)


def test_two_advances_with_one_expected_version_one_wins_one_is_stale(fx: Fixture) -> None:
    with fx.engine.begin() as connection:
        fx.advance(connection, 0, 0)
    out = race(
        fx.engine,
        lambda c: fx.advance(c, 1, 1),
        lambda c: fx.advance(c, 2, 1),
        CLOCK_ROW_LOCK,
    )
    assert isinstance(out["error"], StaleWriteError)
    assert fx.clock() == (fx.years[1], 2)
    assert fx.events() == 2  # the racer's event rolled back with it


def test_two_first_advances_one_creates_the_clock_the_other_is_stale(fx: Fixture) -> None:
    out = race(
        fx.engine,
        lambda c: fx.advance(c, 0, 0),
        lambda c: fx.advance(c, 1, 0),
        TRANSACTION_WAIT,
    )
    assert isinstance(out["error"], StaleWriteError), out
    assert fx.clock() == (fx.years[0], 1)
    assert fx.events() == 1
