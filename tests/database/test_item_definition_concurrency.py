"""Real-PostgreSQL races for item definition authoring (checkpoint 15.3B-1a, decision D-22).

Two creates of one name serialize on the world definition advisory lock and end with two
distinct codes; two updates from one `row_version` serialize on the definition row lock and one
is stale. Nothing is mocked; committed fixtures are purged after.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.item_definitions import create_item_definition, update_item_definition
from dnd_ai.domain.authoring import StaleWriteError
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

ADVISORY = "query LIKE '%pg_advisory_xact_lock%'"
DEFINITION_LOCK = "query LIKE '%FOR UPDATE OF d%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID

    def create(self, connection, name: str = "Racer Blade"):  # type: ignore[no-untyped-def]
        return create_item_definition(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            name=name,
            category="weapon",
        )

    def update(self, connection, definition_id: uuid.UUID, description: str):  # type: ignore[no-untyped-def]
        return update_item_definition(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            item_definition_id=definition_id,
            expected_row_version=1,
            name="Racer Blade",
            category="weapon",
            description=description,
        )

    def codes(self) -> list[str]:
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    text(
                        "SELECT code FROM rules.item_definitions d "
                        "JOIN campaign.campaigns c ON c.campaign_id = :c "
                        "JOIN campaign.timelines t ON t.timeline_id = c.timeline_id "
                        "WHERE d.owning_world_id = t.world_id ORDER BY code"
                    ),
                    {"c": self.campaign_id},
                ).scalars()
            )


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Definition Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Definition Race World")
        campaign_id = make_authored_campaign(setup, world, name="Definition Race Campaign")
    yield Fixture(postgres_engine, owner, campaign_id)
    _purge_user_worlds(postgres_engine, owner)


def test_two_creates_of_one_name_get_distinct_codes(fx: Fixture) -> None:
    out = race(fx.engine, lambda c: fx.create(c), lambda c: fx.create(c), ADVISORY)
    assert out.get("error") is None, out
    assert fx.codes() == ["racer_blade", "racer_blade_2"]


def test_two_updates_from_one_version_one_wins_one_is_stale(fx: Fixture) -> None:
    with fx.engine.begin() as connection:
        definition_id = fx.create(connection).item_definition_id
    out = race(
        fx.engine,
        lambda c: fx.update(c, definition_id, "Winner"),
        lambda c: fx.update(c, definition_id, "Loser"),
        DEFINITION_LOCK,
    )
    assert isinstance(out.get("error"), StaleWriteError), out
    with fx.engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT description, row_version FROM rules.item_definitions "
                "WHERE item_definition_id = :d"
            ),
            {"d": definition_id},
        ).one()
    assert row.description == "Winner" and row.row_version == 2
