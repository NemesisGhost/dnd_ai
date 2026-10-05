import type { AuthoringReadModel, ContentLimits, EntityReferenceSummary } from "./contentAuthoring"

// Quest definition authoring contracts (Phase 15.1). The whole aggregate is one
// read model: the quest, its ordered stages, and each stage's objectives. No
// progress and no completion rule is part of it.

export interface QuestChoice {
    value: string
    label: string
}

export interface QuestOptions {
    can_create: boolean
    objective_types: QuestChoice[]
    stage_types: QuestChoice[]
    requirement_levels: QuestChoice[]
    completion_modes: QuestChoice[]
    visibility_policies: QuestChoice[]
    limits: ContentLimits & {
        max_stages: number
        max_objectives_per_stage: number
        quantity_max: number
    }
}

export interface QuestObjectiveView {
    quest_objective_id: string
    name: string
    description: string | null
    objective_type: string
    objective_type_label: string
    requirement_level: string
    completion_mode: string
    visibility_policy: string
    quantity_required: number | null
    target_kind: string | null
    target: EntityReferenceSummary | null
}

export interface QuestStageView {
    quest_stage_id: string
    name: string
    description: string | null
    stage_type: string
    sequence_number: number
    objectives: QuestObjectiveView[]
}

export interface QuestAuthoringView extends AuthoringReadModel {
    quest_id: string
    name: string
    summary: string | null
    stages: QuestStageView[]
    has_progress: boolean
}

export interface QuestTargetOption {
    entity_id: string
    name: string
    kind: string
    canon_status: string
}

export interface QuestTargetOptionPage {
    items: QuestTargetOption[]
    next_cursor: string | null
}

export interface CreateQuestBody {
    name: string
    summary: string | null
}

export interface UpdateQuestBody extends CreateQuestBody {
    expected_row_version: number
    change_note?: string | null
}

export interface StageBody {
    expected_row_version: number
    name: string
    description: string | null
    stage_type: string
}

export interface ObjectiveBody {
    expected_row_version: number
    name: string
    description: string | null
    objective_type: string
    requirement_level: string
    completion_mode: string
    visibility_policy: string
    quantity_required: number | null
    target_entity_id: string | null
}

// One serializable description of a quest command. The editor submits these
// through a single idempotent mutation, so the Idempotency-Key follows the body.
export type QuestCommand =
    | { op: "update_quest"; body: UpdateQuestBody }
    | { op: "add_stage"; body: StageBody }
    | { op: "update_stage"; stageId: string; body: StageBody }
    | { op: "remove_stage"; stageId: string; expected_row_version: number }
    | { op: "reorder_stages"; expected_row_version: number; stage_ids: string[] }
    | { op: "add_objective"; stageId: string; body: ObjectiveBody }
    | { op: "update_objective"; stageId: string; objectiveId: string; body: ObjectiveBody }
    | { op: "remove_objective"; stageId: string; objectiveId: string; expected_row_version: number }
