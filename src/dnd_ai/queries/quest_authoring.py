"""Quest definition authoring read models (Phase 15.1).

For `canon.edit` holders only. The view is the whole aggregate -- stages in order
with their objectives and targets -- never progress, and includes the
server-computed actions: the shared lifecycle evaluation plus `update`, then the
quest child actions, each blocked with `quest_has_progress` once progress exists.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from dnd_ai.commands.quest_definitions import quest_has_progress
from dnd_ai.domain.content_authoring import evaluate_content_actions
from dnd_ai.domain.entity_lifecycle import BlockedAction
from dnd_ai.domain.quest_authoring import (
    COMPLETION_MODES,
    DEPENDENCY_TYPES,
    OBJECTIVE_TARGET_TYPE_CODES,
    OUTCOME_CATEGORIES,
    PARTICIPANT_ROLES,
    REQUIREMENT_LEVELS,
    REWARD_TYPES,
    STAGE_TYPES,
    VISIBILITY_POLICIES,
)
from dnd_ai.queries.content_preconditions import type_specific_blocks
from dnd_ai.queries.organization_authoring import ReferenceSummary, _reference

QUEST_HAS_PROGRESS = "quest_has_progress"

# Child actions available while the quest is editable; the first three are
# structural and are blocked once progress exists.
STRUCTURAL_QUEST_ACTIONS = (
    "reorder_stages",
    "remove_stage",
    "remove_objective",
    "add_dependency",
    "remove_dependency",
)
FREE_QUEST_ACTIONS = (
    "add_stage",
    "update_stage",
    "add_objective",
    "update_objective",
    "add_participant",
    "remove_participant",
    "add_outcome",
    "update_outcome",
    "remove_outcome",
    "add_reward",
    "remove_reward",
)


@dataclass(frozen=True)
class ObjectiveView:
    quest_objective_id: uuid.UUID
    name: str
    description: str | None
    objective_type: str
    objective_type_label: str
    requirement_level: str
    completion_mode: str
    visibility_policy: str
    quantity_required: int | None
    target: ReferenceSummary | None
    target_kind: str | None


@dataclass(frozen=True)
class StageView:
    quest_stage_id: uuid.UUID
    name: str
    description: str | None
    stage_type: str
    sequence_number: int
    objectives: list[ObjectiveView]


@dataclass(frozen=True)
class DependencyView:
    objective_dependency_id: uuid.UUID
    objective_id: uuid.UUID
    depends_on_objective_id: uuid.UUID
    dependency_type: str


@dataclass(frozen=True)
class ParticipantView:
    quest_participant_id: uuid.UUID
    participant: ReferenceSummary | None
    participant_role: str


@dataclass(frozen=True)
class RewardView:
    quest_reward_id: uuid.UUID
    reward_type: str
    description: str
    knowledge: ReferenceSummary | None


@dataclass(frozen=True)
class OutcomeView:
    quest_outcome_id: uuid.UUID
    code: str
    name: str
    description: str | None
    outcome_category: str
    rewards: list[RewardView]


@dataclass(frozen=True)
class QuestAuthoringView:
    quest_id: uuid.UUID
    name: str
    summary: str | None
    stages: list[StageView]
    has_progress: bool
    canon_status: str
    lifecycle_status: str
    row_version: int
    available_actions: list[str]
    blocked_actions: list[BlockedAction]
    field_locks: list[str] = field(default_factory=list)
    # Phase 15.2E-2a. `gm_notes` is GM-only: this authoring view is for editors alone.
    gm_notes: str | None = None
    dependencies: list[DependencyView] = field(default_factory=list)
    participants: list[ParticipantView] = field(default_factory=list)
    outcomes: list[OutcomeView] = field(default_factory=list)


def list_objective_types(connection: Connection) -> list[tuple[str, str]]:
    rows = connection.execute(
        text("SELECT code, display_name FROM narrative.objective_types ORDER BY display_name, code")
    ).all()
    return [(str(r.code), str(r.display_name)) for r in rows]


def get_quest_authoring(
    connection: Connection, *, world_id: uuid.UUID, quest_id: uuid.UUID
) -> QuestAuthoringView | None:
    row = connection.execute(
        text("""
            SELECT e.canonical_name, e.summary, e.row_version, q.gm_notes,
                   cs.code AS canon_status, ls.code AS lifecycle_status
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            JOIN narrative.quests q ON q.quest_id = e.entity_id
            WHERE e.entity_id = :q AND e.world_id = :w AND et.code = 'quest'
        """),
        {"q": quest_id, "w": world_id},
    ).one_or_none()
    if row is None:
        return None

    stage_rows = connection.execute(
        text("""
            SELECT quest_stage_id, name, description, stage_type, sequence_number
            FROM narrative.quest_stages WHERE quest_id = :q
            ORDER BY sequence_number, created_at, quest_stage_id
        """),
        {"q": quest_id},
    ).all()
    objective_rows = connection.execute(
        text("""
            SELECT qo.quest_stage_id, qo.quest_objective_id, qo.name, qo.description,
                   ot.code AS objective_type, ot.display_name AS objective_type_label,
                   qo.requirement_level, qo.completion_mode, qo.visibility_policy,
                   qo.quantity_required, qo.target_entity_id, tet.code AS target_kind
            FROM narrative.quest_objectives qo
            JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
            JOIN narrative.objective_types ot ON ot.objective_type_id = qo.objective_type_id
            LEFT JOIN core.entities te ON te.entity_id = qo.target_entity_id
            LEFT JOIN core.entity_types tet ON tet.entity_type_id = te.entity_type_id
            WHERE qs.quest_id = :q
            ORDER BY qo.created_at, qo.quest_objective_id
        """),
        {"q": quest_id},
    ).all()
    by_stage: dict[uuid.UUID, list[ObjectiveView]] = {}
    for o in objective_rows:
        by_stage.setdefault(o.quest_stage_id, []).append(
            ObjectiveView(
                quest_objective_id=o.quest_objective_id,
                name=str(o.name),
                description=o.description,
                objective_type=str(o.objective_type),
                objective_type_label=str(o.objective_type_label),
                requirement_level=str(o.requirement_level),
                completion_mode=str(o.completion_mode),
                visibility_policy=str(o.visibility_policy),
                quantity_required=o.quantity_required,
                target=_reference(connection, o.target_entity_id),
                target_kind=None if o.target_kind is None else str(o.target_kind),
            )
        )
    stages = [
        StageView(
            quest_stage_id=s.quest_stage_id,
            name=str(s.name),
            description=s.description,
            stage_type=str(s.stage_type),
            sequence_number=int(s.sequence_number),
            objectives=by_stage.get(s.quest_stage_id, []),
        )
        for s in stage_rows
    ]

    dependencies = [
        DependencyView(
            objective_dependency_id=d.objective_dependency_id,
            objective_id=d.objective_id,
            depends_on_objective_id=d.depends_on_objective_id,
            dependency_type=str(d.dependency_type),
        )
        for d in connection.execute(
            text("""
                SELECT od.objective_dependency_id, od.objective_id, od.depends_on_objective_id,
                       od.dependency_type
                FROM narrative.objective_dependencies od
                JOIN narrative.quest_objectives qo ON qo.quest_objective_id = od.objective_id
                JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
                WHERE qs.quest_id = :q ORDER BY od.created_at, od.objective_dependency_id
            """),
            {"q": quest_id},
        )
    ]
    participants = [
        ParticipantView(
            quest_participant_id=p.quest_participant_id,
            participant=_reference(connection, p.participant_entity_id),
            participant_role=str(p.participant_role),
        )
        for p in connection.execute(
            text(
                "SELECT quest_participant_id, participant_entity_id, participant_role "
                "FROM narrative.quest_participants WHERE quest_id = :q "
                "ORDER BY created_at, quest_participant_id"
            ),
            {"q": quest_id},
        )
    ]
    reward_rows = connection.execute(
        text("""
            SELECT r.quest_outcome_id, r.quest_reward_id, r.reward_type, r.description,
                   r.reward_knowledge_item_id
            FROM narrative.quest_rewards r
            JOIN narrative.quest_outcomes o ON o.quest_outcome_id = r.quest_outcome_id
            WHERE o.quest_id = :q ORDER BY r.created_at, r.quest_reward_id
        """),
        {"q": quest_id},
    ).all()
    rewards_by_outcome: dict[uuid.UUID, list[RewardView]] = {}
    for r in reward_rows:
        rewards_by_outcome.setdefault(r.quest_outcome_id, []).append(
            RewardView(
                quest_reward_id=r.quest_reward_id,
                reward_type=str(r.reward_type),
                description=str(r.description),
                knowledge=_reference(connection, r.reward_knowledge_item_id),
            )
        )
    outcomes = [
        OutcomeView(
            quest_outcome_id=o.quest_outcome_id,
            code=str(o.code),
            name=str(o.name),
            description=o.description,
            outcome_category=str(o.outcome_category),
            rewards=rewards_by_outcome.get(o.quest_outcome_id, []),
        )
        for o in connection.execute(
            text(
                "SELECT quest_outcome_id, code, name, description, outcome_category "
                "FROM narrative.quest_outcomes WHERE quest_id = :q ORDER BY created_at, code"
            ),
            {"q": quest_id},
        )
    ]

    progress = quest_has_progress(connection, quest_id)
    extra = type_specific_blocks(connection, entity_id=quest_id, entity_type_code="quest")
    available, blocked = evaluate_content_actions(
        entity_type_code="quest",
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
        extra_blocked=extra or None,
    )
    if "update" in available:
        available = [*available, *FREE_QUEST_ACTIONS]
        if progress:
            blocked = [
                *blocked,
                *(BlockedAction(a, QUEST_HAS_PROGRESS) for a in STRUCTURAL_QUEST_ACTIONS),
            ]
        else:
            available = [*available, *STRUCTURAL_QUEST_ACTIONS]
    return QuestAuthoringView(
        quest_id=quest_id,
        name=str(row.canonical_name),
        summary=row.summary,
        stages=stages,
        has_progress=progress,
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
        row_version=int(row.row_version),
        available_actions=available,
        blocked_actions=blocked,
        field_locks=["structure"] if progress else [],
        gm_notes=row.gm_notes,
        dependencies=dependencies,
        participants=participants,
        outcomes=outcomes,
    )


def quest_option_catalogs() -> dict[str, list[tuple[str, str]]]:
    return {
        "stage_types": list(STAGE_TYPES),
        "requirement_levels": list(REQUIREMENT_LEVELS),
        "completion_modes": list(COMPLETION_MODES),
        "visibility_policies": list(VISIBILITY_POLICIES),
        "dependency_types": list(DEPENDENCY_TYPES),
        "participant_roles": list(PARTICIPANT_ROLES),
        "outcome_categories": list(OUTCOME_CATEGORIES),
        "reward_types": list(REWARD_TYPES),
    }


def objective_target_type_codes() -> frozenset[str]:
    return OBJECTIVE_TARGET_TYPE_CODES
