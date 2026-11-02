"""Real-PostgreSQL races for the knowledge runtime (checkpoint 15.2E-3).

A first write of one (timeline, claim, knower) is serialized by an advisory lock, the claim is
held `FOR SHARE` so a statement edit cannot interleave with the first learning, and a belief
change and a correction both lock the belief row, so the later one sees what the earlier wrote.
Nothing is mocked; committed fixtures are purged after.
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
from dnd_ai.commands.event_corrections import void_event
from dnd_ai.commands.knowledge_definitions import create_knowledge_item, update_knowledge_item
from dnd_ai.commands.knowledge_runtime import change_belief, record_character_knowledge
from dnd_ai.commands.player_characters import create_player_character
from dnd_ai.commands.world_time import create_calendar, create_world_time
from dnd_ai.domain.authoring import KnowledgeAlreadyKnownError, StaleWriteError
from dnd_ai.domain.event_corrections import CorrectionNotReversibleError
from dnd_ai.domain.knowledge_runtime import KnowerAlreadyKnowsError
from dnd_ai.queries.npc_authoring import list_species_options
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

SCOPE_LOCK = "query LIKE '%pg_advisory_xact_lock%'"
ENTITY_LOCK = "query LIKE '%FOR UPDATE OF e%' OR query LIKE '%FOR SHARE OF e%'"
BELIEF_ROW = "query LIKE '%knowledge.entity_knowledge%FOR UPDATE%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    claim_id: uuid.UUID
    claim_version: int
    knower_id: uuid.UUID

    def learn(self, connection):  # type: ignore[no-untyped-def]
        return record_character_knowledge(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            knowledge_item_id=self.claim_id,
            knower_entity_id=self.knower_id,
        )

    def belief_id(self) -> uuid.UUID:
        with self.engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT entity_knowledge_id FROM knowledge.entity_knowledge WHERE knowledge_item_id = :k"
                ),
                {"k": self.claim_id},
            ).scalar()
        assert isinstance(value, uuid.UUID)
        return value

    def change(self, connection, token, **changes):  # type: ignore[no-untyped-def]
        return change_belief(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            entity_knowledge_id=self.belief_id(),
            expected_last_event_id=token,
            changes=changes,
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
        owner = make_user(setup, "Knowledge Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Knowledge Race World")
        campaign_id = make_authored_campaign(setup, world, name="Knowledge Race Campaign")
        species = list_species_options(setup, world_id=world.world_id)[0].species_id
        knower = create_player_character(
            setup,
            campaign_id=campaign_id,
            actor_user_id=owner,
            name="Racer",
            summary=None,
            species_id=species,
            size_category="medium",
        )
        _publish(setup, campaign_id, owner, knower.entity_id, knower.row_version)
        claim = create_knowledge_item(
            setup,
            campaign_id=campaign_id,
            actor_user_id=owner,
            statement="The race is fixed.",
            knowledge_type="secret",
            truth_status="true",
            sensitivity="secret",
        )
        claim_version = _publish(setup, campaign_id, owner, claim.entity_id, claim.row_version)
        calendar = create_calendar(
            setup,
            world_id=world.world_id,
            actor_user_id=owner,
            name="Knowledge Calendar",
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
    yield Fixture(
        postgres_engine,
        owner,
        campaign_id,
        claim.entity_id,  # type: ignore[arg-type]
        claim_version,
        knower.entity_id,  # type: ignore[arg-type]
    )
    _purge_user_worlds(postgres_engine, owner)


def test_two_first_learnings_make_one_belief(fx: Fixture) -> None:
    out = race(fx.engine, fx.learn, fx.learn, SCOPE_LOCK)
    assert isinstance(out.get("error"), KnowerAlreadyKnowsError), out
    assert (
        fx.scalar(
            "SELECT count(*) FROM knowledge.entity_knowledge WHERE knowledge_item_id = :k",
            k=fx.claim_id,
        )
        == 1
    )


def test_two_belief_changes_from_one_token_one_wins_one_is_stale(fx: Fixture) -> None:
    with fx.engine.begin() as connection:
        token = fx.learn(connection).event_id
    out = race(
        fx.engine,
        lambda c: fx.change(c, token, awareness_level="rumored"),
        lambda c: fx.change(c, token, awareness_level="suspected"),
        SCOPE_LOCK,
    )
    assert isinstance(out.get("error"), StaleWriteError), out
    assert (
        fx.scalar(
            "SELECT awareness_level FROM knowledge.entity_knowledge WHERE knowledge_item_id = :k",
            k=fx.claim_id,
        )
        == "rumored"
    )


def test_a_statement_edit_that_loses_to_the_first_learning_is_refused(fx: Fixture) -> None:
    out = race(
        fx.engine,
        fx.learn,
        lambda c: update_knowledge_item(
            c,
            campaign_id=fx.campaign_id,
            knowledge_item_id=fx.claim_id,
            actor_user_id=fx.owner,
            expected_row_version=fx.claim_version,
            statement="Rewritten while someone learned it.",
            knowledge_type="secret",
            truth_status="true",
            sensitivity="secret",
        ),
        ENTITY_LOCK,
    )
    assert isinstance(out.get("error"), KnowledgeAlreadyKnownError), out
    statement = fx.scalar(
        "SELECT canonical_statement FROM knowledge.knowledge_items WHERE knowledge_item_id = :k",
        k=fx.claim_id,
    )
    assert statement == "The race is fixed."


def test_a_correction_that_loses_to_a_belief_change_refuses(fx: Fixture) -> None:
    with fx.engine.begin() as connection:
        learned = fx.learn(connection).event_id
    out = race(
        fx.engine,
        lambda c: fx.change(c, learned, confidence=5),
        lambda c: void_event(
            c,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            event_id=learned,
            reason="Race",
        ),
        BELIEF_ROW,
    )
    assert isinstance(out.get("error"), CorrectionNotReversibleError), out
    assert (
        fx.scalar(
            "SELECT confidence FROM knowledge.entity_knowledge WHERE knowledge_item_id = :k",
            k=fx.claim_id,
        )
        == 5
    )
