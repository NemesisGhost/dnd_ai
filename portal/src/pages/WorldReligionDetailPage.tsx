import { Link } from "react-router"
import { religionAuthoringPath } from "../api/organizationAuthoring"
import { AuthoringEditLink } from "../components/AuthoringEditLink"
import { DetailPanel } from "../components/DetailPanel"
import { usePageArrival } from "../hooks/usePageArrival"
import { FactGrid } from "../components/FactGrid"
import type { ReligionDetail } from "../types/world"

interface WorldReligionDetailPageProps {
    campaignId: string
    religion: ReligionDetail
}

// Religion detail. serving_organization_ids carries no authorized display
// label in the current contract — deliberately never rendered as a raw
// UUID; the section is omitted rather than shown empty or with an id
// (UI_STYLE_GUIDE.md §10.2, §15 — see the Phase 13D backend contract
// limitation noted in this workstream's report).
export function WorldReligionDetailPage({
    campaignId,
    religion,
}: WorldReligionDetailPageProps) {
    const headingRef = usePageArrival(true)
    return (
        <section aria-labelledby="world-religion-heading">
            <p>
                <Link to={`/app/${encodeURIComponent(campaignId)}/world`}>
                    Back to World
                </Link>
            </p>

            <p className="world-detail__eyebrow">Religion</p>
            <h1 id="world-religion-heading" ref={headingRef} tabIndex={-1}>
                {religion.name}
            </h1>

            <AuthoringEditLink
                campaignId={campaignId}
                noun="religion"
                viewPath={religionAuthoringPath(campaignId, religion.religion_id)}
                editPath={`/app/${encodeURIComponent(campaignId)}/world/religion/${encodeURIComponent(religion.religion_id)}/edit`}
                detail={religion}
            />

            {religion.summary !== null && (
                <p className="world-detail__summary">{religion.summary}</p>
            )}

            <div className="world-detail__panel-grid">
                <DetailPanel title="Overview">
                    <FactGrid
                        items={[
                            {
                                key: "pantheon",
                                label: "Pantheon structure",
                                value: religion.pantheon_structure ?? "Not recorded",
                            },
                        ]}
                    />
                </DetailPanel>
            </div>
        </section>
    )
}
