import type {
    CreateKnowledgeBody,
    KnowledgeAuthoringView,
    KnowledgeSubjectOptionPage,
    UpdateKnowledgeBody,
} from "../types/knowledgeAuthoring"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

function base(campaignId: string): string {
    return `/campaigns/${encodeURIComponent(campaignId)}/authoring/knowledge`
}

export const knowledgeOptionsPath = (campaignId: string): string => `${base(campaignId)}/options`

export const knowledgeAuthoringPath = (campaignId: string, knowledgeItemId: string): string =>
    `${base(campaignId)}/${encodeURIComponent(knowledgeItemId)}`

export function fetchKnowledgeSubjectOptions(
    campaignId: string,
    query: string,
    signal?: AbortSignal,
): Promise<KnowledgeSubjectOptionPage> {
    const params = new URLSearchParams({ limit: "25" })
    if (query.trim() !== "") params.set("q", query.trim())
    return apiRequest<KnowledgeSubjectOptionPage>(
        "GET",
        `${base(campaignId)}/subject-options?${params.toString()}`,
        { signal },
    )
}

export function createKnowledgeItem(
    campaignId: string,
    body: CreateKnowledgeBody,
    ctx: MutationContext,
): Promise<KnowledgeAuthoringView> {
    return apiRequest<KnowledgeAuthoringView>("POST", base(campaignId), { body, ...ctx })
}

export function updateKnowledgeItem(
    campaignId: string,
    knowledgeItemId: string,
    body: UpdateKnowledgeBody,
    ctx: MutationContext,
): Promise<KnowledgeAuthoringView> {
    return apiRequest<KnowledgeAuthoringView>(
        "POST",
        `${knowledgeAuthoringPath(campaignId, knowledgeItemId)}/update`,
        { body, ...ctx },
    )
}
