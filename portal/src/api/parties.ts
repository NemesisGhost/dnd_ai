import type { PartyFieldsBody, PartyReceipt } from "../types/parties"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

export const partiesPath = (campaignId: string, includeArchived = false): string =>
    `/campaigns/${enc(campaignId)}/parties${includeArchived ? "?include_archived=true" : ""}`

export const partyPath = (campaignId: string, partyId: string): string =>
    `/campaigns/${enc(campaignId)}/parties/${enc(partyId)}`

export function createParty(
    campaignId: string,
    body: PartyFieldsBody,
    ctx: MutationContext,
): Promise<PartyReceipt> {
    return apiRequest<PartyReceipt>("POST", `/campaigns/${enc(campaignId)}/parties`, {
        body,
        ...ctx,
    })
}

export function updateParty(
    campaignId: string,
    partyId: string,
    body: PartyFieldsBody & { expected_row_version: number },
    ctx: MutationContext,
): Promise<PartyReceipt> {
    return apiRequest<PartyReceipt>("POST", `${partyPath(campaignId, partyId)}/update`, {
        body,
        ...ctx,
    })
}

export function archiveParty(
    campaignId: string,
    partyId: string,
    body: { expected_row_version: number; reason: string | null },
    ctx: MutationContext,
): Promise<PartyReceipt> {
    return apiRequest<PartyReceipt>("POST", `${partyPath(campaignId, partyId)}/archive`, {
        body,
        ...ctx,
    })
}

export function restoreParty(
    campaignId: string,
    partyId: string,
    body: { expected_row_version: number; reason: string },
    ctx: MutationContext,
): Promise<PartyReceipt> {
    return apiRequest<PartyReceipt>("POST", `${partyPath(campaignId, partyId)}/restore`, {
        body,
        ...ctx,
    })
}
