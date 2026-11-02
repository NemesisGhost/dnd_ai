"""Real-PostgreSQL races for source attachment (checkpoint 15.3C-1).

Two attaches of one (entity, source) pair serialize on a per-pair advisory lock before any link
row exists, so exactly one link is made and the second is refused; a detach that waits for an
in-flight attach then detaches it. Nothing is mocked; committed fixtures are purged after.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.sources import attach_source, create_source, detach_source
from dnd_ai.domain.source_authoring import SourceAlreadyAttachedError
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_location, make_user

pytestmark = pytest.mark.database

ADVISORY = "query LIKE '%pg_advisory_xact_lock%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    entity_id: uuid.UUID
    source_id: uuid.UUID

    def attach(self, connection):  # type: ignore[no-untyped-def]
        return attach_source(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            entity_id=self.entity_id,
            source_id=self.source_id,
        )

    def detach(self, connection):  # type: ignore[no-untyped-def]
        return detach_source(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            entity_id=self.entity_id,
            source_id=self.source_id,
        )

    def links(self) -> list[bool]:
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    text(
                        "SELECT detached_at IS NULL FROM core.entity_source_links "
                        "WHERE entity_id = :e ORDER BY attached_at"
                    ),
                    {"e": self.entity_id},
                ).scalars()
            )


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Source Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Source Race World")
        campaign_id = make_authored_campaign(setup, world, name="Source Race Campaign")
        entity_id = make_location(setup, world.world_id)
        source = create_source(
            setup,
            campaign_id=campaign_id,
            actor_user_id=owner,
            source_type="session_notes",
            title="Race notes",
        )
    yield Fixture(postgres_engine, owner, campaign_id, entity_id, source.source_id)
    _purge_user_worlds(postgres_engine, owner)


def test_two_attaches_of_one_pair_make_one_link(fx: Fixture) -> None:
    out = race(fx.engine, fx.attach, fx.attach, ADVISORY)
    assert isinstance(out.get("error"), SourceAlreadyAttachedError), out
    assert fx.links() == [True]


def test_a_detach_waits_for_an_attach_and_then_detaches_it(fx: Fixture) -> None:
    out = race(fx.engine, fx.attach, fx.detach, ADVISORY)
    assert out.get("error") is None, out
    assert fx.links() == [False]
