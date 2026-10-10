"""Real-PostgreSQL races for the quest runtime (checkpoint 15.2E-2b).

Quest and objective changes of one (timeline, quest, party) scope serialize on a per-scope
advisory lock, and the quest definition is held `FOR SHARE` while state is written, so a
structural edit cannot interleave with the first progress. Nothing is mocked; committed
fixtures are purged after.
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
from dnd_ai.commands.quest_children import add_objective_dependency
from dnd_ai.commands.quest_definitions import add_quest_objective, add_quest_stage, create_quest
from dnd_ai.commands.quest_runtime import change_quest_status, set_objective_status
from dnd_ai.commands.world_time import create_calendar, create_world_time
from dnd_ai.domain.authoring import QuestHasProgressError, StaleWriteError
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

SCOPE_LOCK = "query LIKE '%pg_advisory_xact_lock%'"
ENTITY_LOCK = "query LIKE '%FOR UPDATE OF e%' OR query LIKE '%FOR SHARE OF e%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    quest_id: uuid.UUID
    quest_version: int
    objectives: list[uuid.UUID]

    def change(self, connection, action: str, expected: str | None):  # type: ignore[no-untyped-def]
        return change_quest_status(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            quest_id=self.quest_id,
            action=action,
            expected_status=expected,
        )

    def objective(self, connection, index: int, status: str, expected: str | None):  # type: ignore[no-untyped-def]
        return set_objective_status(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            quest_objective_id=self.objectives[index],
            new_status=status,
            expected_status=expected,
        )

    def scalar(self, sql: str, **params: object):  # type: ignore[no-untyped-def]
        with self.engine.connect() as connection:
            return connection.execute(text(sql), params).scalar()


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Runtime Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Runtime Race World")
        campaign_id = make_authored_campaign(setup, world, name="Runtime Race Campaign")
        quest = create_quest(
            setup, campaign_id=campaign_id, actor_user_id=owner, name="Race", summary=None
        )
        version = quest.row_version
        stage = add_quest_stage(
            setup,
            campaign_id=campaign_id,
            quest_id=quest.entity_id,
            actor_user_id=owner,
            expected_row_version=version,
            name="Stage",
            description=None,
            stage_type="sequential",
        )
        version = stage.row_version
        objectives = []
        for name in ("A", "B"):
            result = add_quest_objective(
                setup,
                campaign_id=campaign_id,
                quest_id=quest.entity_id,
                quest_stage_id=stage.record_id,
                actor_user_id=owner,
                expected_row_version=version,
                name=name,
                description=None,
                objective_type="other",
                requirement_level="required",
                completion_mode="automatic",
                visibility_policy="visible",
                quantity_required=None,
                target_entity_id=None,
            )
            version = result.row_version
            objectives.append(result.record_id)
        # Publish after the last edit; the structure is final from here.
        published = version
        for step in (submit_entity_for_review, approve_entity, publish_entity_as_canon):
            published = step(
                setup,
                campaign_id=campaign_id,
                entity_id=quest.entity_id,
                actor_user_id=owner,
                expected_row_version=published,
            ).row_version
        calendar = create_calendar(
            setup,
            world_id=world.world_id,
            actor_user_id=owner,
            name="Runtime Calendar",
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
        quest.entity_id,  # type: ignore[arg-type]
        published,
        objectives,  # type: ignore[arg-type]
    )
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM campaign.objective_state WHERE quest_objective_id = ANY(:o)"),
            {"o": objectives},
        )
        cleanup.execute(
            text("DELETE FROM campaign.quest_state WHERE quest_id = :q"), {"q": quest.entity_id}
        )
    _purge_user_worlds(postgres_engine, owner)


def _activate(fx: Fixture) -> None:
    with fx.engine.begin() as connection:
        fx.change(connection, "activate", None)


def test_complete_and_fail_from_the_same_status_one_wins_one_is_stale(fx: Fixture) -> None:
    _activate(fx)
    out = race(
        fx.engine,
        lambda c: fx.change(c, "complete", "active"),
        lambda c: fx.change(c, "fail", "active"),
        SCOPE_LOCK,
    )
    assert isinstance(out.get("error"), StaleWriteError), out
    status = fx.scalar(
        "SELECT st.code FROM campaign.quest_state qs JOIN campaign.quest_statuses st "
        "ON st.quest_status_id = qs.quest_status_id WHERE qs.quest_id = :q",
        q=fx.quest_id,
    )
    assert status == "completed"
    events = fx.scalar(
        "SELECT count(*) FROM narrative.event_effects WHERE target_entity_id = :q", q=fx.quest_id
    )
    assert events == 2  # the activation and the completion; the loser wrote nothing


def test_two_first_activations_make_one_state_row(fx: Fixture) -> None:
    out = race(
        fx.engine,
        lambda c: fx.change(c, "activate", None),
        lambda c: fx.change(c, "activate", None),
        SCOPE_LOCK,
    )
    assert isinstance(out.get("error"), StaleWriteError), out
    assert (
        fx.scalar("SELECT count(*) FROM campaign.quest_state WHERE quest_id = :q", q=fx.quest_id)
        == 1
    )


def test_suspending_wins_over_a_waiting_objective_change(fx: Fixture) -> None:
    _activate(fx)
    from dnd_ai.domain.quest_runtime import QuestNotActiveError

    out = race(
        fx.engine,
        lambda c: fx.change(c, "suspend", "active"),
        lambda c: fx.objective(c, 0, "completed", None),
        SCOPE_LOCK,
    )
    assert isinstance(out.get("error"), QuestNotActiveError), out
    assert (
        fx.scalar(
            "SELECT count(*) FROM campaign.objective_state WHERE quest_objective_id = :o",
            o=fx.objectives[0],
        )
        == 0
    )


def test_a_structural_edit_that_loses_to_the_first_activation_is_refused(fx: Fixture) -> None:
    out = race(
        fx.engine,
        lambda c: fx.change(c, "activate", None),
        lambda c: add_objective_dependency(
            c,
            campaign_id=fx.campaign_id,
            quest_id=fx.quest_id,
            actor_user_id=fx.owner,
            expected_row_version=fx.quest_version,
            objective_id=fx.objectives[1],
            depends_on_objective_id=fx.objectives[0],
            dependency_type="prerequisite",
        ),
        ENTITY_LOCK,
    )
    assert isinstance(out.get("error"), QuestHasProgressError), out
    assert (
        fx.scalar(
            "SELECT count(*) FROM narrative.objective_dependencies WHERE objective_id = ANY(:o)",
            o=fx.objectives,
        )
        == 0
    )
