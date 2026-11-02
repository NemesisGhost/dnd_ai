"""Real-PostgreSQL races for encounter preparation (checkpoint 15.3B-2a).

Every preparation command locks the encounter `FOR UPDATE`, so two adds of one character
serialize (the second is refused) and a preparation edit waits for an in-flight start and is then
refused because the encounter is no longer pending. Nothing is mocked; committed fixtures are
purged after.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.encounter_preparation import add_encounter_participant
from dnd_ai.domain.encounter_preparation import (
    EncounterNotPendingError,
    EncounterParticipantExistsError,
)
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_character, make_session, make_user, make_world_time

pytestmark = pytest.mark.database

ENCOUNTER_LOCK = "query LIKE '%FROM narrative.encounters WHERE encounter_id%FOR UPDATE%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    encounter_id: uuid.UUID
    character: uuid.UUID

    def add(self, connection):  # type: ignore[no-untyped-def]
        return add_encounter_participant(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            encounter_id=self.encounter_id,
            participant_entity_id=self.character,
        )

    def participants(self) -> int:
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM narrative.encounter_participants "
                        "WHERE encounter_id = :e"
                    ),
                    {"e": self.encounter_id},
                ).scalar()
                or 0
            )


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Encounter Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Encounter Race World")
        campaign_id = make_authored_campaign(setup, world, name="Encounter Race Campaign")
        timeline_id = setup.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": campaign_id},
        ).scalar()
        session_id = make_session(setup, campaign_id, 1)
        character = make_character(setup, world.world_id, name="Racer")
        encounter_id = setup.execute(
            text("""
                INSERT INTO narrative.encounters
                    (timeline_id, campaign_id, session_id, world_time_id, status)
                VALUES (:t, :c, :s, :w, 'pending') RETURNING encounter_id
            """),
            {
                "t": timeline_id,
                "c": campaign_id,
                "s": session_id,
                "w": make_world_time(setup, world.world_id, 1),
            },
        ).scalar()
    yield Fixture(postgres_engine, owner, campaign_id, encounter_id, character)  # type: ignore[arg-type]
    _purge_user_worlds(postgres_engine, owner)


def test_two_adds_of_one_character_one_wins_one_is_refused(fx: Fixture) -> None:
    out = race(fx.engine, fx.add, fx.add, ENCOUNTER_LOCK)
    assert isinstance(out.get("error"), EncounterParticipantExistsError), out
    assert fx.participants() == 1


def test_an_add_waits_for_a_start_and_is_then_refused(fx: Fixture) -> None:
    def start(connection) -> None:  # type: ignore[no-untyped-def]
        connection.execute(
            text("SELECT 1 FROM narrative.encounters WHERE encounter_id = :e FOR UPDATE"),
            {"e": fx.encounter_id},
        )
        connection.execute(
            text("UPDATE narrative.encounters SET status = 'active' WHERE encounter_id = :e"),
            {"e": fx.encounter_id},
        )

    out = race(fx.engine, start, fx.add, ENCOUNTER_LOCK)
    assert isinstance(out.get("error"), EncounterNotPendingError), out
    assert fx.participants() == 0
