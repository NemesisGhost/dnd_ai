"""Real-PostgreSQL race: archiving a player character against linking a player to it
(checkpoint 15.2B-1).

Both commands lock the character's `core.entities` row `FOR UPDATE`, and the archive
guard is evaluated only after that lock, so whichever commits second sees the
other's result: an archive that loses to a grant is refused, and a grant that loses
to an archive is refused. Nothing is mocked; committed fixtures are purged after.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.access_grants import grant_character_relationship
from dnd_ai.commands.entity_lifecycle import (
    approve_entity,
    archive_entity,
    publish_entity_as_canon,
    submit_entity_for_review,
)
from dnd_ai.commands.player_characters import create_player_character
from dnd_ai.domain.authoring import CharacterHasUserRelationshipsError
from dnd_ai.queries.npc_authoring import list_species_options
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import ENTITY_LOCK, race
from tests.factories import make_campaign_membership, make_user

pytestmark = [pytest.mark.database, pytest.mark.real_relationship_policy]


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    world_id: uuid.UUID
    campaign_id: uuid.UUID
    owner_membership: uuid.UUID
    player_membership: uuid.UUID
    character_id: uuid.UUID
    version: int

    def archive(self, connection):  # type: ignore[no-untyped-def]
        return archive_entity(
            connection,
            campaign_id=self.campaign_id,
            entity_id=self.character_id,
            actor_user_id=self.owner,
            expected_row_version=self.version,
        )

    def grant(self, connection):  # type: ignore[no-untyped-def]
        return grant_character_relationship(
            connection,
            campaign_membership_id=self.player_membership,
            character_id=self.character_id,
            relationship_type_code="owner",
            campaign_id=self.campaign_id,
            expected_world_id=self.world_id,
            granted_by_membership_id=self.owner_membership,
        )

    def relationships(self) -> int:
        with self.engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT count(*) FROM security.membership_character_relationships "
                    "WHERE character_id = :c AND revoked_at IS NULL"
                ),
                {"c": self.character_id},
            ).scalar()
        assert isinstance(value, int)
        return value

    def lifecycle(self) -> str:
        with self.engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT ls.code FROM core.entities e JOIN core.lifecycle_statuses ls "
                    "ON ls.lifecycle_status_id = e.lifecycle_status_id WHERE e.entity_id = :c"
                ),
                {"c": self.character_id},
            ).scalar()
        assert isinstance(value, str)
        return value


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "PC Race Owner")
        player = make_user(setup, "PC Race Player")
        world = make_authored_world(setup, owner_user_id=owner, name="PC Race World")
        campaign_id = make_authored_campaign(setup, world, name="PC Race Campaign")
        owner_membership = setup.execute(
            text(
                "SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u"
            ),
            {"c": campaign_id, "u": owner},
        ).scalar()
        assert isinstance(owner_membership, uuid.UUID)
        player_membership = make_campaign_membership(setup, campaign_id, player)
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
    yield Fixture(
        postgres_engine,
        owner,
        world.world_id,
        campaign_id,
        owner_membership,
        player_membership,
        created.entity_id,
        version,
    )
    _purge_user_worlds(postgres_engine, owner)


def test_an_archive_that_loses_to_a_grant_is_refused(fx: Fixture) -> None:
    out = race(fx.engine, fx.grant, fx.archive, ENTITY_LOCK)
    assert isinstance(out.get("error"), CharacterHasUserRelationshipsError), out
    assert fx.relationships() == 1
    assert fx.lifecycle() == "active"


def test_a_grant_that_loses_to_an_archive_is_refused(fx: Fixture) -> None:
    out = race(fx.engine, fx.archive, fx.grant, ENTITY_LOCK)
    assert "error" in out, out
    assert fx.relationships() == 0
    assert fx.lifecycle() == "archived"
