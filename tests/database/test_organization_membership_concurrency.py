"""Real-PostgreSQL race for organization membership (checkpoint 15.3A-2b, decision D-19).

Two stints for one member and organization that overlap are rejected by the database's exclusion
constraint, which holds under concurrency where an application check could not: when both are
written at once the second waits for the first and then fails as a `membership_overlap`. Nothing
is mocked; committed fixtures are purged after.
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
from dnd_ai.commands.organizations import create_organization
from dnd_ai.commands.player_characters import create_player_character
from dnd_ai.commands.world_relationships import ParticipantInput, create_relationship
from dnd_ai.commands.world_time import create_calendar, create_world_time
from dnd_ai.domain.relationship_authoring import MembershipOverlapError
from dnd_ai.queries.npc_authoring import list_species_options
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

MEMBERSHIP_INSERT = "query LIKE '%INSERT INTO world.organization_memberships%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    organization_id: uuid.UUID
    member_id: uuid.UUID
    years: list[uuid.UUID]

    def join(self, connection, year: int):  # type: ignore[no-untyped-def]
        return create_relationship(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            kind="membership",
            relationship_type="membership",
            participants=[
                ParticipantInput(self.member_id, "member"),
                ParticipantInput(self.organization_id, "organization"),
            ],
            started_world_time_id=self.years[year],
            typed={"role": f"Stint {year}"},
        )

    def count(self) -> int:
        with self.engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT count(*) FROM world.organization_memberships WHERE organization_id = :o"
                ),
                {"o": self.organization_id},
            ).scalar()
        assert isinstance(value, int)
        return value


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
        owner = make_user(setup, "Membership Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Membership Race World")
        campaign_id = make_authored_campaign(setup, world, name="Membership Race Campaign")
        organization = create_organization(
            setup,
            campaign_id=campaign_id,
            actor_user_id=owner,
            kind_code="organization",
            name="Race Guild",
            summary=None,
            typed_fields={"organization_type": "guild"},
        )
        _publish(setup, campaign_id, owner, organization.entity_id, organization.row_version)
        species = list_species_options(setup, world_id=world.world_id)[0].species_id
        member = create_player_character(
            setup,
            campaign_id=campaign_id,
            actor_user_id=owner,
            name="Racer",
            summary=None,
            species_id=species,
            size_category="medium",
        )
        _publish(setup, campaign_id, owner, member.entity_id, member.row_version)
        calendar = create_calendar(
            setup,
            world_id=world.world_id,
            actor_user_id=owner,
            name="Membership Calendar",
            description=None,
            days_per_week=None,
            epoch_label=None,
            months=[("Only", 100)],
        )
        years = [
            create_world_time(
                setup,
                campaign_id=campaign_id,
                actor_user_id=owner,
                calendar_id=calendar.calendar_id,
                year=year,
            ).world_time_id
            for year in range(0, 4)
        ]
    yield Fixture(
        postgres_engine,
        owner,
        campaign_id,
        organization.entity_id,  # type: ignore[arg-type]
        member.entity_id,  # type: ignore[arg-type]
        years,  # type: ignore[arg-type]
    )
    _purge_user_worlds(postgres_engine, owner)


def test_two_overlapping_stints_written_at_once_leave_one(fx: Fixture) -> None:
    out = race(fx.engine, lambda c: fx.join(c, 1), lambda c: fx.join(c, 2), MEMBERSHIP_INSERT)
    assert isinstance(out.get("error"), MembershipOverlapError), out
    assert fx.count() == 1
