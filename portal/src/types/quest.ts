export interface CampaignQuestListItem {
    quest_id: string
    name: string
    status_code: string | null
}

export interface QuestObjective {
    quest_objective_id: string
    name: string
    description: string | null
    requirement_level: string
    completion_mode: string
    visibility_policy: string
    quantity_required: number | null
    status_code: string | null
}

export interface QuestStage {
    quest_stage_id: string
    name: string
    description: string | null
    sequence_number: number
    stage_type: string
    objectives: QuestObjective[]
}

export interface QuestDetail {
    quest_id: string
    name: string
    status_code: string | null
    stages: QuestStage[]
}