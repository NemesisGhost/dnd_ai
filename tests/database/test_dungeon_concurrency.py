"""Real-PostgreSQL races for dungeon authoring and state (checkpoint 15.3A-1, D-31).

Every structural change locks the dungeon `FOR UPDATE` and compares its version, so two editors
serialize; adding an area takes the dungeon `FOR SHARE`, so an archive that wins makes the add
fail; a first state write of one target is serialized by an advisory lock. Nothing is mocked;
committed fixtures are purged after.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.campaign_clock import advance_campaign_clock
from dnd_ai.commands.dungeon_state import set_dungeon_state
from dnd_ai.commands.dungeons import add_area_child, create_dungeon, create_dungeon_area
from dnd_ai.commands.entity_lifecycle import (
    approve_entity,
    archive_entity,
    publish_entity_as_canon,
    submit_entity_for_review,
)
from dnd_ai.commands.world_time import create_calendar, create_world_time
from dnd_ai.domain.authoring import ParentLocationInvalidError, StaleWriteError
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

ENTITY_LOCK = "query LIKE '%FOR UPDATE OF e%' OR query LIKE '%FOR SHARE OF e%'"
SCOPE_LOCK = "query LIKE '%pg_advisory_xact_lock%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    dungeon_id: uuid.UUID
    dungeon_version: int
    area_id: uuid.UUID
    published: bool = False

    def feature(self, connection, version: int, kind: str = "feature"):  # type: ignore[no-untyped-def]
        return add_area_child(
            connection,
            campaign_id=self.campaign_id,
            dungeon_id=self.dungeon_id,
            actor_user_id=self.owner,
            expected_row_version=version,
            dungeon_area_id=self.area_id,
            kind=kind,
            child_type="thing",
            description=None,
        )

    def state(self, connection, status: str):  # type: ignore[no-untyped-def]
        return set_dungeon_state(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            dungeon_area_id=self.area_id,
            kind="area",
            target_id=self.area_id,
            changes={"alarm_level": 1 if status == "a" else 2},
            expected_last_event_id=None,
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
        owner = make_user(setup, "Dungeon Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Dungeon Race World")
        campaign_id = make_authored_campaign(setup, world, name="Dungeon Race Campaign")
        dungeon = create_dungeon(
            setup, campaign_id=campaign_id, actor_user_id=owner, name="Race Vault", summary=None
        )
        area = create_dungeon_area(
            setup,
            campaign_id=campaign_id,
            actor_user_id=owner,
            dungeon_id=dungeon.entity_id,
            name="Race Hall",
            summary=None,
        )
        calendar = create_calendar(
            setup,
            world_id=world.world_id,
            actor_user_id=owner,
            name="Dungeon Calendar",
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
        dungeon_version = dungeon.row_version
    yield Fixture(
        postgres_engine,
        owner,
        campaign_id,
        dungeon.entity_id,  # type: ignore[arg-type]
        dungeon_version,
        area.entity_id,  # type: ignore[arg-type]
    )
    _purge_user_worlds(postgres_engine, owner)


def test_two_structural_edits_from_one_version_one_wins_one_is_stale(fx: Fixture) -> None:
    out = race(
        fx.engine,
        lambda c: fx.feature(c, fx.dungeon_version),
        lambda c: fx.feature(c, fx.dungeon_version, "hazard"),
        ENTITY_LOCK,
    )
    assert isinstance(out.get("error"), StaleWriteError), out
    total = fx.scalar(
        "SELECT (SELECT count(*) FROM world.area_features WHERE dungeon_area_id = :a) "
        "+ (SELECT count(*) FROM world.area_hazards WHERE dungeon_area_id = :a)",
        a=fx.area_id,
    )
    assert total == 1


def test_an_archive_that_wins_makes_adding_an_area_fail(fx: Fixture) -> None:
    # The dungeon has no active area yet once the area is archived; archive both in order.
    with fx.engine.begin() as connection:
        area_version = connection.execute(
            text("SELECT row_version FROM core.entities WHERE entity_id = :a"), {"a": fx.area_id}
        ).scalar()
        archive_entity(
            connection,
            campaign_id=fx.campaign_id,
            entity_id=fx.area_id,
            actor_user_id=fx.owner,
            expected_row_version=area_version,
        )
    out = race(
        fx.engine,
        lambda c: archive_entity(
            c,
            campaign_id=fx.campaign_id,
            entity_id=fx.dungeon_id,
            actor_user_id=fx.owner,
            expected_row_version=fx.dungeon_version,
        ),
        lambda c: create_dungeon_area(
            c,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            dungeon_id=fx.dungeon_id,
            name="Too late",
            summary=None,
        ),
        ENTITY_LOCK,
    )
    assert isinstance(out.get("error"), ParentLocationInvalidError), out
    assert (
        fx.scalar(
            "SELECT count(*) FROM world.locations WHERE parent_location_id = :d", d=fx.dungeon_id
        )
        == 1
    )


def test_two_first_state_writes_of_one_target_one_wins_one_is_stale(fx: Fixture) -> None:
    with fx.engine.begin() as connection:
        version = _publish(connection, fx.campaign_id, fx.owner, fx.dungeon_id, fx.dungeon_version)
        area_version = connection.execute(
            text("SELECT row_version FROM core.entities WHERE entity_id = :a"), {"a": fx.area_id}
        ).scalar()
        _publish(connection, fx.campaign_id, fx.owner, fx.area_id, area_version)
    assert version
    out = race(fx.engine, lambda c: fx.state(c, "a"), lambda c: fx.state(c, "b"), SCOPE_LOCK)
    assert isinstance(out.get("error"), StaleWriteError), out
    assert (
        fx.scalar(
            "SELECT alarm_level FROM campaign.location_state WHERE location_id = :a", a=fx.area_id
        )
        == 1
    )
