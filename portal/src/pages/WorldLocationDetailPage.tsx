import { useWorldBackPath } from "../hooks/useWorldBackPath"
import { Link } from "react-router"
import { DetailPanel, PanelFrame } from "../components/DetailPanel"
import { AuthoringEditLink } from "../components/AuthoringEditLink"
import { locationEditPath, locationNoun, locationViewPath } from "../components/world/placePaths"
import { usePageArrival } from "../hooks/usePageArrival"
import { FactGrid } from "../components/FactGrid"
import type { LocationDetail } from "../types/world"
import { humanizeCode } from "../utils/humanize"

interface WorldLocationDetailPageProps {
    campaignId: string
    location: LocationDetail
}

function describeBoolean(value: boolean | null): string {
    if (value === null) {
        return "Not recorded"
    }
    return value ? "Yes" : "No"
}

// The reading panels of a place: overview, containment and current state. Uses the authorized
// breadcrumb names for containment rather than the raw parent_location_id — that field is never
// rendered. `omitCurrentState` is for a host that shows the current state itself.
export function LocationPanels({
    location,
    omitCurrentState = false,
}: {
    location: LocationDetail
    omitCurrentState?: boolean
}) {
    return (
        <div className="world-detail__panel-grid">
            <DetailPanel title="Overview">
                <FactGrid
                    items={[
                        {
                            key: "type",
                            label: "Type",
                            value: humanizeCode(location.location_type_code),
                        },
                        {
                            key: "population",
                            label: "Population",
                            value: location.population ?? "Not recorded",
                        },
                        {
                            key: "building-use",
                            label: "Building use",
                            value:
                                location.building_use !== null
                                    ? humanizeCode(location.building_use)
                                    : "Not recorded",
                        },
                        // Editors only: the server sends null to everyone else, so "Not recorded"
                        // would wrongly tell a player the place has no rating.
                        ...(location.danger_level !== null
                            ? [
                                  {
                                      key: "danger",
                                      label: "Danger level",
                                      value: location.danger_level,
                                  },
                              ]
                            : []),
                    ]}
                />
            </DetailPanel>

            <DetailPanel
                title="Containment"
                isEmpty={location.breadcrumbs.length === 0}
                emptyState={<p>No containment recorded.</p>}
            >
                <ol className="world-detail__breadcrumbs">
                    {location.breadcrumbs.map((crumb) => (
                        <li key={crumb.location_id}>
                            {crumb.name} (
                            {humanizeCode(crumb.location_type_code)})
                        </li>
                    ))}
                </ol>
            </DetailPanel>

            {omitCurrentState ? null : <LocationCurrentState location={location} />}
        </div>
    )
}

// What is currently true of the place in the campaign's timeline.
export function LocationCurrentState({
    location,
    embedded = false,
}: {
    location: LocationDetail
    // A staged section already supplies the surface and the heading: render the content only.
    embedded?: boolean
}) {
    return (
        <PanelFrame embedded={embedded} title="Current State">
            <FactGrid
                items={[
                    {
                        key: "searched",
                        label: "Searched",
                        value: describeBoolean(location.is_searched),
                    },
                    {
                        key: "destroyed",
                        label: "Destroyed",
                        value: describeBoolean(location.is_destroyed),
                    },
                    {
                        key: "alarm",
                        label: "Alarm level",
                        value: location.alarm_level ?? "Not recorded",
                    },
                    {
                        key: "condition",
                        label: "Condition notes",
                        value: location.condition_notes ?? "Not recorded",
                    },
                ]}
            />
        </PanelFrame>
    )
}

// Location detail (UI_STYLE_GUIDE.md §10.2). The reader everyone sees; editors get the workspace
// instead (components/world/WorldRecordWorkspace), which reuses these panels.
export function WorldLocationDetailPage({
    campaignId,
    location,
}: WorldLocationDetailPageProps) {
    const worldBackPath = useWorldBackPath(campaignId)
    const headingRef = usePageArrival(true)
    return (
        <section aria-labelledby="world-location-heading">
            <p>
                <Link to={worldBackPath}>
                    Back to World
                </Link>
            </p>

            <p className="world-detail__eyebrow">
                {humanizeCode(location.location_type_code)}
            </p>
            <h1 id="world-location-heading" ref={headingRef} tabIndex={-1}>
                {location.name}
            </h1>

            <AuthoringEditLink
                campaignId={campaignId}
                noun={locationNoun(location)}
                viewPath={locationViewPath(campaignId, location)}
                editPath={locationEditPath(campaignId, location)}
                detail={location}
            />

            {location.summary !== null && (
                <p className="world-detail__summary">{location.summary}</p>
            )}

            <LocationPanels location={location} />
        </section>
    )
}
