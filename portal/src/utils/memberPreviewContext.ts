import type { KnowledgeView } from "../types/knowledge"

// The Member preview workspace keeps everything it selects in its own address, so a reload,
// Back/Forward and a shared link reproduce it, and leaving for normal Knowledge (a link with no
// query) cannot carry any of it along.
export const PREVIEW_VIEWS: readonly KnowledgeView[] = [
    "known",
    "rumors",
    "party_shared",
    "character_private",
    "recent",
    "public",
]

export interface MemberPreviewContext {
    // The previewed member's campaign membership id.
    member: string | null
    characterId: string | null
    partyId: string | null
    view: KnowledgeView
    query: string
    includePublic: boolean
    cursor: string | null
}

const nonEmpty = (value: string | null): string | null => (value === null || value === "" ? null : value)

export function parseMemberPreviewContext(search: URLSearchParams): MemberPreviewContext {
    const view = search.get("view") as KnowledgeView | null
    return {
        member: nonEmpty(search.get("member")),
        characterId: nonEmpty(search.get("character_id")),
        partyId: nonEmpty(search.get("party_id")),
        view: view !== null && PREVIEW_VIEWS.includes(view) ? view : "known",
        query: search.get("q") ?? "",
        includePublic: search.get("public") !== "0",
        cursor: nonEmpty(search.get("cursor")),
    }
}

// Only what differs from the defaults is written.
export function memberPreviewSearch(context: MemberPreviewContext): string {
    const search = new URLSearchParams()
    if (context.member !== null) search.set("member", context.member)
    if (context.characterId !== null) search.set("character_id", context.characterId)
    if (context.partyId !== null) search.set("party_id", context.partyId)
    if (context.view !== "known") search.set("view", context.view)
    if (context.query !== "") search.set("q", context.query)
    if (!context.includePublic) search.set("public", "0")
    if (context.cursor !== null) search.set("cursor", context.cursor)
    const text = search.toString()
    return text === "" ? "" : `?${text}`
}

export const memberPreviewPath = (campaignId: string): string =>
    `/app/${encodeURIComponent(campaignId)}/knowledge/member-preview`

export const memberPreviewClaimPath = (campaignId: string, knowledgeItemId: string): string =>
    `${memberPreviewPath(campaignId)}/${encodeURIComponent(knowledgeItemId)}`
