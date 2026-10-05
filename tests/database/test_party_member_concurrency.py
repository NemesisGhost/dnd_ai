"""Real-PostgreSQL races for party membership (checkpoint 15.2C-2).

Every membership command locks the party row `FOR UPDATE` first, so concurrent
commands serialize: the second one sees the first one's party version bump and
membership rows. Nothing is mocked; committed fixtures are purged after.
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
from dnd_ai.commands.parties import archive_party, create_party
from dnd_ai.commands.party_members import add_party_member
from dnd_ai.commands.player_characters import create_player_character
from dnd_ai.commands.world_time import create_calendar, create_world_time
from dnd_ai.domain.authoring import StaleWriteError
from dnd_ai.domain.party_authoring import PartyMembershipOverlapError, PartyNotActiveError
from dnd_ai.queries.npc_authoring import list_species_options
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

PARTY_LOCK = "query LIKE '%campaign.parties%FOR UPDATE%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    party_id: uuid.UUID
    character_id: uuid.UUID
    times: list[uuid.UUID]

    def add(self, connection, version: int, time_index: int = 0):  # type: ignore[no-untyped-def]
        return add_party_member(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            party_id=self.party_id,
            character_id=self.character_id,
            effective_from_world_time_id=self.times[time_index],
            expected_party_row_version=version,
        )

    def archive(self, connection, version: int):  # type: ignore[no-untyped-def]
        return archive_party(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            party_id=self.party_id,
            expected_row_version=version,
        )

    def memberships(self) -> int:
        with self.engine.connect() as connection:
            value = connection.execute(
                text("SELECT count(*) FROM campaign.party_memberships WHERE party_id = :p"),
                {"p": self.party_id},
            ).scalar()
        assert isinstance(value, int)
        return value

    def join_events(self) -> int:
        with self.engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT count(*) FROM narrative.events e JOIN narrative.event_types t "
                    "ON t.event_type_id = e.event_type_id "
                    "WHERE e.campaign_id = :c AND t.code = 'party_member_joined'"
                ),
                {"c": self.campaign_id},
            ).scalar()
        assert isinstance(value, int)
        return value


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Member Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Member Race World")
        campaign_id = make_authored_campaign(setup, world, name="Member Race Campaign")
        party_id = create_party(
            setup, campaign_id=campaign_id, actor_user_id=owner, name="Racers"
        ).party_id
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
    yield Fixture(postgres_engine, owner, campaign_id, party_id, created.entity_id, times)
    _purge_user_worlds(postgres_engine, owner)


def test_two_adds_from_one_party_version_one_wins_one_is_stale(fx: Fixture) -> None:
    out = race(fx.engine, lambda c: fx.add(c, 1), lambda c: fx.add(c, 1, 1), PARTY_LOCK)
    assert isinstance(out.get("error"), StaleWriteError), out
    assert fx.memberships() == 1 and fx.join_events() == 1


def test_a_second_add_that_saw_the_new_version_is_an_overlap_not_a_500(fx: Fixture) -> None:
    out = race(fx.engine, lambda c: fx.add(c, 1), lambda c: fx.add(c, 2, 1), PARTY_LOCK)
    assert isinstance(out.get("error"), PartyMembershipOverlapError), out
    assert fx.memberships() == 1 and fx.join_events() == 1


def test_an_add_that_loses_to_an_archive_is_stale_and_writes_nothing(fx: Fixture) -> None:
    out = race(fx.engine, lambda c: fx.archive(c, 1), lambda c: fx.add(c, 1), PARTY_LOCK)
    assert isinstance(out.get("error"), StaleWriteError), out
    assert fx.memberships() == 0 and fx.join_events() == 0


def test_an_add_that_saw_the_archived_party_is_refused(fx: Fixture) -> None:
    out = race(fx.engine, lambda c: fx.archive(c, 1), lambda c: fx.add(c, 2), PARTY_LOCK)
    assert isinstance(out.get("error"), PartyNotActiveError), out
    assert fx.memberships() == 0
