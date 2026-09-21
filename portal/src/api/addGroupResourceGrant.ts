import type {
    AddGroupResourceGrantRequest,
    AddGroupResourceGrantResponse,
} from "../types/addGroupResourceGrant"

export class AddGroupResourceGrantRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(`Add group resource grant request failed with status ${status}`)
        this.name = "AddGroupResourceGrantRequestError"
        this.status = status
    }
}

// Character-target, group-grantee, allow-effect only — the same portal
// scope ../api/addResourceGrant.ts already applies to a member grantee
// (see dnd_ai.commands.access_grants' own module docstring). The server
// independently re-validates and enforces its own delegation policy
// regardless, including this checkpoint's own new requirement that the
// grantee group currently be active.
export async function addGroupResourceGrant(
    campaignId: string,
    accessGroupId: string,
    characterId: string,
    capabilityCode: string,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<AddGroupResourceGrantResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)

    const body: AddGroupResourceGrantRequest = {
        capability_code: capabilityCode,
        effect: "allow",
        grantee_access_group_id: accessGroupId,
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
        throw new AddGroupResourceGrantRequestError(response.status)
    }

    return (await response.json()) as AddGroupResourceGrantResponse
}
