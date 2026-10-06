"""Real-PostgreSQL races for item operations (checkpoint 15.3B-1b).

Every operation locks the item instance `FOR UPDATE` and compares the item's last-event token, so
two operations from one token serialize and the second is stale; a character's attunements
serialize on a per-character advisory lock so the three-item limit cannot be passed. Nothing is
mocked; committed fixtures are purged after.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.campaign_clock import advance_campaign_clock
from dnd_ai.commands.entity_lifecycle import (
    approve_entity,
    publish_entity_as_canon,
    submit_entity_for_review,
)
from dnd_ai.commands.item_definitions import create_item_definition
from dnd_ai.commands.item_instances import create_item_instance
from dnd_ai.commands.item_operations import (
    attune_item,
    award_item,
    destroy_item,
    transfer_in_context,
)
from dnd_ai.commands.npcs import create_npc
from dnd_ai.commands.world_time import create_calendar, create_world_time
from dnd_ai.domain.authoring import StaleWriteError
from dnd_ai.domain.item_runtime import AttunementNotAllowedError
from dnd_ai.queries.npc_authoring import list_species_options
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

ITEM_LOCK = "query LIKE '%FROM world.item_instances WHERE item_instance_id%FOR UPDATE%'"
ADVISORY = "query LIKE '%pg_advisory_xact_lock%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    world_id: uuid.UUID
    timeline_id: uuid.UUID
    holder: uuid.UUID

    def publish(self, connection, entity_id: uuid.UUID, version: int) -> None:  # type: ignore[no-untyped-def]
        for step in (submit_entity_for_review, approve_entity, publish_entity_as_canon):
            version = step(
                connection,
                campaign_id=self.campaign_id,
                entity_id=entity_id,
                actor_user_id=self.owner,
                expected_row_version=version,
            ).row_version

    def item(self, connection, name: str, definition: uuid.UUID) -> uuid.UUID:  # type: ignore[no-untyped-def]
        made = create_item_instance(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            name=name,
            summary=None,
            item_definition_id=definition,
        )
        self.publish(connection, made.entity_id, made.row_version)
        return made.entity_id  # type: ignore[return-value]

    def definition(self, connection, name: str, *, attunement: bool) -> uuid.UUID:  # type: ignore[no-untyped-def]
        return create_item_definition(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            name=name,
            category="wondrous_item",
            requires_attunement=attunement,
            canon_status="canon",
        ).item_definition_id

    def award(self, connection, item: uuid.UUID, token=None):  # type: ignore[no-untyped-def]
        return award_item(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            item_instance_id=item,
            holder_entity_id=self.holder,
            expected_last_event_id=token,
        )

    def token(self, item: uuid.UUID) -> uuid.UUID | None:
        with self.engine.connect() as connection:
            return connection.execute(  # type: ignore[no-any-return]
                text(
                    "SELECT last_event_id FROM campaign.item_state "
                    "WHERE item_instance_id = :i AND timeline_id = :t"
                ),
                {"i": item, "t": self.timeline_id},
            ).scalar()

    def count(self, sql: str, **params: object) -> int:
        with self.engine.connect() as connection:
            return int(connection.execute(text(sql), params).scalar() or 0)


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Item Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Item Race World")
        campaign_id = make_authored_campaign(setup, world, name="Item Race Campaign")
        timeline_id = setup.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": campaign_id},
        ).scalar()
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
        holder = npc.entity_id
        fixture = Fixture(postgres_engine, owner, campaign_id, world.world_id, timeline_id, holder)  # type: ignore[arg-type]
        fixture.publish(setup, holder, npc.row_version)  # type: ignore[arg-type]
        calendar = create_calendar(
            setup,
            world_id=world.world_id,
            actor_user_id=owner,
            name="Item Calendar",
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
    yield fixture
    _purge_user_worlds(postgres_engine, owner)


def test_two_awards_from_one_token_one_wins_one_is_stale(fx: Fixture) -> None:
    with fx.engine.begin() as setup:
        definition = fx.definition(setup, "Plain Blade", attunement=False)
        item = fx.item(setup, "Blade", definition)
    out = race(fx.engine, lambda c: fx.award(c, item), lambda c: fx.award(c, item), ITEM_LOCK)
    assert isinstance(out.get("error"), StaleWriteError), out
    assert (
        fx.count(
            "SELECT count(*) FROM campaign.inventory_entries WHERE item_instance_id = :i", i=item
        )
        == 1
    )
    assert (
        fx.count("SELECT count(*) FROM campaign.item_state WHERE item_instance_id = :i", i=item)
        == 1
    )


def test_a_destroy_and_a_transfer_from_one_token_serialize(fx: Fixture) -> None:
    with fx.engine.begin() as setup:
        definition = fx.definition(setup, "Plain Blade", attunement=False)
        item = fx.item(setup, "Blade", definition)
        token = fx.award(setup, item).event_id
    out = race(
        fx.engine,
        lambda c: destroy_item(
            c,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            item_instance_id=item,
            expected_last_event_id=token,
            world_time_id=None,
            session_id=None,
            note=None,
        ),
        lambda c: transfer_in_context(
            c,
            world_id=fx.world_id,
            timeline_id=fx.timeline_id,
            campaign_id=fx.campaign_id,
            item_id=item,
            time_id=_clock(fx),
            holder_entity_id=None,
            container_id=None,
            location_id=None,
            expected=token,
        ),
        ITEM_LOCK,
    )
    assert isinstance(out.get("error"), StaleWriteError), out
    assert (
        fx.count(
            "SELECT count(*) FROM campaign.item_state WHERE item_instance_id = :i AND is_destroyed",
            i=item,
        )
        == 1
    )


def _clock(fx: Fixture) -> uuid.UUID:
    with fx.engine.connect() as connection:
        value = connection.execute(
            text(
                "SELECT current_world_time_id FROM campaign.timeline_clocks WHERE timeline_id = :t"
            ),
            {"t": fx.timeline_id},
        ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def test_two_attunements_cannot_pass_the_three_item_limit(fx: Fixture) -> None:
    with fx.engine.begin() as setup:
        definition = fx.definition(setup, "Ring", attunement=True)
        rings = [fx.item(setup, f"Ring {n}", definition) for n in range(4)]
        for ring in rings:
            fx.award(setup, ring)
        for ring in rings[:2]:
            attune_item(
                setup,
                campaign_id=fx.campaign_id,
                actor_user_id=fx.owner,
                item_instance_id=ring,
                character_id=fx.holder,
                expected_last_event_id=_token_in(setup, fx, ring),
            )
        tokens = [_token_in(setup, fx, ring) for ring in rings[2:]]

    def attune(connection, ring: uuid.UUID, token):  # type: ignore[no-untyped-def]
        return attune_item(
            connection,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            item_instance_id=ring,
            character_id=fx.holder,
            expected_last_event_id=token,
        )

    out = race(
        fx.engine,
        lambda c: attune(c, rings[2], tokens[0]),
        lambda c: attune(c, rings[3], tokens[1]),
        ADVISORY,
    )
    assert isinstance(out.get("error"), AttunementNotAllowedError), out
    assert (
        fx.count(
            "SELECT count(*) FROM campaign.item_attunements "
            "WHERE character_id = :c AND broken_world_time_id IS NULL",
            c=fx.holder,
        )
        == 3
    )


def _token_in(connection, fx: Fixture, item: uuid.UUID) -> uuid.UUID | None:  # type: ignore[no-untyped-def]
    return connection.execute(  # type: ignore[no-any-return]
        text(
            "SELECT last_event_id FROM campaign.item_state "
            "WHERE item_instance_id = :i AND timeline_id = :t"
        ),
        {"i": item, "t": fx.timeline_id},
    ).scalar()
