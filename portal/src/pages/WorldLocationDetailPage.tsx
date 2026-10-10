import { useWorldBackPath } from "../hooks/useWorldBackPath"
import { Link } from "react-router"
import { DetailPanel } from "../components/DetailPanel"
import { areaAuthoringPath, dungeonAuthoringPath } from "../api/dungeonAuthoring"
import { AuthoringEditLink } from "../components/AuthoringEditLink"
import { locationAuthoringPath } from "../api/locationAuthoring"
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

// Location detail (UI_STYLE_GUIDE.md §10.2). Uses the authorized breadcrumb
// names for containment rather than the raw parent_location_id — that field
// is never rendered.
export function WorldLocationDetailPage({
    campaignId,
    location,
}: WorldLocationDetailPageProps) {
    const worldBackPath = useWorldBackPath(campaignId)
    const headingRef = usePageArrival(true)
    const root = `/app/${encodeURIComponent(campaignId)}`
    const isDungeonType =
        location.location_type_code === "dungeon" || location.location_type_code === "dungeon_area"
    const editPath =
        location.location_type_code === "dungeon"
            ? `${root}/world/dungeon/${encodeURIComponent(location.location_id)}/edit`
            : location.location_type_code === "dungeon_area" && location.parent_location_id !== null
              ? `${root}/world/dungeon/${encodeURIComponent(location.parent_location_id)}/areas/${encodeURIComponent(location.location_id)}/edit`
              : `${root}/world/location/${encodeURIComponent(location.location_id)}/edit`
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
                noun={isDungeonType ? location.location_type_code.replace("_", " ") : "location"}
                viewPath={
                    location.location_type_code === "dungeon"
                        ? dungeonAuthoringPath(campaignId, location.location_id)
                        : location.location_type_code === "dungeon_area"
                          ? areaAuthoringPath(campaignId, location.location_id)
                          : locationAuthoringPath(campaignId, location.location_id)
                }
                editPath={editPath}
                detail={location}
            />

            {location.summary !== null && (
                <p className="world-detail__summary">{location.summary}</p>
            )}

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
                            {
                                key: "danger",
                                label: "Danger level",
                                value: location.danger_level ?? "Not recorded",
                            },
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

                <DetailPanel title="Current State">
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
                </DetailPanel>
            </div>
        </section>
    )
}
