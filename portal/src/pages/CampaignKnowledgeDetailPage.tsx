import { useCallback, useEffect } from "react"
import { useLocation, useParams, useSearchParams } from "react-router"
import { KnowledgeDetailBoundary } from "../components/KnowledgeDetailBoundary"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { runPermissionLossCleanup } from "../hooks/navigationHolds"
import { KnowledgeClaimPage } from "./KnowledgeClaimPage"
import PlaceholderPage from "./PlaceholderPage"

// Route-based Knowledge claim page (UI_STYLE_GUIDE.md §11.2), now also where a claim is
// edited and where who knows it is managed:
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
    const [searchParams, setSearchParams] = useSearchParams()

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

    // A party the refreshed bootstrap no longer authorizes is dropped from the address (replacing
    // history, so Back cannot restore it); the record is then read again without it.
    // Permission loss, not a choice: it runs under the narrow exemption so it is never held behind the
    // claim page's "discard unsaved changes?" question, which a deliberate party change does ask.
    const locationKey = useLocation().key
    const dropRevokedParty = useCallback(
        (revokedPartyId: string) => {
            runPermissionLossCleanup(locationKey, () =>
                setSearchParams(
                    (current) => {
                        if (current.get("party_id") !== revokedPartyId) return current
                        const next = new URLSearchParams(current)
                        next.delete("party_id")
                        return next
                    },
                    { replace: true },
                ),
            )
        },
        [setSearchParams, locationKey],
    )

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
            onPartyRevoked={dropRevokedParty}
        >
            {(item, refresh) => (
                <KnowledgeClaimPage
                    campaignId={campaignId}
                    knowledgeItemId={knowledgeItemId}
                    item={item}
                    characterId={characterId}
                    partyId={partyId}
                    refreshDetail={refresh}
                />
            )}
        </KnowledgeDetailBoundary>
    )
}
