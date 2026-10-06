import type { PreparedEncounter, PrepareEncounterBody } from "../types/encounters"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

export const sessionEncountersPath = (campaignId: string, sessionId: string): string =>
    `/campaigns/${enc(campaignId)}/authoring/encounters?session_id=${enc(sessionId)}`

export const encounterOptionsPath = (campaignId: string): string =>
    `/campaigns/${enc(campaignId)}/authoring/encounters/options`

export const preparedEncounterPath = (campaignId: string, encounterId: string): string =>
    `/campaigns/${enc(campaignId)}/authoring/encounters/${enc(encounterId)}`

const base = (campaignId: string, encounterId: string): string =>
    `/campaigns/${enc(campaignId)}/encounters/${enc(encounterId)}`

export function prepareEncounter(
    campaignId: string,
    body: PrepareEncounterBody,
    ctx: MutationContext,
): Promise<PreparedEncounter> {
    return apiRequest<PreparedEncounter>("POST", `/campaigns/${enc(campaignId)}/encounters/prepare`, {
        body,
        ...ctx,
    })
}

export function updateEncounter(
    campaignId: string,
    encounterId: string,
    body: { location_id: string | null; summary: string | null },
    ctx: MutationContext,
): Promise<PreparedEncounter> {
    return apiRequest<PreparedEncounter>("POST", `${base(campaignId, encounterId)}/update`, {
        body,
        ...ctx,
    })
}

export function addParticipant(
    campaignId: string,
    encounterId: string,
    body: { participant_entity_id: string; side: string; initiative: number | null },
    ctx: MutationContext,
): Promise<PreparedEncounter> {
    return apiRequest<PreparedEncounter>("POST", `${base(campaignId, encounterId)}/participants`, {
        body,
        ...ctx,
    })
}

export function updateParticipant(
    campaignId: string,
    encounterId: string,
    participantId: string,
    body: { side: string; initiative: number | null },
    ctx: MutationContext,
): Promise<PreparedEncounter> {
    return apiRequest<PreparedEncounter>(
        "POST",
        `${base(campaignId, encounterId)}/participants/${enc(participantId)}/update`,
        { body, ...ctx },
    )
}

export function removeParticipant(
    campaignId: string,
    encounterId: string,
    participantId: string,
    ctx: MutationContext,
): Promise<PreparedEncounter> {
    return apiRequest<PreparedEncounter>(
        "POST",
        `${base(campaignId, encounterId)}/participants/${enc(participantId)}/remove`,
        { body: {}, ...ctx },
    )
}
