import type {
    ChangeCharacterRelationshipRequest,
    ChangeCharacterRelationshipResponse,
} from "../types/changeCharacterRelationship"

export class ChangeCharacterRelationshipRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Change character relationship request failed with status ${status}`,
        )
        this.name = "ChangeCharacterRelationshipRequestError"
        this.status = status
    }
}

export async function changeCharacterRelationship(
    campaignId: string,
    membershipCharacterRelationshipId: string,
    newRelationshipTypeId: string,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<ChangeCharacterRelationshipResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedRelationshipId = encodeURIComponent(
        membershipCharacterRelationshipId,
    )

    const body: ChangeCharacterRelationshipRequest = {
        new_relationship_type_id: newRelationshipTypeId,
    }

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/character-relationships/${encodedRelationshipId}/change`,
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
        throw new ChangeCharacterRelationshipRequestError(
            response.status,
        )
    }

    return (
        await response.json()
    ) as ChangeCharacterRelationshipResponse
}
