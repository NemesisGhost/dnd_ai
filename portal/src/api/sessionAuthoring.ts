import type { SessionReceipt } from "../types/campaignSession"
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
