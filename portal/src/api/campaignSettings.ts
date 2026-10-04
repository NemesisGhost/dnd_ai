import type {
    CampaignMutationResponse,
    CreateCampaignRequest,
    CreateCampaignResponse,
    UpdateCampaignRequest,
} from "../types/campaignSettings"
import type { TransitionRequest } from "../types/worldAuthoring"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

export const ARCHIVED_CAMPAIGNS_PATH = "/campaigns/archived?limit=100"

export function campaignSettingsPath(campaignId: string): string {
    return `/campaigns/${encodeURIComponent(campaignId)}/settings`
}

export function createCampaign(
    body: CreateCampaignRequest,
    ctx: MutationContext,
): Promise<CreateCampaignResponse> {
    return apiRequest<CreateCampaignResponse>("POST", "/campaigns", { body, ...ctx })
}

export function updateCampaign(
    campaignId: string,
    body: UpdateCampaignRequest,
    ctx: MutationContext,
): Promise<CampaignMutationResponse> {
    return apiRequest<CampaignMutationResponse>(
        "POST",
        `/campaigns/${encodeURIComponent(campaignId)}/update`,
        { body, ...ctx },
    )
}

export function archiveCampaign(
    campaignId: string,
    body: TransitionRequest,
    ctx: MutationContext,
): Promise<CampaignMutationResponse> {
    return apiRequest<CampaignMutationResponse>(
        "POST",
        `/campaigns/${encodeURIComponent(campaignId)}/archive`,
        { body, ...ctx },
    )
}

export function reactivateCampaign(
    campaignId: string,
    body: { expected_row_version: number },
    ctx: MutationContext,
): Promise<CampaignMutationResponse> {
    return apiRequest<CampaignMutationResponse>(
        "POST",
        `/campaigns/${encodeURIComponent(campaignId)}/reactivate`,
        { body, ...ctx },
    )
}
