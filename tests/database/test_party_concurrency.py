"""Real-PostgreSQL races for party definitions (checkpoint 15.2C-1).

A holder transaction runs a party command and stays uncommitted; a racer thread
issues the competing command and blocks on the party row lock; the holder commits
and the racer's classified outcome is checked. Nothing is mocked.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.parties import archive_party, create_party, update_party
from dnd_ai.domain.authoring import StaleWriteError
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

    def update(self, connection, name: str, version: int):  # type: ignore[no-untyped-def]
        return update_party(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            party_id=self.party_id,
            expected_row_version=version,
            name=name,
        )

    def archive(self, connection, version: int):  # type: ignore[no-untyped-def]
        return archive_party(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            party_id=self.party_id,
            expected_row_version=version,
        )

    def state(self) -> tuple[str, str]:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT p.name, ls.code FROM campaign.parties p JOIN core.lifecycle_statuses ls "
                    "ON ls.lifecycle_status_id = p.lifecycle_status_id WHERE p.party_id = :p"
                ),
                {"p": self.party_id},
            ).one()
        return str(row.name), str(row.code)


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Party Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Party Race World")
        campaign_id = make_authored_campaign(setup, world, name="Party Race Campaign")
        party = create_party(
            setup, campaign_id=campaign_id, actor_user_id=owner, name="Racers"
        ).party_id
    yield Fixture(postgres_engine, owner, campaign_id, party)
    _purge_user_worlds(postgres_engine, owner)


def test_two_edits_from_one_version_one_wins_one_is_stale(fx: Fixture) -> None:
    out = race(
        fx.engine,
        lambda c: fx.update(c, "Winner", 1),
        lambda c: fx.update(c, "Loser", 1),
        PARTY_LOCK,
    )
    assert isinstance(out.get("error"), StaleWriteError), out
    assert fx.state() == ("Winner", "active")


def test_an_edit_that_loses_to_an_archive_is_stale_and_changes_nothing(fx: Fixture) -> None:
    out = race(
        fx.engine,
        lambda c: fx.archive(c, 1),
        lambda c: fx.update(c, "Late", 1),
        PARTY_LOCK,
    )
    assert isinstance(out.get("error"), StaleWriteError), out
    assert fx.state() == ("Racers", "archived")
