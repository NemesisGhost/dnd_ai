"""Quest dependencies, participants, outcomes, and rewards (Phase 15 checkpoint 15.2E-2a).

These extend the quest aggregate of `dnd_ai.commands.quest_definitions` (decision D-29):
every command takes the quest's `expected_row_version`, locks the quest `FOR UPDATE`, and
bumps the root version. They write **definition** rows only.

- Objective dependencies are structural: adding or removing one is refused once the quest has
  recorded progress (`quest_has_progress`), exactly like reordering stages. Both objectives must
  belong to the quest and differ; a prerequisite may not close a loop (prerequisite edges
  must stay acyclic).
- Participants (people and organizations) and outcomes with their rewards are free: no recorded
  state refers to them, so they stay editable after progress. A knowledge reward must be a
  usable knowledge item of the world (locked `FOR SHARE`).
- Item rewards are free-text descriptions for now (no item-definition reference exists).

Lock order: authority scope, then entities by ascending id (the quest `FOR UPDATE`; a participant
or knowledge reward `FOR SHARE`).
"""

import uuid

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.domain.authoring import AuthoringValidationError, QuestHasProgressError
from dnd_ai.domain.content_authoring import diff_fields, initial_fields
from dnd_ai.domain.quest_authoring import (
    MAX_DEPENDENCIES,
    MAX_OUTCOMES,
    MAX_PARTICIPANTS,
    MAX_REWARDS_PER_OUTCOME,
    ORDERING_DEPENDENCY_TYPE,
    PARTICIPANT_TYPE_CODES,
    ObjectiveDependencyCycleError,
    ObjectiveDependencyExistsError,
    ObjectiveDependencyInvalidError,
    QuestOutcomeCodeExistsError,
    QuestParticipantExistsError,
    QuestParticipantInvalidError,
    RewardKnowledgeInvalidError,
    normalize_dependency_type,
    normalize_outcome_fields,
    normalize_participant_role,
    normalize_reward_fields,
)

from ._content import ContentWriteResult, EntityNotFoundError, usable_reference
from .quest_definitions import (
    _bump,
    _child_result,
    _lock_quest,
    _noop,
    _text_id,
    quest_has_progress,
)

_UNIQUE_VIOLATION = "23505"


def _objective_in_quest(
    connection: Connection, quest_id: uuid.UUID, objective_id: uuid.UUID
) -> bool:
    return (
        connection.execute(
            text("""
                SELECT 1 FROM narrative.quest_objectives qo
                JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
                WHERE qo.quest_objective_id = :o AND qs.quest_id = :q
            """),
            {"o": objective_id, "q": quest_id},
        ).scalar()
        is not None
    )


def _would_loop(
    connection: Connection, quest_id: uuid.UUID, objective_id: uuid.UUID, depends_on: uuid.UUID
) -> bool:
    """Adding `objective_id` requires `depends_on`: a loop if `depends_on` already (transitively)
    requires `objective_id` through prerequisite edges of this quest."""
    rows = connection.execute(
        text("""
            SELECT od.objective_id, od.depends_on_objective_id
            FROM narrative.objective_dependencies od
            JOIN narrative.quest_objectives qo ON qo.quest_objective_id = od.objective_id
            JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
            WHERE qs.quest_id = :q AND od.dependency_type = :t
        """),
        {"q": quest_id, "t": ORDERING_DEPENDENCY_TYPE},
    ).all()
    requires: dict[uuid.UUID, list[uuid.UUID]] = {}
    for row in rows:
        requires.setdefault(row.objective_id, []).append(row.depends_on_objective_id)
    seen: set[uuid.UUID] = set()
    stack = [depends_on]
    while stack:
        current = stack.pop()
        if current == objective_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(requires.get(current, []))
    return False


