import type {
    ReactNode,
} from "react"
import {
    useKnowledgeItems,
} from "../hooks/useKnowledgeItems"
import type {
    KnowledgePage,
    KnowledgeView,
} from "../types/knowledge"

interface KnowledgeItemsBoundaryProps {
    campaignId: string
    view: KnowledgeView
    characterId: string | null
    partyId: string | null
    query: string
    knowledgeType: string | null
    cursor?: string | null
    children: (
        page: KnowledgePage,
        refreshing: boolean,
    ) => ReactNode
}

export function KnowledgeItemsBoundary({
    campaignId,
    view,
    characterId,
    partyId,
    query,
    knowledgeType,
    cursor = null,
    children,
}: KnowledgeItemsBoundaryProps) {
    const { state, retry } =
        useKnowledgeItems(
            campaignId,
            view,
            characterId,
            partyId,
            query,
            knowledgeType,
            cursor,
        )

    if (state.status === "loading") {
        return (
            <div
                role="region"
                aria-label="Knowledge results"
                aria-busy="true"
            >
                <h2>Loading knowledge</h2>
                <p>
                    Loading the latest authorized
                    knowledge.
                </p>
            </div>
        )
    }

    if (state.status === "unavailable") {
        return (
            <div
                role="region"
                aria-label="Knowledge results"
            >
                <h2>Knowledge unavailable</h2>
                <p>
                    The requested knowledge is not
                    available.
                </p>
            </div>
        )
    }

    if (state.status === "error") {
        return (
            <div
                role="region"
                aria-label="Knowledge results"
            >
                <h2>
                    Knowledge information unavailable
                </h2>

                <p>
                    The portal could not load the
                    knowledge information. Try again.
                </p>

                <button
                    type="button"
                    onClick={retry}
                >
                    Try again
                </button>
            </div>
        )
    }

    return (
        <>
            {children(
                state.page,
                state.status === "refreshing",
            )}
        </>
    )
}