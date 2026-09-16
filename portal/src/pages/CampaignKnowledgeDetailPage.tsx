import { useParams, useSearchParams } from "react-router"
import { KnowledgeDetailBoundary } from "../components/KnowledgeDetailBoundary"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { KnowledgeDetailPage } from "./KnowledgeDetailPage"
import PlaceholderPage from "./PlaceholderPage"

// Route-based Knowledge detail (UI_STYLE_GUIDE.md §11.2):
// /app/:campaignId/knowledge/:knowledgeItemId. The character perspective
// always comes from the globally selected character (same mechanism every
// other authorization-sensitive page uses), never from the URL. The party
// filter has no such global home, so it is carried in the URL's own
// `party_id` query parameter — the only addressable place that survives a
// direct refresh or bookmark (UI_DESIGN.md §5.6, §9).
export function CampaignKnowledgeDetailPage() {
    const { campaignId, knowledgeItemId } = useParams<{
        campaignId: string
        knowledgeItemId: string
    }>()

    const { getSelectedCharacterId } = usePerspective()
    const [searchParams] = useSearchParams()

    if (campaignId === undefined || knowledgeItemId === undefined) {
        return (
            <PlaceholderPage
                title="Knowledge unavailable"
                description="The requested knowledge is not available."
            />
        )
    }

    const characterId = getSelectedCharacterId(campaignId)
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