def add_objective_dependency(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    objective_id: uuid.UUID,
    depends_on_objective_id: uuid.UUID,
    dependency_type: str | None,
) -> ContentWriteResult:
    kind = normalize_dependency_type(dependency_type)
    scope, quest, _ = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    if quest_has_progress(connection, quest_id):
        raise QuestHasProgressError(f"quest {quest_id} has progress")
    if (
        objective_id == depends_on_objective_id
        or not _objective_in_quest(connection, quest_id, objective_id)
        or not _objective_in_quest(connection, quest_id, depends_on_objective_id)
    ):
        raise ObjectiveDependencyInvalidError("objectives are not valid for this quest")
    count = connection.execute(
        text("""
            SELECT count(*) FROM narrative.objective_dependencies od
            JOIN narrative.quest_objectives qo ON qo.quest_objective_id = od.objective_id
            JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
            WHERE qs.quest_id = :q
        """),
        {"q": quest_id},
    ).scalar()
    if (count or 0) >= MAX_DEPENDENCIES:
        raise AuthoringValidationError(f"a quest holds at most {MAX_DEPENDENCIES} dependencies")
    if kind == ORDERING_DEPENDENCY_TYPE and _would_loop(
        connection, quest_id, objective_id, depends_on_objective_id
    ):
        raise ObjectiveDependencyCycleError("prerequisite loop")
    try:
        dependency_id = connection.execute(
            text("""
                INSERT INTO narrative.objective_dependencies
                    (objective_id, depends_on_objective_id, dependency_type)
                VALUES (:o, :d, :t) RETURNING objective_dependency_id
            """),
            {"o": objective_id, "d": depends_on_objective_id, "t": kind},
        ).scalar()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == _UNIQUE_VIOLATION:
            raise ObjectiveDependencyExistsError("duplicate dependency") from exc
        raise
    assert isinstance(dependency_id, uuid.UUID)
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="objective_dependencies",
        record_id=dependency_id,
        action="created",
        fields=initial_fields(
            {
                "objective_id": str(objective_id),
                "depends_on_objective_id": str(depends_on_objective_id),
                "dependency_type": kind,
            }
        ),
    )


def remove_objective_dependency(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    objective_dependency_id: uuid.UUID,
) -> ContentWriteResult:
    scope, quest, _ = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    if quest_has_progress(connection, quest_id):
        raise QuestHasProgressError(f"quest {quest_id} has progress")
    row = connection.execute(
        text("""
            DELETE FROM narrative.objective_dependencies od
            USING narrative.quest_objectives qo, narrative.quest_stages qs
            WHERE od.objective_dependency_id = :d AND qo.quest_objective_id = od.objective_id
              AND qs.quest_stage_id = qo.quest_stage_id AND qs.quest_id = :q
            RETURNING od.objective_id, od.depends_on_objective_id, od.dependency_type
        """),
        {"d": objective_dependency_id, "q": quest_id},
    ).one_or_none()
    if row is None:
        raise EntityNotFoundError(
            f"dependency {objective_dependency_id} is not in quest {quest_id}"
        )
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="objective_dependencies",
        record_id=objective_dependency_id,
        action="deleted",
        fields=initial_fields(
            {
                "objective_id": str(row.objective_id),
                "depends_on_objective_id": str(row.depends_on_objective_id),
                "dependency_type": str(row.dependency_type),
            }
        ),
    )


def add_quest_participant(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    participant_entity_id: uuid.UUID,
    participant_role: str | None,
) -> ContentWriteResult:
    role = normalize_participant_role(participant_role)
    scope, quest, locked = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        target_ids=(participant_entity_id,),
    )
    usable_reference(
        locked,
        participant_entity_id,
        type_codes=PARTICIPANT_TYPE_CODES,
        error=QuestParticipantInvalidError,
    )
    count = connection.execute(
        text("SELECT count(*) FROM narrative.quest_participants WHERE quest_id = :q"),
        {"q": quest_id},
    ).scalar()
    if (count or 0) >= MAX_PARTICIPANTS:
        raise AuthoringValidationError(f"a quest holds at most {MAX_PARTICIPANTS} participants")
    try:
        participant_id = connection.execute(
            text("""
                INSERT INTO narrative.quest_participants (quest_id, participant_entity_id, participant_role)
                VALUES (:q, :e, :r) RETURNING quest_participant_id
            """),
            {"q": quest_id, "e": participant_entity_id, "r": role},
        ).scalar()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == _UNIQUE_VIOLATION:
            raise QuestParticipantExistsError("duplicate participant") from exc
        raise
    assert isinstance(participant_id, uuid.UUID)
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="quest_participants",
        record_id=participant_id,
        action="created",
        fields=initial_fields(
            {"target_entity_id": _text_id(participant_entity_id), "participant_role": role}
        ),
    )


