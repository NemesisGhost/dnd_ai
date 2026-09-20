import type {
    AddResourceGrantRequest,
    AddResourceGrantResponse,
} from "../types/addResourceGrant"

export class AddResourceGrantRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(`Add resource grant request failed with status ${status}`)
        this.name = "AddResourceGrantRequestError"
        this.status = status
    }
}

// Character-target, membership-grantee, allow-effect only — the one
// resource-grant shape this checkpoint's portal UI supports (see
// dnd_ai.commands.access_grants' own module docstring for why the other
// five target kinds, access-group grantees, and an explicit deny effect
// are deferred). The server independently re-validates and enforces its
// own delegation policy regardless of what this client ever sends
// (dnd_ai.domain.access.RESOURCE_GRANT_CAPABILITY_CATALOG).
export async function addResourceGrant(
    campaignId: string,
    campaignMembershipId: string,
    characterId: string,
    capabilityCode: string,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<AddResourceGrantResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)

    const body: AddResourceGrantRequest = {
        capability_code: capabilityCode,
        effect: "allow",
        grantee_campaign_membership_id: campaignMembershipId,
        character_id: characterId,
    }

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/resource-grants`,
        {
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
        },
    )

    if (!response.ok) {
        throw new AddResourceGrantRequestError(response.status)
    }

    return (await response.json()) as AddResourceGrantResponse
}
