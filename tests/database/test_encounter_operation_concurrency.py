"""Real-PostgreSQL races for encounter operation (checkpoint 15.3B-2b).

Turns, the end and the abort all lock the encounter `FOR UPDATE`. Two turns that leave the round
and order to the server serialize and take consecutive orders; a turn waiting on an abort is
refused because the encounter is no longer active. Nothing is mocked; committed fixtures are
purged after.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.encounter_operations import abort_encounter
from dnd_ai.commands.encounters import EncounterNotActiveError, _resolve_combat_turn_impl
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_character, make_user, make_world_time

pytestmark = pytest.mark.database

ENCOUNTER_LOCK = "query LIKE '%FROM narrative.encounters WHERE encounter_id%FOR UPDATE%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    encounter_id: uuid.UUID
    time_id: uuid.UUID
    actors: list[uuid.UUID]

    def turn(self, connection, actor: uuid.UUID):  # type: ignore[no-untyped-def]
        return _resolve_combat_turn_impl(
            connection,
            encounter_id=self.encounter_id,
            round_number=None,
            turn_order=None,
            actor_entity_id=actor,
            world_time_id=self.time_id,
            campaign_id=self.campaign_id,
        )

    def orders(self) -> list[int]:
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    text("""
                        SELECT t.turn_order FROM narrative.encounter_turns t
                        JOIN narrative.encounter_rounds r
                          ON r.encounter_round_id = t.encounter_round_id
                        WHERE r.encounter_id = :e ORDER BY t.turn_order
                    """),
                    {"e": self.encounter_id},
                ).scalars()
            )


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Encounter Op Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Encounter Op Race World")
        campaign_id = make_authored_campaign(setup, world, name="Encounter Op Race Campaign")
        timeline_id = setup.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": campaign_id},
        ).scalar()
        time_id = make_world_time(setup, world.world_id, 1)
        encounter_id = setup.execute(
            text("""
                INSERT INTO narrative.encounters
                    (timeline_id, campaign_id, world_time_id, status, current_round)
                VALUES (:t, :c, :w, 'active', 1) RETURNING encounter_id
            """),
            {"t": timeline_id, "c": campaign_id, "w": time_id},
        ).scalar()
        actors = [make_character(setup, world.world_id, name=n) for n in ("Racer A", "Racer B")]
        for actor in actors:
            setup.execute(
                text(
                    "INSERT INTO narrative.encounter_participants "
                    "(encounter_id, participant_entity_id) VALUES (:e, :p)"
                ),
                {"e": encounter_id, "p": actor},
            )
    yield Fixture(postgres_engine, owner, campaign_id, encounter_id, time_id, actors)  # type: ignore[arg-type]
    _purge_user_worlds(postgres_engine, owner)


def test_two_turns_with_no_order_given_take_consecutive_orders(fx: Fixture) -> None:
    out = race(
        fx.engine,
        lambda c: fx.turn(c, fx.actors[0]),
        lambda c: fx.turn(c, fx.actors[1]),
        ENCOUNTER_LOCK,
    )
    assert out.get("error") is None, out
    assert fx.orders() == [0, 1]


def test_a_turn_waits_for_an_abort_and_is_then_refused(fx: Fixture) -> None:
    out = race(
        fx.engine,
        lambda c: abort_encounter(
            c,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            encounter_id=fx.encounter_id,
            world_time_id=fx.time_id,
        ),
        lambda c: fx.turn(c, fx.actors[0]),
        ENCOUNTER_LOCK,
    )
    assert isinstance(out.get("error"), EncounterNotActiveError), out
    assert fx.orders() == []
