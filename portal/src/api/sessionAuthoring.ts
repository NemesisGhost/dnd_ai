import type { PlayReceipt, SessionReceipt } from "../types/campaignSession"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

export const sessionPath = (campaignId: string, sessionId: string): string =>
    `/campaigns/${enc(campaignId)}/sessions/${enc(sessionId)}`

interface SessionFieldsBody {
    title: string | null
    scheduled_for: string | null
    summary: string | null
}

export function scheduleSession(
    campaignId: string,
    body: SessionFieldsBody,
    ctx: MutationContext,
): Promise<SessionReceipt> {
    return apiRequest<SessionReceipt>("POST", `/campaigns/${enc(campaignId)}/sessions`, {
        body,
        ...ctx,
    })
}

export function updateSession(
    campaignId: string,
    sessionId: string,
    body: SessionFieldsBody & { expected_row_version: number },
    ctx: MutationContext,
): Promise<SessionReceipt> {
    return apiRequest<SessionReceipt>("POST", `${sessionPath(campaignId, sessionId)}/update`, {
        body,
        ...ctx,
    })
}

export function archiveSession(
    campaignId: string,
    sessionId: string,
    body: { expected_row_version: number; reason: string | null },
    ctx: MutationContext,
): Promise<SessionReceipt> {
    return apiRequest<SessionReceipt>("POST", `${sessionPath(campaignId, sessionId)}/archive`, {
        body,
        ...ctx,
    })
}

export function restoreSession(
    campaignId: string,
    sessionId: string,
    body: { expected_row_version: number; reason: string },
    ctx: MutationContext,
): Promise<SessionReceipt> {
    return apiRequest<SessionReceipt>("POST", `${sessionPath(campaignId, sessionId)}/restore`, {
        body,
        ...ctx,
    })
}

export function startSession(
    campaignId: string,
    sessionId: string,
    body: { expected_row_version: number; start_world_time_id: string | null },
    ctx: MutationContext,
): Promise<PlayReceipt> {
    return apiRequest<PlayReceipt>("POST", `${sessionPath(campaignId, sessionId)}/start`, {
        body,
        ...ctx,
    })
}

export function endSession(
    campaignId: string,
    sessionId: string,
    body: {
        expected_row_version: number
        end_world_time_id: string | null
        summary: string | null
    },
    ctx: MutationContext,
): Promise<PlayReceipt> {
    return apiRequest<PlayReceipt>("POST", `${sessionPath(campaignId, sessionId)}/end`, {
        body,
        ...ctx,
    })
}

export function addSessionParticipant(
    campaignId: string,
    sessionId: string,
    body: { expected_row_version: number; character_id: string; participation_role: string },
    ctx: MutationContext,
): Promise<PlayReceipt> {
    return apiRequest<PlayReceipt>("POST", `${sessionPath(campaignId, sessionId)}/participants`, {
        body,
        ...ctx,
    })
}

export function removeSessionParticipant(
    campaignId: string,
    sessionId: string,
    participantId: string,
    body: { expected_row_version: number },
    ctx: MutationContext,
): Promise<PlayReceipt> {
    return apiRequest<PlayReceipt>(
        "POST",
        `${sessionPath(campaignId, sessionId)}/participants/${enc(participantId)}/remove`,
        { body, ...ctx },
    )
}

export function logSessionEntry(
    campaignId: string,
    sessionId: string,
    body: { entry: string; details: string | null; world_time_id: string | null },
    ctx: MutationContext,
): Promise<PlayReceipt> {
    return apiRequest<PlayReceipt>("POST", `${sessionPath(campaignId, sessionId)}/log`, {
        body,
        ...ctx,
    })
}
