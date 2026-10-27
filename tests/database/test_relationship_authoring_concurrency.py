"""Real-PostgreSQL races for world relationship authoring (checkpoint 15.3A-2a, D-18).

Every relationship command locks its participants `FOR SHARE` and the relationship row `FOR
UPDATE`, so two editors serialize (a second edit from the same version is stale), a state change
waits for an archive and then refuses, and a relationship cannot be created with a participant
that a concurrent archive just removed. Nothing is mocked; committed fixtures are purged after.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.campaign_clock import advance_campaign_clock
from dnd_ai.commands.entity_lifecycle import (
    approve_entity,
    archive_entity,
    publish_entity_as_canon,
    submit_entity_for_review,
)
from dnd_ai.commands.locations import create_location
from dnd_ai.commands.relationships import _evolve_relationship_reaction_impl
from dnd_ai.commands.world_relationships import (
    ParticipantInput,
    archive_relationship,
    create_relationship,
    update_relationship,
)
from dnd_ai.commands.world_time import create_calendar, create_world_time
from dnd_ai.domain.authoring import StaleWriteError
from dnd_ai.domain.relationship_authoring import (
    RelationshipArchivedError,
    RelationshipParticipantInvalidError,
)
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

ENTITY_LOCK = "query LIKE '%FOR UPDATE OF e%' OR query LIKE '%FOR SHARE OF e%'"
RELATIONSHIP_LOCK = "query LIKE '%world.relationships%FOR UPDATE%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    timeline_id: uuid.UUID
    north: uuid.UUID
    south: uuid.UUID
    relationship_id: uuid.UUID
    version: int
    time_id: uuid.UUID

    def update(self, connection, description: str, version: int):  # type: ignore[no-untyped-def]
        return update_relationship(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            relationship_id=self.relationship_id,
            expected_row_version=version,
            description=description,
            started_world_time_id=None,
        )

    def scalar(self, sql: str, **params: object):  # type: ignore[no-untyped-def]
        with self.engine.connect() as connection:
            return connection.execute(text(sql), params).scalar()


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
        owner = make_user(setup, "Relationship Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Relationship Race World")
        campaign_id = make_authored_campaign(setup, world, name="Relationship Race Campaign")
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
        relationship = create_relationship(
            setup,
            campaign_id=campaign_id,
            actor_user_id=owner,
            kind="general",
            relationship_type="adjacency",
            participants=[
                ParticipantInput(places[0], "subject"),  # type: ignore[arg-type]
                ParticipantInput(places[1], "object"),  # type: ignore[arg-type]
            ],
        )
        calendar = create_calendar(
            setup,
            world_id=world.world_id,
            actor_user_id=owner,
            name="Relationship Calendar",
            description=None,
            days_per_week=None,
            epoch_label=None,
            months=[("Only", 100)],
        )
        time_id = create_world_time(
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
            world_time_id=time_id,
            expected_row_version=0,
        )
        timeline_id = setup.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": campaign_id},
        ).scalar()
    yield Fixture(
        postgres_engine,
        owner,
        campaign_id,
        timeline_id,
        places[0],  # type: ignore[arg-type]
        places[1],  # type: ignore[arg-type]
        relationship.relationship_id,
        relationship.row_version,
        time_id,
    )
    _purge_user_worlds(postgres_engine, owner)


def test_two_edits_from_one_version_one_wins_one_is_stale(fx: Fixture) -> None:
    out = race(
        fx.engine,
        lambda c: fx.update(c, "Winner", fx.version),
        lambda c: fx.update(c, "Loser", fx.version),
        RELATIONSHIP_LOCK,
    )
    assert isinstance(out.get("error"), StaleWriteError), out
    assert (
        fx.scalar(
            "SELECT description FROM world.relationships WHERE relationship_id = :r",
            r=fx.relationship_id,
        )
        == "Winner"
    )


def test_a_state_change_that_loses_to_an_archive_is_refused(fx: Fixture) -> None:
    out = race(
        fx.engine,
        lambda c: archive_relationship(
            c,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            relationship_id=fx.relationship_id,
            expected_row_version=fx.version,
        ),
        lambda c: _evolve_relationship_reaction_impl(
            c,
            relationship_id=fx.relationship_id,
            timeline_id=fx.timeline_id,
            world_time_id=fx.time_id,
            new_status_code="strained",
        ),
        RELATIONSHIP_LOCK,
    )
    assert isinstance(out.get("error"), RelationshipArchivedError), out
    assert (
        fx.scalar(
            "SELECT count(*) FROM campaign.relationship_state WHERE relationship_id = :r",
            r=fx.relationship_id,
        )
        == 0
    )


def test_creating_with_a_participant_that_was_just_archived_is_refused(fx: Fixture) -> None:
    version = fx.scalar("SELECT row_version FROM core.entities WHERE entity_id = :e", e=fx.south)
    out = race(
        fx.engine,
        lambda c: archive_entity(
            c,
            campaign_id=fx.campaign_id,
            entity_id=fx.south,
            actor_user_id=fx.owner,
            expected_row_version=version,
        ),
        lambda c: create_relationship(
            c,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            kind="general",
            relationship_type="other",
            participants=[
                ParticipantInput(fx.north, "subject"),
                ParticipantInput(fx.south, "object"),
            ],
        ),
        ENTITY_LOCK,
    )
    assert isinstance(out.get("error"), RelationshipParticipantInvalidError), out
    assert (
        fx.scalar(
            "SELECT count(*) FROM world.relationships WHERE relationship_id <> :r AND world_id = "
            "(SELECT world_id FROM world.relationships WHERE relationship_id = :r)",
            r=fx.relationship_id,
        )
        == 0
    )
