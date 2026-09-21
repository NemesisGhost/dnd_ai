import type {
    AccessGroupResponse,
    CreateAccessGroupRequest,
} from "../types/accessGroup"

export class CreateAccessGroupRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(`Create access group request failed with status ${status}`)
        this.name = "CreateAccessGroupRequestError"
        this.status = status
    }
}

export async function createAccessGroup(
    campaignId: string,
    name: string,
    description: string | null,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<AccessGroupResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)

    const body: CreateAccessGroupRequest = { name, description }

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/access-groups`,
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
        throw new CreateAccessGroupRequestError(response.status)
    }

    return (await response.json()) as AccessGroupResponse
}
