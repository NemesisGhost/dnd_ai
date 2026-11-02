import type { RuntimeCommand, RuntimeReceipt } from "../types/questRuntime"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

export const questProgressPath = (campaignId: string, questId: string): string =>
    `/campaigns/${enc(campaignId)}/quests/${enc(questId)}/progress`

// Runs one explicit GM command; the caller refetches the progress afterwards.
export function runQuestRuntimeCommand(
    campaignId: string,
    questId: string,
    command: RuntimeCommand,
    ctx: MutationContext,
): Promise<RuntimeReceipt> {
    const quests = `/campaigns/${enc(campaignId)}/quests`
    if (command.op === "quest") {
        return apiRequest<RuntimeReceipt>("POST", `${quests}/${enc(questId)}/${command.action}`, {
            body: {
                expected_status: command.expected_status,
                party_id: command.party_id,
                note: command.note,
            },
            ...ctx,
        })
    }
    return apiRequest<RuntimeReceipt>(
        "POST",
        `${quests}/objectives/${enc(command.objectiveId)}/status`,
        {
            body: {
                new_status: command.new_status,
                expected_status: command.expected_status,
                party_id: command.party_id,
            },
            ...ctx,
        },
    )
}
