import type { ReactNode } from "react"
import { useWorldEntities } from "../hooks/useWorldEntities"
import type {
    WorldCategory,
    WorldEntityPage,
} from "../types/world"

interface WorldEntitiesBoundaryProps {
    campaignId: string
    category: WorldCategory | null
    query: string
    cursor?: string | null
    children: (
        page: WorldEntityPage,
        refreshing: boolean,
    ) => ReactNode
}

export function WorldEntitiesBoundary({
    campaignId,
    category,
    query,
    cursor = null,
    children,
}: WorldEntitiesBoundaryProps) {
    const { state, retry } = useWorldEntities(
        campaignId,
        category,
        query,
        cursor,
    )

    // Rendered inside WorldPage, which already carries the page's <h1>, so
    // every branch here is result-region markup (a labelled region with at
    // most an <h2>) rather than a page-level placeholder.

    if (state.status === "loading") {
        return (
            <div
                role="region"
                aria-label="World entities results"
                aria-busy="true"
            >
                <h2>Loading world</h2>
                <p>
                    Loading the latest authorized world information.
                </p>
            </div>
        )
    }

    if (state.status === "unavailable") {
        return (
            <div
                role="region"
                aria-label="World entities results"
            >
                <h2>World unavailable</h2>
                <p>
                    The requested world information is not available.
                </p>
            </div>
        )
    }

    if (state.status === "error") {
        return (
            <div
                role="region"
                aria-label="World entities results"
            >
                <h2>World information unavailable</h2>

                <p>
                    The portal could not load the world information.
                    Try again.
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
