import type {
    CalendarListResponse,
    CalendarReceipt,
    CreateCalendarBody,
    CreateWorldTimeBody,
    WorldTimePage,
    WorldTimeReceipt,
} from "../types/worldTime"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

export const worldCalendarsPath = (worldId: string): string => `/worlds/${enc(worldId)}/calendars`
export const campaignCalendarsPath = (campaignId: string): string =>
    `/campaigns/${enc(campaignId)}/calendars`
export const worldTimesPath = (campaignId: string, params?: { limit?: number; cursor?: string }): string => {
    const query = new URLSearchParams()
    if (params?.limit !== undefined) query.set("limit", String(params.limit))
    if (params?.cursor !== undefined) query.set("cursor", params.cursor)
    const suffix = query.toString()
    return `/campaigns/${enc(campaignId)}/world-times${suffix === "" ? "" : `?${suffix}`}`
}

export function fetchCampaignCalendars(
    campaignId: string,
    signal?: AbortSignal,
): Promise<CalendarListResponse> {
    return apiRequest<CalendarListResponse>("GET", campaignCalendarsPath(campaignId), { signal })
}

export function fetchWorldTimes(
    campaignId: string,
    params?: { limit?: number; cursor?: string },
    signal?: AbortSignal,
): Promise<WorldTimePage> {
    return apiRequest<WorldTimePage>("GET", worldTimesPath(campaignId, params), { signal })
}

export function createCalendar(
    worldId: string,
    body: CreateCalendarBody,
    ctx: MutationContext,
): Promise<CalendarReceipt> {
    return apiRequest<CalendarReceipt>("POST", worldCalendarsPath(worldId), { body, ...ctx })
}

export function createWorldTime(
    campaignId: string,
    body: CreateWorldTimeBody,
    ctx: MutationContext,
): Promise<WorldTimeReceipt> {
    return apiRequest<WorldTimeReceipt>("POST", `/campaigns/${enc(campaignId)}/world-times`, {
        body,
        ...ctx,
    })
}
