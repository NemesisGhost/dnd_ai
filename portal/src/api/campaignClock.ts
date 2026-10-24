import type { AdvanceClockBody, ClockReceipt, ClockState, CorrectClockBody } from "../types/campaignClock"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

export const clockPath = (campaignId: string): string => `/campaigns/${enc(campaignId)}/clock`

export function advanceClock(
    campaignId: string,
    body: AdvanceClockBody,
    ctx: MutationContext,
): Promise<ClockReceipt> {
    return apiRequest<ClockReceipt>("POST", `${clockPath(campaignId)}/advance`, { body, ...ctx })
}

export function correctClock(
    campaignId: string,
    body: CorrectClockBody,
    ctx: MutationContext,
): Promise<ClockReceipt> {
    return apiRequest<ClockReceipt>("POST", `${clockPath(campaignId)}/correct`, { body, ...ctx })
}

export type { ClockState }
