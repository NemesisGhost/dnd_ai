import type {
    AddGroupResourceGrantRequest,
    AddGroupResourceGrantResponse,
} from "../types/addGroupResourceGrant"
import type { ResourceGrantEffect, ResourceGrantTarget } from "../types/resourceGrantTarget"

export class AddGroupResourceGrantRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(`Add group resource grant request failed with status ${status}`)
        this.name = "AddGroupResourceGrantRequestError"
        this.status = status
    }
}

// Group grantee, any of the six target kinds, allow or deny -- the same
// portal scope ../api/addResourceGrant.ts applies to a member grantee.
export async function addGroupResourceGrant(
    campaignId: string,
    accessGroupId: string,
    target: ResourceGrantTarget,
    capabilityCode: string,
    effect: ResourceGrantEffect,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<AddGroupResourceGrantResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)

    const body: AddGroupResourceGrantRequest = {
        capability_code: capabilityCode,
        effect,
        grantee_access_group_id: accessGroupId,
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
        throw new AddGroupResourceGrantRequestError(response.status)
    }

    return (await response.json()) as AddGroupResourceGrantResponse
}
