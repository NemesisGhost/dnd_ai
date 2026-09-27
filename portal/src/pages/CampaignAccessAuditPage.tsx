import { useParams } from "react-router"
import { AccessTabNav } from "../components/AccessTabNav"
import { AuditHistory } from "../components/AuditHistory"
import { useAuditActors } from "../hooks/useAuditActors"
import PlaceholderPage from "./PlaceholderPage"

// The audit-history route, split out of CampaignAccessPage (Phase 13E-B
// manual-acceptance fix) so that opening /access never fetches audit
// history, and opening /access/audit never fetches the role/relationship/
// grant mutation endpoints the management page owns. A direct reload of
// this URL works the same as navigating to it from the tab above, since
// both go through this same route.
//
// Audit-actor-contract fix: this page no longer depends on
// AccessOverviewBoundary/the complete `GET .../access-overview` response
// merely to populate the actor filter — `useAuditActors` fetches only the
// bounded, identically-authorized actor facet `GET .../audit-history/
// actors` returns. `AuditHistory` itself always renders regardless of
// that facet's own status (loading/unavailable/error all fall back to its
// existing `actors = []` default, which simply omits the actor filter) —
// the actor list is a secondary enhancement, never a gate on the
// audit-history list this route exists to show.
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

    return <CampaignAccessAuditContent campaignId={activeCampaignId} />
}

function CampaignAccessAuditContent({ campaignId }: { campaignId: string }) {
    const { state } = useAuditActors(campaignId)
    const actors = state.status === "success" ? state.actors : []

    return (
        <>
            <AccessTabNav campaignId={campaignId} />
            <AuditHistory campaignId={campaignId} actors={actors} />
        </>
    )
}
