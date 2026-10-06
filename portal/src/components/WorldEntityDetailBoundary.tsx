import type { ReactNode } from "react"
import { EntityLifecyclePanel } from "./EntityLifecyclePanel"
import { useWorldDetail } from "../hooks/useWorldDetail"
import PlaceholderPage from "../pages/PlaceholderPage"

interface WorldEntityDetailBoundaryProps<T> {
    campaignId: string
    entityId: string
    fetchDetail: (
        campaignId: string,
        entityId: string,
        signal?: AbortSignal,
    ) => Promise<T>
    /** Lowercase noun used in loading/unavailable copy, e.g. "location". */
    resourceLabel: string
    // False when the page renders its own lifecycle panel (an item, whose operations panel
    // refreshes with it).
    lifecycle?: boolean
    children: (detail: T) => ReactNode
}

// Shared loading/unavailable/error boundary for every World detail category
// with a uniform (campaignId, entityId) => Promise<T> contract. Presentation
// of the authorized fields stays entirely in the domain-specific page
// component received as `children`.
export function WorldEntityDetailBoundary<T>({
    campaignId,
    entityId,
    fetchDetail,
    resourceLabel,
    lifecycle = true,
    children,
}: WorldEntityDetailBoundaryProps<T>) {
    const { state, retry } = useWorldDetail(
        fetchDetail,
        campaignId,
        entityId,
    )

    if (state.status === "loading") {
        return (
            <PlaceholderPage
                title={`Loading ${resourceLabel}`}
                description={`Loading the latest authorized ${resourceLabel} information.`}
            />
        )
    }

    if (state.status === "unavailable") {
        return (
            <PlaceholderPage
                title={`${capitalize(resourceLabel)} unavailable`}
                description={`The requested ${resourceLabel} information is not available.`}
            />
        )
    }

    if (state.status === "error") {
        return (
            <section
                className="placeholder-page"
                aria-labelledby="world-detail-error-heading"
            >
                <h1 id="world-detail-error-heading">
                    {capitalize(resourceLabel)} information unavailable
                </h1>

                <p>
                    The portal could not load the {resourceLabel} information.
                    Try again.
                </p>

                <button type="button" onClick={retry}>
                    Try again
                </button>
            </section>
        )
    }

    return (
        <>
            {children(state.detail)}
            {lifecycle ? (
                <EntityLifecyclePanel
                    campaignId={campaignId}
                    entityId={entityId}
                    category={resourceLabel}
                    onChanged={retry}
                />
            ) : null}
        </>
    )
}

function capitalize(value: string): string {
    return value.length === 0
        ? value
        : value.charAt(0).toUpperCase() + value.slice(1)
}
