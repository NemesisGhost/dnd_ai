import { fetchReligionDetail } from "../api/world"
import type { ReligionDetail } from "../types/world"
import { useWorldDetail } from "./useWorldDetail"
import type { UseWorldDetailResult } from "./useWorldDetail"

export function useReligionDetail(
    campaignId: string,
    religionId: string,
): UseWorldDetailResult<ReligionDetail> {
    return useWorldDetail(fetchReligionDetail, campaignId, religionId)
}
