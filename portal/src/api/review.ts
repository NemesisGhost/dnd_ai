import type { ReviewQueue } from "../types/review"
import { apiRequest } from "./http"

const enc = encodeURIComponent

export const reviewQueuePath = (
    campaignId: string,
    filters: { status: string; type: string; cursor?: string | null },
): string => {
    const params = new URLSearchParams({ status: filters.status })
    if (filters.type !== "") params.set("type", filters.type)
    if (filters.cursor) params.set("cursor", filters.cursor)
    return `/campaigns/${enc(campaignId)}/review-queue?${params.toString()}`
}

export const revisionsPath = (campaignId: string, entityId: string): string =>
    `/campaigns/${enc(campaignId)}/entities/${enc(entityId)}/revisions`

export const comparePath = (campaignId: string, entityId: string, from: number, to: number): string =>
    `${revisionsPath(campaignId, entityId)}/compare?from=${from}&to=${to}`

// The next page of the queue, for "Load more".
export function fetchReviewPage(
    campaignId: string,
    filters: { status: string; type: string; cursor: string },
    signal?: AbortSignal,
): Promise<ReviewQueue> {
    return apiRequest<ReviewQueue>("GET", reviewQueuePath(campaignId, filters), { signal })
}
