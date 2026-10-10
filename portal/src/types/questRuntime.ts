// Quest progress and runtime commands (Phase 15 checkpoint 15.2E-2b).

export type QuestStatus =
    | "unavailable"
    | "available"
    | "active"
    | "suspended"
    | "completed"
    | "failed"
    | "abandoned"

export type QuestAction = "activate" | "complete" | "fail" | "suspend" | "resume" | "abandon"

export interface ObjectiveProgress {
    quest_objective_id: string
    name: string
    stage_name: string
    requirement_level: string
    status: string | null
    next_statuses: string[]
}

export interface ScopeProgress {
    party_id: string | null
    party_name: string | null
    status: QuestStatus | null
    actions: QuestAction[]
    all_required_complete: boolean
    objectives: ObjectiveProgress[]
}

export interface QuestProgress {
    quest_id: string
    name: string
    published: boolean
    scopes: ScopeProgress[]
}

export interface RuntimeReceipt {
    quest_id: string
    event_id: string
    previous_status: string | null
    status: string
    changed: boolean
    quest_objective_id?: string
}

export type RuntimeCommand =
    | {
          op: "quest"
          action: QuestAction
          party_id: string | null
          expected_status: string | null
          note: string | null
      }
    | {
          op: "objective"
          objectiveId: string
          new_status: string
          party_id: string | null
          expected_status: string | null
      }
