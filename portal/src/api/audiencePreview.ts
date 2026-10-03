import type { AudiencePreviewResourceType, AudiencePreviewResult } from "../types/audiencePreview"

export class AudiencePreviewRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(`Audience preview request failed with status ${status}`)
        this.name = "AudiencePreviewRequestError"
        this.status = status
    }
}

export async function fetchAudiencePreview(
    campaignId: string,
    campaignMembershipId: string,
    resourceType: AudiencePreviewResourceType,
    resourceId: string,
    signal?: AbortSignal,
): Promise<AudiencePreviewResult> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedMembershipId = encodeURIComponent(campaignMembershipId)
    const encodedResourceId = encodeURIComponent(resourceId)

    // Mirrors dnd_ai.api.preview's own two fixed routes — "quest" maps to
    // .../preview/quests/{quest_id}, "knowledge_item" to .../preview/
    // knowledge/{knowledge_item_id}. character_id/party_id are
    // deliberately never sent here: this panel always previews the
    // subject's own unfiltered perspective (no perspective override),
    // matching dnd_ai.api.preview's own "interpreted against the subject"
    // contract with no query parameters supplied.
    const path =
        resourceType === "quest"
            ? `/api/campaigns/${encodedCampaignId}/members/${encodedMembershipId}/preview/quests/${encodedResourceId}`
            : `/api/campaigns/${encodedCampaignId}/members/${encodedMembershipId}/preview/knowledge/${encodedResourceId}`

    const response = await fetch(path, {
        method: "GET",
        headers: {
            Accept: "application/json",
        },
        cache: "no-store",
        signal,
    })

    if (!response.ok) {
        throw new AudiencePreviewRequestError(response.status)
    }

    const body = await response.json()
    return resourceType === "quest"
        ? { resourceType: "quest", quest: body }
        : { resourceType: "knowledge_item", knowledgeItem: body }
}
