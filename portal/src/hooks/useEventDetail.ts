import { fetchEventDetail } from "../api/world"
import type { EventDetail } from "../types/world"
import { useWorldDetail } from "./useWorldDetail"
import type { UseWorldDetailResult } from "./useWorldDetail"

export function useEventDetail(
    campaignId: string,
    eventId: string,
): UseWorldDetailResult<EventDetail> {
    return useWorldDetail(fetchEventDetail, campaignId, eventId)
}
