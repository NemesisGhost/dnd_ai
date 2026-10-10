"""Real-PostgreSQL races for session play (checkpoint 15.2D-2).

Start serializes on a per-campaign advisory lock (and a unique partial index backs
it); end and participant changes serialize on the session row; a log entry shares the
row so it either lands before an end or sees the ended session. Nothing is mocked;
committed fixtures are purged after.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.campaign_clock import advance_campaign_clock
from dnd_ai.commands.entity_lifecycle import (
    approve_entity,
    publish_entity_as_canon,
    submit_entity_for_review,
)
from dnd_ai.commands.player_characters import create_player_character
from dnd_ai.commands.session_authoring import schedule_session
from dnd_ai.commands.session_play import (
    add_session_participant,
    end_session,
    record_session_log_entry,
    start_session,
)
from dnd_ai.commands.world_time import create_calendar, create_world_time
from dnd_ai.domain.authoring import StaleWriteError
from dnd_ai.domain.session_authoring import (
    AnotherSessionInProgressError,
    SessionNotInProgressError,
)
from dnd_ai.queries.npc_authoring import list_species_options
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

ADVISORY = "query LIKE '%pg_advisory_xact_lock%'"
SESSION_ROW = (
    "query LIKE '%campaign.sessions%FOR UPDATE%' OR query LIKE '%campaign.sessions%FOR SHARE%'"
)


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    first: uuid.UUID
    second: uuid.UUID
    character_id: uuid.UUID

    def start(self, connection, session_id, version: int = 1):  # type: ignore[no-untyped-def]
        return start_session(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            session_id=session_id,
            expected_row_version=version,
        )

    def end(self, connection, session_id, version: int):  # type: ignore[no-untyped-def]
        return end_session(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            session_id=session_id,
            expected_row_version=version,
            end_world_time_id=None,
        )

    def log(self, connection, session_id):  # type: ignore[no-untyped-def]
        return record_session_log_entry(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            session_id=session_id,
            entry="An entry",
        )

    def add(self, connection, session_id, version: int):  # type: ignore[no-untyped-def]
        return add_session_participant(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            session_id=session_id,
            expected_row_version=version,
            character_id=self.character_id,
            participation_role="player_character",
        )

    def scalar(self, sql: str, **params: object):  # type: ignore[no-untyped-def]
        with self.engine.connect() as connection:
            return connection.execute(text(sql), params).scalar()


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Play Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Play Race World")
        campaign_id = make_authored_campaign(setup, world, name="Play Race Campaign")
        species = list_species_options(setup, world_id=world.world_id)[0].species_id
        created = create_player_character(
            setup,
            campaign_id=campaign_id,
            actor_user_id=owner,
            name="Racer",
            summary=None,
            species_id=species,
            size_category="medium",
        )
        version = created.row_version
        for step in (submit_entity_for_review, approve_entity, publish_entity_as_canon):
            version = step(
                setup,
                campaign_id=campaign_id,
                entity_id=created.entity_id,
                actor_user_id=owner,
                expected_row_version=version,
            ).row_version
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
            for year in (1, 2)
        ]
        advance_campaign_clock(
            setup,
            campaign_id=campaign_id,
            actor_user_id=owner,
            world_time_id=years[0],
            expected_row_version=0,
        )
        first = schedule_session(
            setup, campaign_id=campaign_id, actor_user_id=owner, title="One", scheduled_for=None
        ).session_id
        second = schedule_session(
            setup, campaign_id=campaign_id, actor_user_id=owner, title="Two", scheduled_for=None
        ).session_id
    yield Fixture(postgres_engine, owner, campaign_id, first, second, created.entity_id)
    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text(
                "DELETE FROM campaign.session_participants WHERE session_id IN "
                "(SELECT session_id FROM campaign.sessions WHERE campaign_id = :c)"
            ),
            {"c": campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.sessions WHERE campaign_id = :c"), {"c": campaign_id}
        )
    _purge_user_worlds(postgres_engine, owner)


def test_two_starts_in_one_campaign_one_wins_the_other_sees_a_session_in_progress(
    fx: Fixture,
) -> None:
    out = race(
        fx.engine,
        lambda c: fx.start(c, fx.first),
        lambda c: fx.start(c, fx.second),
        ADVISORY,
    )
    assert isinstance(out.get("error"), AnotherSessionInProgressError), out
    started = fx.scalar(
        "SELECT count(*) FROM campaign.sessions WHERE campaign_id = :c AND started_at IS NOT NULL",
        c=fx.campaign_id,
    )
    assert started == 1


def test_an_end_that_loses_to_a_participant_change_is_stale(fx: Fixture) -> None:
    with fx.engine.begin() as connection:
        fx.start(connection, fx.first)
    version = fx.scalar(
        "SELECT row_version FROM campaign.sessions WHERE session_id = :s", s=fx.first
    )
    out = race(
        fx.engine,
        lambda c: fx.add(c, fx.first, version),
        lambda c: fx.end(c, fx.first, version),
        SESSION_ROW,
    )
    assert isinstance(out.get("error"), StaleWriteError), out
    assert (
        fx.scalar("SELECT ended_at FROM campaign.sessions WHERE session_id = :s", s=fx.first)
        is None
    )


def test_a_log_entry_that_loses_to_an_end_sees_the_ended_session(fx: Fixture) -> None:
    with fx.engine.begin() as connection:
        fx.start(connection, fx.first)
    version = fx.scalar(
        "SELECT row_version FROM campaign.sessions WHERE session_id = :s", s=fx.first
    )
    # The end needs a later time than the start; move the clock first.
    with fx.engine.begin() as connection:
        year2 = connection.execute(
            text(
                "SELECT world_time_id FROM core.world_times wt JOIN campaign.campaigns c ON TRUE "
                "WHERE c.campaign_id = :c AND wt.year = 2 LIMIT 1"
            ),
            {"c": fx.campaign_id},
        ).scalar()
        advance_campaign_clock(
            connection,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            world_time_id=year2,
            expected_row_version=1,
        )
    out = race(
        fx.engine,
        lambda c: fx.end(c, fx.first, version),
        lambda c: fx.log(c, fx.first),
        SESSION_ROW,
    )
    assert isinstance(out.get("error"), SessionNotInProgressError), out
    assert fx.scalar("SELECT count(*) FROM narrative.events WHERE session_id = :s", s=fx.first) == 0
