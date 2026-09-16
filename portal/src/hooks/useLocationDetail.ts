import { fetchLocationDetail } from "../api/world"
import type { LocationDetail } from "../types/world"
import { useWorldDetail } from "./useWorldDetail"
import type { UseWorldDetailResult } from "./useWorldDetail"

export function useLocationDetail(
    campaignId: string,
    locationId: string,
): UseWorldDetailResult<LocationDetail> {
    return useWorldDetail(fetchLocationDetail, campaignId, locationId)
}
