import { Link } from "react-router"
import { DetailPanel } from "../components/DetailPanel"
import { FactGrid } from "../components/FactGrid"
import type { EventDetail } from "../types/world"
import { humanizeCode } from "../utils/humanize"

interface WorldEventDetailPageProps {
    campaignId: string
    event: EventDetail
}

// Event detail. participants[]/locations[] carry only ids and an optional
// role code with no authorized display label for the referenced entity —
// the contract does not let this page invent a name, so those sections are
// omitted entirely rather than shown with a raw UUID (UI_STYLE_GUIDE.md
// §10.2, §15 — see this workstream's backend contract limitation report).
// world_time_id and session_id are identifiers with no display label
// either and are also never rendered.
export function WorldEventDetailPage({
    campaignId,
    event,
}: WorldEventDetailPageProps) {
    return (
        <section aria-labelledby="world-event-heading">
            <p>
                <Link to={`/app/${encodeURIComponent(campaignId)}/world`}>
                    Back to World
                </Link>
            </p>

            <p className="world-detail__eyebrow">
                {humanizeCode(event.event_type_code)}
            </p>
            <h1 id="world-event-heading">{event.name}</h1>

            {event.summary !== null && (
                <p className="world-detail__summary">{event.summary}</p>
            )}

            <div className="world-detail__panel-grid">
                <DetailPanel title="Overview">
                    <FactGrid
                        items={[
                            {
                                key: "status",
                                label: "Status",
                                value: humanizeCode(event.event_status_code),
                            },
                            {
                                key: "details",
                                label: "Details",
                                value: event.details ?? "Not recorded",
                            },
                        ]}
                    />
                </DetailPanel>
            </div>
        </section>
    )
}