def remove_quest_participant(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    quest_participant_id: uuid.UUID,
) -> ContentWriteResult:
    scope, quest, _ = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    row = connection.execute(
        text(
            "DELETE FROM narrative.quest_participants WHERE quest_participant_id = :p "
            "AND quest_id = :q RETURNING participant_entity_id, participant_role"
        ),
        {"p": quest_participant_id, "q": quest_id},
    ).one_or_none()
    if row is None:
        raise EntityNotFoundError(f"participant {quest_participant_id} is not in quest {quest_id}")
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="quest_participants",
        record_id=quest_participant_id,
        action="deleted",
        fields=initial_fields(
            {
                "target_entity_id": str(row.participant_entity_id),
                "participant_role": str(row.participant_role),
            }
        ),
    )


def _outcome_in_quest(connection: Connection, quest_id: uuid.UUID, outcome_id: uuid.UUID) -> bool:
    return (
        connection.execute(
            text(
                "SELECT 1 FROM narrative.quest_outcomes "
                "WHERE quest_outcome_id = :o AND quest_id = :q"
            ),
            {"o": outcome_id, "q": quest_id},
        ).scalar()
        is not None
    )


def add_quest_outcome(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    code: str | None,
    name: str | None,
    description: str | None,
    outcome_category: str | None,
) -> ContentWriteResult:
    fields = normalize_outcome_fields(
        code=code, name=name, description=description, outcome_category=outcome_category
    )
    scope, quest, _ = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    count = connection.execute(
        text("SELECT count(*) FROM narrative.quest_outcomes WHERE quest_id = :q"), {"q": quest_id}
    ).scalar()
    if (count or 0) >= MAX_OUTCOMES:
        raise AuthoringValidationError(f"a quest holds at most {MAX_OUTCOMES} outcomes")
    try:
        outcome_id = connection.execute(
            text("""
                INSERT INTO narrative.quest_outcomes
                    (quest_id, code, name, description, outcome_category)
                VALUES (:q, :code, :name, :description, :category) RETURNING quest_outcome_id
            """),
            {
                "q": quest_id,
                "code": fields.code,
                "name": fields.name,
                "description": fields.description,
                "category": fields.outcome_category,
            },
        ).scalar()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == _UNIQUE_VIOLATION:
            raise QuestOutcomeCodeExistsError("duplicate outcome code") from exc
        raise
    assert isinstance(outcome_id, uuid.UUID)
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="quest_outcomes",
        record_id=outcome_id,
        action="created",
        fields=initial_fields(
            {
                "code": fields.code,
                "name": fields.name,
                "description": fields.description,
                "outcome_category": fields.outcome_category,
            }
        ),
    )


def update_quest_outcome(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    quest_outcome_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    name: str | None,
    description: str | None,
    outcome_category: str | None,
) -> ContentWriteResult:
    scope, quest, _ = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    current = connection.execute(
        text(
            "SELECT code, name, description, outcome_category FROM narrative.quest_outcomes "
            "WHERE quest_outcome_id = :o AND quest_id = :q"
        ),
        {"o": quest_outcome_id, "q": quest_id},
    ).one_or_none()
    if current is None:
        raise EntityNotFoundError(f"outcome {quest_outcome_id} is not in quest {quest_id}")
    # The code names the outcome for state and events; it never changes.
    fields = normalize_outcome_fields(
        code=str(current.code),
        name=name,
        description=description,
        outcome_category=outcome_category,
    )
    changed = diff_fields(
        {
            "name": current.name,
            "description": current.description,
            "outcome_category": current.outcome_category,
        },
        {
            "name": fields.name,
            "description": fields.description,
            "outcome_category": fields.outcome_category,
        },
    )
    if not changed:
        return _noop(quest, scope)
    connection.execute(
        text(
            "UPDATE narrative.quest_outcomes SET name = :n, description = :d, "
            "outcome_category = :c WHERE quest_outcome_id = :o"
        ),
        {
            "n": fields.name,
            "d": fields.description,
            "c": fields.outcome_category,
            "o": quest_outcome_id,
        },
    )
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="quest_outcomes",
        record_id=quest_outcome_id,
        action="updated",
        fields=dict(changed),
    )


