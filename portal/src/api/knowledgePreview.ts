import type { KnowledgeView } from "../types/knowledge"

const enc = encodeURIComponent

const previewBase = (campaignId: string, membershipId: string): string =>
    `/campaigns/${enc(campaignId)}/members/${enc(membershipId)}/preview/knowledge`

export interface PreviewKnowledgeListParameters {
    view: KnowledgeView
    characterId: string | null
    partyId: string | null
    query: string
    includePublic: boolean
    cursor: string | null
}

// Paths (without the `/api` prefix `apiRequest` adds) of the server's three Knowledge preview reads
// (`dnd_ai.api.preview`). Every one names the previewed member's membership; the server resolves
// the member, authorizes the actor, and projects the response for that member. Perspective values
// are interpreted against the previewed member, never the signed-in actor.
export function previewKnowledgeListPath(
    campaignId: string,
    membershipId: string,
    parameters: PreviewKnowledgeListParameters,
): string {
    const search = new URLSearchParams()
    search.set("view", parameters.view)
    if (parameters.characterId !== null) search.set("character_id", parameters.characterId)
    if (parameters.partyId !== null) search.set("party_id", parameters.partyId)
    if (parameters.query !== "") search.set("q", parameters.query)
    if (!parameters.includePublic) search.set("include_public", "false")
    if (parameters.cursor !== null) search.set("cursor", parameters.cursor)
    return `${previewBase(campaignId, membershipId)}?${search.toString()}`
}

export function previewKnowledgeDetailPath(
    campaignId: string,
    membershipId: string,
    knowledgeItemId: string,
    characterId: string | null,
    partyId: string | null,
): string {
    const search = new URLSearchParams()
    if (characterId !== null) search.set("character_id", characterId)
    if (partyId !== null) search.set("party_id", partyId)
    const query = search.toString()
    const path = `${previewBase(campaignId, membershipId)}/${enc(knowledgeItemId)}`
    return query === "" ? path : `${path}?${query}`
}

export const previewPerspectivesPath = (campaignId: string, membershipId: string): string =>
    `${previewBase(campaignId, membershipId)}/perspectives`
