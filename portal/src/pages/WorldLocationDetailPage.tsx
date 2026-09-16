import { Link } from "react-router"
import { DetailPanel } from "../components/DetailPanel"
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
    return (
        <section aria-labelledby="world-location-heading">
            <p>
                <Link to={`/app/${encodeURIComponent(campaignId)}/world`}>
                    Back to World
                </Link>
            </p>

            <p className="world-detail__eyebrow">
                {humanizeCode(location.location_type_code)}
            </p>
            <h1 id="world-location-heading">{location.name}</h1>

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
