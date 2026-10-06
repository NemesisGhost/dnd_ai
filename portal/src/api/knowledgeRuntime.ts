import type { KnowledgeCommand, KnowledgeRuntimeReceipt } from "../types/knowledgeRuntime"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

export const knowledgeAudiencePath = (campaignId: string, knowledgeItemId: string): string =>
    `/campaigns/${enc(campaignId)}/knowledge/${enc(knowledgeItemId)}/audience`

// Runs one explicit GM command; the caller refetches the audience afterwards.
export function runKnowledgeCommand(
    campaignId: string,
    knowledgeItemId: string,
    command: KnowledgeCommand,
    ctx: MutationContext,
): Promise<KnowledgeRuntimeReceipt> {
    const base = `/campaigns/${enc(campaignId)}/knowledge`
    const item = `${base}/${enc(knowledgeItemId)}`
    const post = (path: string, body: unknown) =>
        apiRequest<KnowledgeRuntimeReceipt>("POST", path, { body, ...ctx })
    switch (command.op) {
        case "reveal":
            return post(`${item}/reveal-to-party`, {
                party_id: command.party_id,
                awareness_level: command.awareness_level,
            })
        case "learn":
            return post(`${item}/learn`, {
                knower_entity_id: command.knower_entity_id,
                awareness_level: command.awareness_level,
                confidence: command.confidence,
                interpretation: command.interpretation,
            })
        case "transfer":
            return post(`${item}/transfer`, {
                source_entity_id: command.source_entity_id,
                recipient_entity_id: command.recipient_entity_id,
                transfer_method: command.transfer_method,
                awareness_level: command.awareness_level,
                modified_interpretation: command.modified_interpretation,
            })
        case "public":
            return post(`${item}/make-public`, {
                location_id: command.location_id,
                awareness_level: command.awareness_level,
            })
        case "belief":
            return post(`${base}/knowers/${enc(command.entity_knowledge_id)}/belief`, {
                expected_last_event_id: command.expected_last_event_id,
                ...command.changes,
            })
    }
}
