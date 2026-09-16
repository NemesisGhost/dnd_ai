import type { ReactNode } from "react"
import { useKnowledgeDetail } from "../hooks/useKnowledgeDetail"
import type { KnowledgeDetail } from "../types/knowledge"
import PlaceholderPage from "../pages/PlaceholderPage"

interface KnowledgeDetailBoundaryProps {
    campaignId: string
    knowledgeItemId: string
    characterId: string | null
    partyId: string | null
    children: (item: KnowledgeDetail) => ReactNode
}

export function KnowledgeDetailBoundary({
    campaignId,
    knowledgeItemId,
    characterId,
    partyId,
    children,
}: KnowledgeDetailBoundaryProps) {
    const { state, retry } = useKnowledgeDetail(
        campaignId,
        knowledgeItemId,
        characterId,
        partyId,
    )

    if (state.status === "loading") {
        return (
            <PlaceholderPage
                title="Loading knowledge"
                description="Loading the latest authorized knowledge."
            />
        )
    }

    if (state.status === "unavailable") {
        return (
            <PlaceholderPage
                title="Knowledge unavailable"
                description="The requested knowledge is not available."
            />
        )
    }

    if (state.status === "error") {
        return (
            <section
                className="placeholder-page"
                aria-labelledby="knowledge-detail-error-heading"
            >
                <h1 id="knowledge-detail-error-heading">
                    Knowledge information unavailable
                </h1>

                <p>
                    The portal could not load the knowledge information.
                    Try again.
                </p>

                <button type="button" onClick={retry}>
                    Try again
                </button>
            </section>
        )
    }

    return <>{children(state.item)}</>
}
