import type { ReactNode } from "react"
import { useWorldEntities } from "../hooks/useWorldEntities"
import PlaceholderPage from "../pages/PlaceholderPage"
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

    if (state.status === "loading") {
        return (
            <PlaceholderPage
                title="Loading world"
                description="Loading the latest authorized world information."
            />
        )
    }

    if (state.status === "unavailable") {
        return (
            <PlaceholderPage
                title="World unavailable"
                description="The requested world information is not available."
            />
        )
    }

    if (state.status === "error") {
        return (
            <section
                className="placeholder-page"
                aria-labelledby="world-error-heading"
            >
                <h1 id="world-error-heading">
                    World information unavailable
                </h1>

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
            </section>
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