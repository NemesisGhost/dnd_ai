import { useWorldBackPath, useWorldReturnState } from "../hooks/useWorldBackPath"
import { Link } from "react-router"
import { organizationAuthoringPath } from "../api/organizationAuthoring"
import { AuthoringEditLink } from "../components/AuthoringEditLink"
import { DetailPanel } from "../components/DetailPanel"
import { FactGrid } from "../components/FactGrid"
import { usePageArrival } from "../hooks/usePageArrival"
import type { OrganizationDetail } from "../types/world"
import { humanizeCode } from "../utils/humanize"

interface WorldOrganizationDetailPageProps {
    campaignId: string
    organization: OrganizationDetail
}

// Organization detail (UI_STYLE_GUIDE.md §10.2). Audience-safe: the server
// omits the GM-only notes, and a parent, headquarters, or religion it names is
// present only if the caller may see it. Related records are shown by name and
// linked, never by identifier.
export function WorldOrganizationDetailPage({
    campaignId,
    organization,
}: WorldOrganizationDetailPageProps) {
    const worldBackPath = useWorldBackPath(campaignId)
    const worldReturnState = useWorldReturnState()
    const headingRef = usePageArrival(true)
    const base = `/app/${encodeURIComponent(campaignId)}/world`
    return (
        <section aria-labelledby="world-organization-heading">
            <p>
                <Link to={worldBackPath}>Back to World</Link>
            </p>

            <p className="world-detail__eyebrow">{humanizeCode(organization.kind_code)}</p>
            <h1 id="world-organization-heading" ref={headingRef} tabIndex={-1}>
                {organization.name}
            </h1>

            <AuthoringEditLink
                campaignId={campaignId}
                noun="organization"
                viewPath={organizationAuthoringPath(campaignId, organization.organization_id)}
                editPath={`${base}/organization/${encodeURIComponent(organization.organization_id)}/edit`}
                detail={organization}
            />

            {organization.summary !== null && (
                <p className="world-detail__summary">{organization.summary}</p>
            )}

            <div className="world-detail__panel-grid">
                <DetailPanel title="Overview">
                    <FactGrid
                        items={[
                            {
                                key: "type",
                                label: "Type",
                                value: humanizeCode(organization.organization_type_code),
                            },
                            {
                                key: "status",
                                label: "Current status",
                                value:
                                    organization.status_code !== null
                                        ? humanizeCode(organization.status_code)
                                        : "Not recorded",
                            },
                        ]}
                    />
                </DetailPanel>

                <DetailPanel
                    title="Description"
                    isEmpty={organization.public_description === null}
                    emptyState={<p>No public description recorded.</p>}
                >
                    <p>{organization.public_description}</p>
                </DetailPanel>

                <DetailPanel
                    title="Structure"
                    isEmpty={
                        organization.parent === null &&
                        organization.headquarters === null &&
                        organization.religion === null
                    }
                    emptyState={<p>No related records to show.</p>}
                >
                    <ul className="world-detail__links">
                        {organization.parent !== null && (
                            <li>
                                Part of{" "}
                                <Link state={worldReturnState} to={`${base}/organization/${encodeURIComponent(organization.parent.entity_id)}`}>
                                    {organization.parent.name}
                                </Link>
                            </li>
                        )}
                        {organization.headquarters !== null && (
                            <li>
                                Headquarters{" "}
                                <Link state={worldReturnState} to={`${base}/location/${encodeURIComponent(organization.headquarters.entity_id)}`}>
                                    {organization.headquarters.name}
                                </Link>
                            </li>
                        )}
                        {organization.religion !== null && (
                            <li>
                                Serves{" "}
                                <Link state={worldReturnState} to={`${base}/religion/${encodeURIComponent(organization.religion.entity_id)}`}>
                                    {organization.religion.name}
                                </Link>
                            </li>
                        )}
                    </ul>
                </DetailPanel>
            </div>
        </section>
    )
}
