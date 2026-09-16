import { fetchItemDetail } from "../api/world"
import type { ItemDetail } from "../types/world"
import { useWorldDetail } from "./useWorldDetail"
import type { UseWorldDetailResult } from "./useWorldDetail"

export function useItemDetail(
    campaignId: string,
    itemInstanceId: string,
): UseWorldDetailResult<ItemDetail> {
    return useWorldDetail(fetchItemDetail, campaignId, itemInstanceId)
}
