import type { StatusReceipt } from "../types/organizationMembers"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

export const organizationMembersPath = (campaignId: string, organizationId: string): string =>
    `/campaigns/${enc(campaignId)}/organizations/${enc(organizationId)}/members`

export function setOrganizationStatus(
    campaignId: string,
    organizationId: string,
    body: { world_time_id: string; new_status_code: string; expected_status: string | null },
    ctx: MutationContext,
): Promise<StatusReceipt> {
    return apiRequest<StatusReceipt>(
        "POST",
        `/campaigns/${enc(campaignId)}/organizations/${enc(organizationId)}/status`,
        { body, ...ctx },
    )
}
