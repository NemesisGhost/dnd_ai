"""Real-PostgreSQL race for NPC portrayal saves (checkpoint 15.3A-3, decision D-21).

A save locks the NPC entity `FOR UPDATE` and compares the version number the editor saw, so two
saves from one version serialize: one appends the next version and the other is stale. Nothing
is mocked; committed fixtures are purged after.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.npc_portrayal import save_npc_portrayal_profile
from dnd_ai.commands.npcs import create_npc
from dnd_ai.domain.authoring import StaleWriteError
from dnd_ai.queries.npc_authoring import list_species_options
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

ENTITY_LOCK = "query LIKE '%FOR UPDATE OF e%' OR query LIKE '%FOR SHARE OF e%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    npc_id: uuid.UUID

    def save(self, connection, voice: str):  # type: ignore[no-untyped-def]
        return save_npc_portrayal_profile(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            npc_id=self.npc_id,
            expected_version=0,
            fields={"voice": voice},
        )

    def versions(self) -> list[int]:
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    text(
                        "SELECT version_number FROM character.npc_portrayal_profiles "
                        "WHERE npc_id = :n ORDER BY version_number"
                    ),
                    {"n": self.npc_id},
                ).scalars()
            )


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Portrayal Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Portrayal Race World")
        campaign_id = make_authored_campaign(setup, world, name="Portrayal Race Campaign")
        species = list_species_options(setup, world_id=world.world_id)[0].species_id
        npc = create_npc(
            setup,
            campaign_id=campaign_id,
            actor_user_id=owner,
            name="Racer",
            summary=None,
            species_id=species,
            size_category="medium",
        )
    yield Fixture(postgres_engine, owner, campaign_id, npc.entity_id)  # type: ignore[arg-type]
    _purge_user_worlds(postgres_engine, owner)


def test_two_saves_from_one_version_one_wins_one_is_stale(fx: Fixture) -> None:
    out = race(
        fx.engine, lambda c: fx.save(c, "Winner"), lambda c: fx.save(c, "Loser"), ENTITY_LOCK
    )
    assert isinstance(out.get("error"), StaleWriteError), out
    assert fx.versions() == [1]
