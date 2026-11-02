import {
    useEffect,
} from "react"
import type {
    ReactNode,
} from "react"
import {
    useKnowledgeItems,
} from "../hooks/useKnowledgeItems"
import type {
    KnowledgeLifecycle,
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
    includePublic?: boolean
    lifecycle?: KnowledgeLifecycle
    /** Called when the server refuses a non-active lifecycle for this caller. */
    onLifecycleRejected?: () => void
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
    includePublic = true,
    lifecycle = "active",
    onLifecycleRejected,
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
            includePublic,
            lifecycle,
        )

    const lifecycleRejected =
        state.status === "lifecycle_rejected"

    useEffect(() => {
        if (lifecycleRejected) {
            onLifecycleRejected?.()
        }
    }, [lifecycleRejected, onLifecycleRejected])

    if (
        state.status === "loading" ||
        state.status === "lifecycle_rejected"
    ) {
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