import { Link } from "react-router"
import { LocationChildren } from "../components/world/LocationChildren"
import { worldRecordPath } from "../components/world/worldPaths"
import { useWorldReturnState } from "../hooks/useWorldBackPath"
import { WorldRecordBack } from "../components/world/WorldRecordBack"
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
    campaignId,
    location,
    linkState,
    omitCurrentState = false,
}: {
    campaignId: string
    location: LocationDetail
    // The state the ancestors' pages are opened with: the page's own task, as its other links carry it.
    linkState?: object
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
                <ol className="world-detail__breadcrumbs" aria-label="Location path">
                    {location.breadcrumbs.map((crumb) => (
                        <li key={crumb.location_id}>
                            <Link to={worldRecordPath(campaignId, "location", crumb.location_id)} state={linkState}>
                                {crumb.name} ({humanizeCode(crumb.location_type_code)})
                            </Link>
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

// Location detail (docs/reference/portal-style.md §10.2). The reader everyone sees; editors get the workspace
// instead (components/world/WorldRecordWorkspace), which reuses these panels.
export function WorldLocationDetailPage({
    campaignId,
    location,
}: WorldLocationDetailPageProps) {
    const headingRef = usePageArrival(true)
    const returnState = useWorldReturnState()
    return (
        <section aria-labelledby="world-location-heading">
            <WorldRecordBack campaignId={campaignId} current={location.name} />

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

            <LocationPanels campaignId={campaignId} location={location} linkState={returnState} />
            {location.location_type_code !== "dungeon_area" ? (
                <LocationChildren
                    campaignId={campaignId}
                    location={location}
                    includeHidden={false}
                    linkState={returnState}
                />
            ) : null}
        </section>
    )
}
