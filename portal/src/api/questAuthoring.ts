import type { QuestReceipt } from "../types/contentAuthoring"
import type { CreateQuestBody, QuestCommand, QuestTargetOptionPage } from "../types/questAuthoring"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

function base(campaignId: string): string {
    return `/campaigns/${encodeURIComponent(campaignId)}/authoring/quests`
}

const enc = encodeURIComponent

export const questOptionsPath = (campaignId: string): string => `${base(campaignId)}/options`

export const questAuthoringPath = (campaignId: string, questId: string): string =>
    `${base(campaignId)}/${enc(questId)}`

export function fetchQuestTargetOptions(
    campaignId: string,
    query: string,
    signal?: AbortSignal,
): Promise<QuestTargetOptionPage> {
    const params = new URLSearchParams({ limit: "25" })
    if (query.trim() !== "") params.set("q", query.trim())
    return apiRequest<QuestTargetOptionPage>(
        "GET",
        `${base(campaignId)}/target-options?${params.toString()}`,
        { signal },
    )
}

export function createQuest(
    campaignId: string,
    body: CreateQuestBody,
    ctx: MutationContext,
): Promise<QuestReceipt> {
    return apiRequest<QuestReceipt>("POST", base(campaignId), { body, ...ctx })
}

// Runs one quest command and returns the whole authoring view.
export function runQuestCommand(
    campaignId: string,
    questId: string,
    command: QuestCommand,
    ctx: MutationContext,
): Promise<QuestReceipt> {
    const quest = questAuthoringPath(campaignId, questId)
    const post = (path: string, body: unknown) =>
        apiRequest<QuestReceipt>("POST", `${quest}${path}`, { body, ...ctx })
    switch (command.op) {
        case "update_quest":
            return post("/update", command.body)
        case "add_stage":
            return post("/stages", command.body)
        case "update_stage":
            return post(`/stages/${enc(command.stageId)}/update`, command.body)
        case "remove_stage":
            return post(`/stages/${enc(command.stageId)}/remove`, {
                expected_row_version: command.expected_row_version,
            })
        case "reorder_stages":
            return post("/stages/reorder", {
                expected_row_version: command.expected_row_version,
                stage_ids: command.stage_ids,
            })
        case "add_objective":
            return post(`/stages/${enc(command.stageId)}/objectives`, command.body)
        case "update_objective":
            return post(
                `/stages/${enc(command.stageId)}/objectives/${enc(command.objectiveId)}/update`,
                command.body,
            )
        case "add_dependency":
            return post("/dependencies", command.body)
        case "remove_dependency":
            return post(`/dependencies/${enc(command.dependencyId)}/remove`, {
                expected_row_version: command.expected_row_version,
            })
        case "add_participant":
            return post("/participants", command.body)
        case "remove_participant":
            return post(`/participants/${enc(command.participantId)}/remove`, {
                expected_row_version: command.expected_row_version,
            })
        case "add_outcome":
            return post("/outcomes", command.body)
        case "update_outcome":
            return post(`/outcomes/${enc(command.outcomeId)}/update`, command.body)
        case "remove_outcome":
            return post(`/outcomes/${enc(command.outcomeId)}/remove`, {
                expected_row_version: command.expected_row_version,
            })
        case "add_reward":
            return post(`/outcomes/${enc(command.outcomeId)}/rewards`, command.body)
        case "remove_reward":
            return post(`/rewards/${enc(command.rewardId)}/remove`, {
                expected_row_version: command.expected_row_version,
            })
        case "remove_objective":
            return post(
                `/stages/${enc(command.stageId)}/objectives/${enc(command.objectiveId)}/remove`,
                { expected_row_version: command.expected_row_version },
            )
    }
}
