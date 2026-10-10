"""Real-PostgreSQL race for recording travel (checkpoint 15.3A-2c, decision D-20).

A traveler with no open location row has nothing to lock, so two journeys that both start from
"nowhere" are serialized by an advisory lock on (timeline, traveler): the second sees where the
first left the traveler and moves them on, leaving exactly one open row. Nothing is mocked;
committed fixtures are purged after.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.entity_lifecycle import (
    approve_entity,
    publish_entity_as_canon,
    submit_entity_for_review,
)
from dnd_ai.commands.locations import create_location
from dnd_ai.commands.player_characters import create_player_character
from dnd_ai.commands.travel import record_travel
from dnd_ai.commands.world_time import create_calendar, create_world_time
from dnd_ai.queries.npc_authoring import list_species_options
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

TRAVELER_LOCK = "query LIKE '%pg_advisory_xact_lock%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    traveler: uuid.UUID
    places: list[uuid.UUID]
    years: list[uuid.UUID]

    def go(self, connection, place: int, year: int):  # type: ignore[no-untyped-def]
        return record_travel(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            destination_location_id=self.places[place],
            character_ids=[self.traveler],
            world_time_id=self.years[year],
        )

    def rows(self) -> list[tuple[uuid.UUID, bool]]:
        with self.engine.connect() as connection:
            result = connection.execute(
                text(
                    "SELECT location_id, departed_at_world_time_id IS NULL AS open "
                    "FROM campaign.character_location_history WHERE character_id = :c"
                ),
                {"c": self.traveler},
            ).all()
        return [(r.location_id, bool(r.open)) for r in result]


def _publish(setup, campaign_id, owner, entity_id, version):  # type: ignore[no-untyped-def]
    for step in (submit_entity_for_review, approve_entity, publish_entity_as_canon):
        version = step(
            setup,
            campaign_id=campaign_id,
            entity_id=entity_id,
            actor_user_id=owner,
            expected_row_version=version,
        ).row_version
    return version


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Travel Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Travel Race World")
        campaign_id = make_authored_campaign(setup, world, name="Travel Race Campaign")
        places = []
        for name in ("Northmark", "Southmark"):
            created = create_location(
                setup,
                campaign_id=campaign_id,
                actor_user_id=owner,
                category_code="settlement",
                name=name,
                summary=None,
            )
            _publish(setup, campaign_id, owner, created.entity_id, created.row_version)
            places.append(created.entity_id)
        species = list_species_options(setup, world_id=world.world_id)[0].species_id
        traveler = create_player_character(
            setup,
            campaign_id=campaign_id,
            actor_user_id=owner,
            name="Racer",
            summary=None,
            species_id=species,
            size_category="medium",
        )
        _publish(setup, campaign_id, owner, traveler.entity_id, traveler.row_version)
        calendar = create_calendar(
            setup,
            world_id=world.world_id,
            actor_user_id=owner,
            name="Travel Calendar",
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
    yield Fixture(
        postgres_engine,
        owner,
        campaign_id,
        traveler.entity_id,  # type: ignore[arg-type]
        places,  # type: ignore[arg-type]
        years,  # type: ignore[arg-type]
    )
    _purge_user_worlds(postgres_engine, owner)


def test_two_journeys_from_nowhere_leave_one_open_location(fx: Fixture) -> None:
    out = race(fx.engine, lambda c: fx.go(c, 0, 0), lambda c: fx.go(c, 1, 1), TRAVELER_LOCK)
    assert "error" not in out, out
    rows = fx.rows()
    assert len(rows) == 2 and sum(1 for _, is_open in rows if is_open) == 1
    assert (fx.places[1], True) in rows and (fx.places[0], False) in rows
