import { useEffect } from "react"
import { useParams, useSearchParams } from "react-router"
import { KnowledgeDetailBoundary } from "../components/KnowledgeDetailBoundary"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { KnowledgeDetailPage } from "./KnowledgeDetailPage"
import PlaceholderPage from "./PlaceholderPage"

// Route-based Knowledge detail (UI_STYLE_GUIDE.md §11.2):
// /app/:campaignId/knowledge/:knowledgeItemId. The character perspective
// is carried in the URL's own `character_id` query parameter when present
// — the only addressable place that survives a direct refresh or bookmark
// (UI_DESIGN.md §5.6, §9) — and falls back to the globally selected
// character otherwise, for backward compatibility with links that predate
// this parameter. The party filter works the same way via `party_id`. The
// server remains authoritative for both: neither parameter is treated as a
// local authorization grant, and an unauthorized or invalid value still
// produces the existing non-disclosing "unavailable" result.
export function CampaignKnowledgeDetailPage() {
    const { campaignId, knowledgeItemId } = useParams<{
        campaignId: string
        knowledgeItemId: string
    }>()

    const { getSelectedCharacterId, syncCharacterFromUrl } = usePerspective()
    const [searchParams] = useSearchParams()

    const urlCharacterId = searchParams.get("character_id")
    const selectedCharacterId =
        campaignId === undefined ? null : getSelectedCharacterId(campaignId)

    // Reconciles the context panel's visible perspective with the
    // URL-provided character so a direct refresh never shows one character
    // while requesting as another. Only runs when they actually disagree,
    // and syncCharacterFromUrl itself no-ops for an id outside the current
    // bootstrap's authorized character_perspectives — so this never grants
    // access on its own and never loops (the effect's own dependencies
    // stop changing once they agree, or stay unchanged when it no-ops).
    useEffect(() => {
        if (
            campaignId === undefined ||
            urlCharacterId === null ||
            urlCharacterId === selectedCharacterId
        ) {
            return
        }

        syncCharacterFromUrl?.(campaignId, urlCharacterId)
    }, [campaignId, urlCharacterId, selectedCharacterId, syncCharacterFromUrl])

    if (campaignId === undefined || knowledgeItemId === undefined) {
        return (
            <PlaceholderPage
                title="Knowledge unavailable"
                description="The requested knowledge is not available."
            />
        )
    }

    const characterId = urlCharacterId ?? selectedCharacterId
    const partyId = searchParams.get("party_id")

    return (
        <KnowledgeDetailBoundary
            campaignId={campaignId}
            knowledgeItemId={knowledgeItemId}
            characterId={characterId}
            partyId={partyId}
        >
            {(item) => (
                <KnowledgeDetailPage campaignId={campaignId} item={item} />
            )}
        </KnowledgeDetailBoundary>
    )
}
