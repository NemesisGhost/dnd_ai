import type {
    CorrectionReceipt,
    EventReceipt,
    RecordEventBody,
    ReplacementBody,
} from "../types/eventAuthoring"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

export const eventPath = (campaignId: string, eventId: string): string =>
    `/campaigns/${enc(campaignId)}/events/${enc(eventId)}`

export const correctionPreviewPath = (campaignId: string, eventId: string): string =>
    `${eventPath(campaignId, eventId)}/correction-preview`

export function recordEvent(
    campaignId: string,
    body: RecordEventBody,
    ctx: MutationContext,
): Promise<EventReceipt> {
    return apiRequest<EventReceipt>("POST", `/campaigns/${enc(campaignId)}/events`, {
        body,
        ...ctx,
    })
}

export function voidEvent(
    campaignId: string,
    eventId: string,
    body: { reason: string },
    ctx: MutationContext,
): Promise<CorrectionReceipt> {
    return apiRequest<CorrectionReceipt>("POST", `${eventPath(campaignId, eventId)}/void`, {
        body,
        ...ctx,
    })
}

export function correctEvent(
    campaignId: string,
    eventId: string,
    body: { reason: string; replacement: ReplacementBody },
    ctx: MutationContext,
): Promise<CorrectionReceipt> {
    return apiRequest<CorrectionReceipt>("POST", `${eventPath(campaignId, eventId)}/correct`, {
        body,
        ...ctx,
    })
}
