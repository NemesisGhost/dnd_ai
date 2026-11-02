"""Real-PostgreSQL race for build activation (checkpoint 15.2B-2).

Two activations from the same view (`expected_active_build_id`) serialize on the
character's state row `FOR UPDATE`: one wins, the other is a stale write, and no
second event is recorded. Nothing is mocked; committed fixtures are purged after.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.campaign_clock import advance_campaign_clock
from dnd_ai.commands.character_builds import (
    activate_character_build,
    create_character_build,
    initialize_character_state,
)
from dnd_ai.commands.entity_lifecycle import (
    approve_entity,
    publish_entity_as_canon,
    submit_entity_for_review,
)
from dnd_ai.commands.player_characters import create_player_character
from dnd_ai.commands.world_time import create_calendar, create_world_time
from dnd_ai.domain.authoring import StaleWriteError
from dnd_ai.domain.character_builds import BuildInput
from dnd_ai.queries.npc_authoring import list_species_options
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

STATE_LOCK = "query LIKE '%character_state%FOR UPDATE%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    character_id: uuid.UUID
    builds: list[uuid.UUID]

    def activate(self, connection, index: int, expected: uuid.UUID | None):  # type: ignore[no-untyped-def]
        return activate_character_build(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            character_id=self.character_id,
            character_build_id=self.builds[index],
            expected_active_build_id=expected,
        )

    def active(self) -> uuid.UUID | None:
        with self.engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT character_build_id FROM campaign.character_state "
                    "WHERE character_id = :c"
                ),
                {"c": self.character_id},
            ).scalar()
        assert value is None or isinstance(value, uuid.UUID)
        return value

    def events(self) -> int:
        with self.engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT count(*) FROM narrative.events e JOIN narrative.event_types t "
                    "ON t.event_type_id = e.event_type_id "
                    "WHERE e.campaign_id = :c AND t.code = 'character_build_activated'"
                ),
                {"c": self.campaign_id},
            ).scalar()
        assert isinstance(value, int)
        return value


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Build Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Build Race World")
        campaign_id = make_authored_campaign(setup, world, name="Build Race Campaign")
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
        builds = [
            create_character_build(
                setup,
                campaign_id=campaign_id,
                actor_user_id=owner,
                character_id=created.entity_id,
                build=BuildInput(label=label),
            ).character_build_id
            for label in ("One", "Two", "Three")
        ]
        initialize_character_state(
            setup,
            campaign_id=campaign_id,
            actor_user_id=owner,
            character_id=created.entity_id,
            maximum_hit_points=10,
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
        year = create_world_time(
            setup,
            campaign_id=campaign_id,
            actor_user_id=owner,
            calendar_id=calendar.calendar_id,
            year=1,
        ).world_time_id
        advance_campaign_clock(
            setup,
            campaign_id=campaign_id,
            actor_user_id=owner,
            world_time_id=year,
            expected_row_version=0,
        )
        fixture = Fixture(postgres_engine, owner, campaign_id, created.entity_id, builds)
        fixture.activate(setup, 0, None)  # administrative baseline
    yield fixture
    _purge_user_worlds(postgres_engine, owner)


def test_two_activations_from_one_view_one_wins_one_is_stale(fx: Fixture) -> None:
    one = fx.builds[0]
    out = race(
        fx.engine,
        lambda c: fx.activate(c, 1, one),
        lambda c: fx.activate(c, 2, one),
        STATE_LOCK,
    )
    assert isinstance(out.get("error"), StaleWriteError), out
    assert fx.active() == fx.builds[1]
    assert fx.events() == 1  # the racer's event rolled back with it
