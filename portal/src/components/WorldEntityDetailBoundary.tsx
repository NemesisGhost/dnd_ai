import type { ReactNode } from "react"
import { EntityLifecyclePanel } from "./EntityLifecyclePanel"
import { useWorldDetail } from "../hooks/useWorldDetail"
import { useBreadcrumbLabel } from "../navigation/BreadcrumbLabelContext"
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
    // The record's name for the breadcrumbs of the pages opened from it: the World category it is
    // under and how to read its name from the detail. Published from this page's own read, under
    // the authority in force when that read started; a refused answer drops it.
    label?: { category: string; name: (detail: T) => string }
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
    label,
    children,
}: WorldEntityDetailBoundaryProps<T>) {
    const { state, retry, authority } = useWorldDetail(
        fetchDetail,
        campaignId,
        entityId,
    )
    useBreadcrumbLabel({
        route: "world.record",
        params: { campaignId, category: label?.category ?? "", entityId },
        name: label !== undefined && state.status === "success" ? label.name(state.detail) : undefined,
        denied: label !== undefined && state.status === "unavailable",
        authority: label === undefined ? null : authority,
    })

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
        <div className="world-detail__layout">
            {children(state.detail)}
            {lifecycle ? (
                <EntityLifecyclePanel
                    campaignId={campaignId}
                    entityId={entityId}
                    category={resourceLabel}
                    onChanged={retry}
                />
            ) : null}
        </div>
    )
}

function capitalize(value: string): string {
    return value.length === 0
        ? value
        : value.charAt(0).toUpperCase() + value.slice(1)
}
