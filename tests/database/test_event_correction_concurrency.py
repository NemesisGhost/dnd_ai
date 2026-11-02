"""Real-PostgreSQL races for event correction (checkpoint 15.2E-1).

A correction locks the event row, then the state rows it reverses. Two corrections of one
event serialize on the event row (the second sees `voided`); a later change of the state a
correction would reverse, committed first, makes the correction refuse rather than clobber
it. Nothing is mocked; committed fixtures are purged after.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.campaign_clock import advance_campaign_clock
from dnd_ai.commands.character_builds import initialize_character_state
from dnd_ai.commands.character_state import _adjust_hit_points_impl
from dnd_ai.commands.entity_lifecycle import (
    approve_entity,
    publish_entity_as_canon,
    submit_entity_for_review,
)
from dnd_ai.commands.event_corrections import void_event
from dnd_ai.commands.player_characters import create_player_character
from dnd_ai.commands.world_time import create_calendar, create_world_time
from dnd_ai.domain.event_corrections import CorrectionNotReversibleError, EventAlreadyCorrectedError
from dnd_ai.queries.npc_authoring import list_species_options
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

EVENT_ROW = "query LIKE '%narrative.events%FOR UPDATE%'"
STATE_ROW = "query LIKE '%campaign.character_state%FOR UPDATE%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    timeline_id: uuid.UUID
    character_id: uuid.UUID
    times: list[uuid.UUID]
    first_event: uuid.UUID

    def void(self, connection, event_id):  # type: ignore[no-untyped-def]
        return void_event(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            event_id=event_id,
            reason="Race",
        )

    def hurt(self, connection, delta: int):  # type: ignore[no-untyped-def]
        return _adjust_hit_points_impl(
            connection,
            timeline_id=self.timeline_id,
            character_id=self.character_id,
            world_time_id=self.times[1],
            delta=delta,
            campaign_id=self.campaign_id,
        )

    def scalar(self, sql: str, **params: object):  # type: ignore[no-untyped-def]
        with self.engine.connect() as connection:
            return connection.execute(text(sql), params).scalar()


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Correction Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Correction Race World")
        campaign_id = make_authored_campaign(setup, world, name="Correction Race Campaign")
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
        initialize_character_state(
            setup,
            campaign_id=campaign_id,
            actor_user_id=owner,
            character_id=created.entity_id,
            maximum_hit_points=30,
        )
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
        times = [
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
            world_time_id=times[0],
            expected_row_version=0,
        )
        timeline_id = setup.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": campaign_id},
        ).scalar()
        first = _adjust_hit_points_impl(
            setup,
            timeline_id=timeline_id,
            character_id=created.entity_id,
            world_time_id=times[0],
            delta=-5,
            campaign_id=campaign_id,
        )
        assert first.event_id is not None
    yield Fixture(
        postgres_engine, owner, campaign_id, timeline_id, created.entity_id, times, first.event_id
    )
    _purge_user_worlds(postgres_engine, owner)


def test_two_voids_of_one_event_one_wins_the_other_sees_it_voided(fx: Fixture) -> None:
    out = race(
        fx.engine,
        lambda c: fx.void(c, fx.first_event),
        lambda c: fx.void(c, fx.first_event),
        EVENT_ROW,
    )
    assert isinstance(out.get("error"), EventAlreadyCorrectedError), out
    corrections = fx.scalar(
        "SELECT count(*) FROM narrative.event_corrections WHERE corrected_event_id = :e",
        e=fx.first_event,
    )
    assert corrections == 1
    assert (
        fx.scalar(
            "SELECT current_hit_points FROM campaign.character_state WHERE character_id = :c",
            c=fx.character_id,
        )
        == 30
    )


def test_a_void_that_loses_to_a_later_hit_point_change_refuses_and_changes_nothing(
    fx: Fixture,
) -> None:
    out = race(
        fx.engine,
        lambda c: fx.hurt(c, -2),
        lambda c: fx.void(c, fx.first_event),
        STATE_ROW,
    )
    assert isinstance(out.get("error"), CorrectionNotReversibleError), out
    assert (
        fx.scalar(
            "SELECT current_hit_points FROM campaign.character_state WHERE character_id = :c",
            c=fx.character_id,
        )
        == 23
    )
    status = fx.scalar(
        "SELECT es.code FROM narrative.events e JOIN narrative.event_statuses es "
        "ON es.event_status_id = e.event_status_id WHERE e.event_id = :e",
        e=fx.first_event,
    )
    assert status == "recorded"