def remove_quest_outcome(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    quest_outcome_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
) -> ContentWriteResult:
    scope, quest, _ = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    row = connection.execute(
        text(
            "SELECT code, (SELECT count(*) FROM narrative.quest_rewards WHERE quest_outcome_id = :o) "
            "AS rewards FROM narrative.quest_outcomes WHERE quest_outcome_id = :o AND quest_id = :q"
        ),
        {"o": quest_outcome_id, "q": quest_id},
    ).one_or_none()
    if row is None:
        raise EntityNotFoundError(f"outcome {quest_outcome_id} is not in quest {quest_id}")
    connection.execute(
        text("DELETE FROM narrative.quest_outcomes WHERE quest_outcome_id = :o"),
        {"o": quest_outcome_id},
    )
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="quest_outcomes",
        record_id=quest_outcome_id,
        action="deleted",
        fields=initial_fields({"code": str(row.code), "rewards_removed": int(row.rewards)}),
    )


def add_quest_reward(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    quest_outcome_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    reward_type: str | None,
    description: str | None,
    reward_knowledge_item_id: uuid.UUID | None,
) -> ContentWriteResult:
    fields = normalize_reward_fields(reward_type=reward_type, description=description)
    if (fields.reward_type == "knowledge") != (reward_knowledge_item_id is not None):
        raise RewardKnowledgeInvalidError("a knowledge reward names a knowledge item, others none")
    scope, quest, locked = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        target_ids=(reward_knowledge_item_id,),
    )
    if not _outcome_in_quest(connection, quest_id, quest_outcome_id):
        raise EntityNotFoundError(f"outcome {quest_outcome_id} is not in quest {quest_id}")
    usable_reference(
        locked,
        reward_knowledge_item_id,
        type_codes=frozenset({"knowledge_item"}),
        error=RewardKnowledgeInvalidError,
    )
    count = connection.execute(
        text("SELECT count(*) FROM narrative.quest_rewards WHERE quest_outcome_id = :o"),
        {"o": quest_outcome_id},
    ).scalar()
    if (count or 0) >= MAX_REWARDS_PER_OUTCOME:
        raise AuthoringValidationError(
            f"an outcome holds at most {MAX_REWARDS_PER_OUTCOME} rewards"
        )
    reward_id = connection.execute(
        text("""
            INSERT INTO narrative.quest_rewards
                (quest_outcome_id, reward_type, description, reward_knowledge_item_id)
            VALUES (:o, :t, :d, :k) RETURNING quest_reward_id
        """),
        {
            "o": quest_outcome_id,
            "t": fields.reward_type,
            "d": fields.description,
            "k": reward_knowledge_item_id,
        },
    ).scalar()
    assert isinstance(reward_id, uuid.UUID)
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="quest_rewards",
        record_id=reward_id,
        action="created",
        fields=initial_fields(
            {
                "quest_outcome_id": str(quest_outcome_id),
                "reward_type": fields.reward_type,
                "description": fields.description,
                "subject_entity_id": _text_id(reward_knowledge_item_id),
            }
        ),
    )


def remove_quest_reward(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    quest_reward_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
) -> ContentWriteResult:
    scope, quest, _ = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    row = connection.execute(
        text("""
            DELETE FROM narrative.quest_rewards r USING narrative.quest_outcomes o
            WHERE r.quest_reward_id = :r AND o.quest_outcome_id = r.quest_outcome_id
              AND o.quest_id = :q RETURNING r.quest_outcome_id, r.reward_type
        """),
        {"r": quest_reward_id, "q": quest_id},
    ).one_or_none()
    if row is None:
        raise EntityNotFoundError(f"reward {quest_reward_id} is not in quest {quest_id}")
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="quest_rewards",
        record_id=quest_reward_id,
        action="deleted",
        fields=initial_fields(
            {"quest_outcome_id": str(row.quest_outcome_id), "reward_type": str(row.reward_type)}
        ),
    )
