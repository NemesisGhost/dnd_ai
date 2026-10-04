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
    OBJECTIVE_TARGET_TYPE_CODES,
    REQUIREMENT_LEVELS,
    STAGE_TYPES,
    VISIBILITY_POLICIES,
)
from dnd_ai.queries.content_preconditions import type_specific_blocks
from dnd_ai.queries.organization_authoring import ReferenceSummary, _reference

QUEST_HAS_PROGRESS = "quest_has_progress"

# Child actions available while the quest is editable; the first three are
# structural and are blocked once progress exists.
STRUCTURAL_QUEST_ACTIONS = ("reorder_stages", "remove_stage", "remove_objective")
FREE_QUEST_ACTIONS = ("add_stage", "update_stage", "add_objective", "update_objective")


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
            SELECT e.canonical_name, e.summary, e.row_version,
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
    )


def quest_option_catalogs() -> dict[str, list[tuple[str, str]]]:
    return {
        "stage_types": list(STAGE_TYPES),
        "requirement_levels": list(REQUIREMENT_LEVELS),
        "completion_modes": list(COMPLETION_MODES),
        "visibility_policies": list(VISIBILITY_POLICIES),
    }


def objective_target_type_codes() -> frozenset[str]:
    return OBJECTIVE_TARGET_TYPE_CODES
