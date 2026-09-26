import type {
    AddResourceGrantRequest,
    AddResourceGrantResponse,
} from "../types/addResourceGrant"
import type { ResourceGrantEffect, ResourceGrantTarget } from "../types/resourceGrantTarget"

export class AddResourceGrantRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(`Add resource grant request failed with status ${status}`)
        this.name = "AddResourceGrantRequestError"
        this.status = status
    }
}

// Membership grantee, any of the six target kinds, allow or deny -- the
// server independently re-validates and enforces its own delegation
// policy regardless of what this client ever sends
// (dnd_ai.domain.access.RESOURCE_GRANT_CAPABILITY_CATALOG), including the
// CTI-column guard that rejects an entity_id target belonging to one of
// the four kinds with their own column.
export async function addResourceGrant(
    campaignId: string,
    campaignMembershipId: string,
    target: ResourceGrantTarget,
    capabilityCode: string,
    effect: ResourceGrantEffect,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<AddResourceGrantResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)

    const body: AddResourceGrantRequest = {
        capability_code: capabilityCode,
        effect,
        grantee_campaign_membership_id: campaignMembershipId,
        [target.field]: target.id,
    }

    const response = await fetch(`/api/campaigns/${encodedCampaignId}/resource-grants`, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
            "Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify(body),
    })

    if (!response.ok) {
        throw new AddResourceGrantRequestError(response.status)
    }

    return (await response.json()) as AddResourceGrantResponse
}
