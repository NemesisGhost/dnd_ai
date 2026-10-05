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
    dependency_types: QuestChoice[]
    participant_roles: QuestChoice[]
    outcome_categories: QuestChoice[]
    reward_types: QuestChoice[]
    limits: ContentLimits & {
        max_stages: number
        max_objectives_per_stage: number
        quantity_max: number
        gm_notes_max_length: number
        outcome_description_max_length: number
        reward_description_max_length: number
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

export interface QuestDependencyView {
    objective_dependency_id: string
    objective_id: string
    depends_on_objective_id: string
    dependency_type: string
}

export interface QuestParticipantView {
    quest_participant_id: string
    participant_role: string
    participant: EntityReferenceSummary | null
}

export interface QuestRewardView {
    quest_reward_id: string
    reward_type: string
    description: string
    knowledge: EntityReferenceSummary | null
}

export interface QuestOutcomeView {
    quest_outcome_id: string
    code: string
    name: string
    description: string | null
    outcome_category: string
    rewards: QuestRewardView[]
}

export interface QuestAuthoringView extends AuthoringReadModel {
    quest_id: string
    name: string
    summary: string | null
    stages: QuestStageView[]
    has_progress: boolean
    // GM-only planning text, dependencies between objectives, participants, and outcomes.
    gm_notes: string | null
    dependencies: QuestDependencyView[]
    participants: QuestParticipantView[]
    outcomes: QuestOutcomeView[]
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
    // Omitted keeps the current notes; null clears them.
    gm_notes?: string | null
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
    | {
          op: "add_dependency"
          body: {
              expected_row_version: number
              objective_id: string
              depends_on_objective_id: string
              dependency_type: string
          }
      }
    | { op: "remove_dependency"; dependencyId: string; expected_row_version: number }
    | {
          op: "add_participant"
          body: { expected_row_version: number; participant_entity_id: string; participant_role: string }
      }
    | { op: "remove_participant"; participantId: string; expected_row_version: number }
    | {
          op: "add_outcome"
          body: {
              expected_row_version: number
              code: string
              name: string
              description: string | null
              outcome_category: string
          }
      }
    | {
          op: "update_outcome"
          outcomeId: string
          body: {
              expected_row_version: number
              name: string
              description: string | null
              outcome_category: string
          }
      }
    | { op: "remove_outcome"; outcomeId: string; expected_row_version: number }
    | {
          op: "add_reward"
          outcomeId: string
          body: {
              expected_row_version: number
              reward_type: string
              description: string
              reward_knowledge_item_id: string | null
          }
      }
    | { op: "remove_reward"; rewardId: string; expected_row_version: number }
