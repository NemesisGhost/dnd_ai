import type { MembershipReceipt, PartyFieldsBody, PartyReceipt } from "../types/parties"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

export const partiesPath = (campaignId: string, includeArchived = false): string =>
    `/campaigns/${enc(campaignId)}/parties${includeArchived ? "?include_archived=true" : ""}`

export const characterPartiesPath = (campaignId: string, characterId: string): string =>
    `/campaigns/${enc(campaignId)}/characters/${enc(characterId)}/parties`

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

export const partyMembersPath = (campaignId: string, partyId: string): string =>
    `${partyPath(campaignId, partyId)}/members`

export function addPartyMember(
    campaignId: string,
    partyId: string,
    body: {
        character_id: string
        effective_from_world_time_id: string
        expected_party_row_version: number
        reason: string | null
    },
    ctx: MutationContext,
): Promise<MembershipReceipt> {
    return apiRequest<MembershipReceipt>("POST", partyMembersPath(campaignId, partyId), {
        body,
        ...ctx,
    })
}

export function endPartyMembership(
    campaignId: string,
    partyId: string,
    membershipId: string,
    body: {
        effective_to_world_time_id: string
        expected_party_row_version: number
        reason: string | null
    },
    ctx: MutationContext,
): Promise<MembershipReceipt> {
    return apiRequest<MembershipReceipt>(
        "POST",
        `${partyMembersPath(campaignId, partyId)}/${enc(membershipId)}/end`,
        { body, ...ctx },
    )
}
