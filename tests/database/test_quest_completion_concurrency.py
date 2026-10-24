"""Real-PostgreSQL races for quest completion authoring (checkpoint 15.2E-2a).

Every quest command locks the quest entity `FOR UPDATE` and compares the expected version, so
two editors serialize: two prerequisite edges that would close a loop together cannot both
land, and a second edit from the same version is stale. Nothing is mocked; committed fixtures
are purged after.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.quest_children import add_objective_dependency, add_quest_outcome
from dnd_ai.commands.quest_definitions import add_quest_objective, add_quest_stage, create_quest
from dnd_ai.domain.authoring import StaleWriteError
from dnd_ai.domain.quest_authoring import ObjectiveDependencyCycleError
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

ENTITY_LOCK = "query LIKE '%FOR UPDATE OF e%' OR query LIKE '%FOR SHARE OF e%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    quest_id: uuid.UUID
    objectives: list[uuid.UUID]

    def version(self) -> int:
        with self.engine.connect() as connection:
            value = connection.execute(
                text("SELECT row_version FROM core.entities WHERE entity_id = :q"),
                {"q": self.quest_id},
            ).scalar()
        assert isinstance(value, int)
        return value

    def depend(self, connection, objective: int, on: int, version: int):  # type: ignore[no-untyped-def]
        return add_objective_dependency(
            connection,
            campaign_id=self.campaign_id,
            quest_id=self.quest_id,
            actor_user_id=self.owner,
            expected_row_version=version,
            objective_id=self.objectives[objective],
            depends_on_objective_id=self.objectives[on],
            dependency_type="prerequisite",
        )

    def outcome(self, connection, code: str, version: int):  # type: ignore[no-untyped-def]
        return add_quest_outcome(
            connection,
            campaign_id=self.campaign_id,
            quest_id=self.quest_id,
            actor_user_id=self.owner,
            expected_row_version=version,
            code=code,
            name=code,
            description=None,
            outcome_category="neutral",
        )

    def edges(self) -> int:
        with self.engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT count(*) FROM narrative.objective_dependencies WHERE objective_id = ANY(:o)"
                ),
                {"o": self.objectives},
            ).scalar()
        assert isinstance(value, int)
        return value


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Quest Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Quest Race World")
        campaign_id = make_authored_campaign(setup, world, name="Quest Race Campaign")
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
    yield Fixture(postgres_engine, owner, campaign_id, quest.entity_id, objectives)  # type: ignore[arg-type]
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM narrative.objective_dependencies WHERE objective_id = ANY(:o)"),
            {"o": objectives},
        )
        cleanup.execute(
            text("DELETE FROM narrative.quest_outcomes WHERE quest_id = :q"),
            {"q": quest.entity_id},
        )
    _purge_user_worlds(postgres_engine, owner)


def test_two_opposite_prerequisites_cannot_both_land(fx: Fixture) -> None:
    version = fx.version()
    # The second edit used the version the first one produced, so only the cycle can stop it.
    out = race(
        fx.engine,
        lambda c: fx.depend(c, 0, 1, version),
        lambda c: fx.depend(c, 1, 0, version + 1),
        ENTITY_LOCK,
    )
    assert isinstance(out.get("error"), ObjectiveDependencyCycleError), out
    assert fx.edges() == 1


def test_two_edits_from_one_version_one_wins_one_is_stale(fx: Fixture) -> None:
    version = fx.version()
    out = race(
        fx.engine,
        lambda c: fx.outcome(c, "winner", version),
        lambda c: fx.outcome(c, "loser", version),
        ENTITY_LOCK,
    )
    assert isinstance(out.get("error"), StaleWriteError), out
    with fx.engine.connect() as connection:
        codes = (
            connection.execute(
                text("SELECT code FROM narrative.quest_outcomes WHERE quest_id = :q"),
                {"q": fx.quest_id},
            )
            .scalars()
            .all()
        )
    assert codes == ["winner"]
