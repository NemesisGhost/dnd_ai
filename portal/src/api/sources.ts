import type { Provenance, SourceItem } from "../types/provenance"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

export const sourcesPath = (campaignId: string): string => `/campaigns/${enc(campaignId)}/sources`

export const provenancePath = (campaignId: string, entityId: string): string =>
    `/campaigns/${enc(campaignId)}/entities/${enc(entityId)}/provenance`

export function createSource(
    campaignId: string,
    body: { source_type: string; title: string; reference: string | null },
    ctx: MutationContext,
): Promise<SourceItem> {
    return apiRequest<SourceItem>("POST", sourcesPath(campaignId), { body, ...ctx })
}

export function attachSource(
    campaignId: string,
    entityId: string,
    sourceId: string,
    ctx: MutationContext,
): Promise<Provenance> {
    return apiRequest<Provenance>(
        "POST",
        `/campaigns/${enc(campaignId)}/entities/${enc(entityId)}/sources/attach`,
        { body: { source_id: sourceId }, ...ctx },
    )
}

export function detachSource(
    campaignId: string,
    entityId: string,
    sourceId: string,
    ctx: MutationContext,
): Promise<Provenance> {
    return apiRequest<Provenance>(
        "POST",
        `/campaigns/${enc(campaignId)}/entities/${enc(entityId)}/sources/detach`,
        { body: { source_id: sourceId }, ...ctx },
    )
}
