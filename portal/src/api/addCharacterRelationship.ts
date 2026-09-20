import type {
    AddCharacterRelationshipRequest,
    AddCharacterRelationshipResponse,
} from "../types/addCharacterRelationship"

export class AddCharacterRelationshipRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Add character relationship request failed with status ${status}`,
        )
        this.name = "AddCharacterRelationshipRequestError"
        this.status = status
    }
}

export async function addCharacterRelationship(
    campaignId: string,
    campaignMembershipId: string,
    characterId: string,
    relationshipTypeCode: string,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<AddCharacterRelationshipResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedMembershipId =
        encodeURIComponent(campaignMembershipId)

    const body: AddCharacterRelationshipRequest = {
        character_id: characterId,
        relationship_type_code: relationshipTypeCode,
    }

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/memberships/${encodedMembershipId}/character-relationships`,
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
        throw new AddCharacterRelationshipRequestError(
            response.status,
        )
    }

    return (
        await response.json()
    ) as AddCharacterRelationshipResponse
}
