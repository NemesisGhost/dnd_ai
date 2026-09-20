import type { RevokeCharacterRelationshipResponse } from "../types/revokeCharacterRelationship"

export class RevokeCharacterRelationshipRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Revoke character relationship request failed with status ${status}`,
        )
        this.name = "RevokeCharacterRelationshipRequestError"
        this.status = status
    }
}

export async function revokeCharacterRelationship(
    campaignId: string,
    membershipCharacterRelationshipId: string,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<RevokeCharacterRelationshipResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedRelationshipId = encodeURIComponent(
        membershipCharacterRelationshipId,
    )

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/character-relationships/${encodedRelationshipId}/revoke`,
        {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            signal,
            headers: {
                Accept: "application/json",
                "X-CSRF-Token": csrfToken,
                "Idempotency-Key": idempotencyKey,
            },
        },
    )

    if (!response.ok) {
        throw new RevokeCharacterRelationshipRequestError(
            response.status,
        )
    }

    return (
        await response.json()
    ) as RevokeCharacterRelationshipResponse
}
