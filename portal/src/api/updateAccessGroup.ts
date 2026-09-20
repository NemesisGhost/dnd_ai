import type {
    AccessGroupResponse,
    UpdateAccessGroupRequest,
} from "../types/accessGroup"

export class UpdateAccessGroupRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(`Update access group request failed with status ${status}`)
        this.name = "UpdateAccessGroupRequestError"
        this.status = status
    }
}

export async function updateAccessGroup(
    campaignId: string,
    accessGroupId: string,
    name: string,
    description: string | null,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<AccessGroupResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedGroupId = encodeURIComponent(accessGroupId)

    const body: UpdateAccessGroupRequest = { name, description }

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/access-groups/${encodedGroupId}/update`,
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
        throw new UpdateAccessGroupRequestError(response.status)
    }

    return (await response.json()) as AccessGroupResponse
}
