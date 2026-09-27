import { useParams } from "react-router"
import { AccessOverviewBoundary } from "../components/AccessOverviewBoundary"
import { AccessTabNav } from "../components/AccessTabNav"
import { AuditHistory } from "../components/AuditHistory"
import PlaceholderPage from "./PlaceholderPage"

// The audit-history route, split out of CampaignAccessPage (Phase 13E-B
// manual-acceptance fix) so that opening /access never fetches audit
// history, and opening /access/audit never fetches the role/relationship/
// grant mutation endpoints the management page owns. A direct reload of
// this URL works the same as navigating to it from the tab above, since
// both go through this same route.
export function CampaignAccessAuditPage() {
    const { campaignId } = useParams<{ campaignId: string }>()

    if (campaignId === undefined) {
        return (
            <PlaceholderPage
                title="Access unavailable"
                description="The requested access information is not available."
            />
        )
    }

    const activeCampaignId: string = campaignId

    return (
        <>
            <AccessTabNav campaignId={activeCampaignId} />

            <AccessOverviewBoundary campaignId={activeCampaignId}>
                {(overview) => (
                    <AuditHistory
                        campaignId={activeCampaignId}
                        actors={overview.members.map((member) => ({
                            user_id: member.user_id,
                            display_name: member.display_name,
                        }))}
                    />
                )}
            </AccessOverviewBoundary>
        </>
    )
}
