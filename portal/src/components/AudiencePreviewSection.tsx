import { useContext } from "react"
import { useAccessOverview } from "../hooks/useAccessOverview"
import { SessionContext } from "../context/SessionContext"
import { canPreviewAudience } from "../utils/canPreviewAudience"
import { AudiencePreviewPanel } from "./AudiencePreviewPanel"
import type { ResourceOption } from "./ResourceTargetSelector"
import type { AudiencePreviewResourceType } from "../types/audiencePreview"

interface AudiencePreviewSectionProps {
    campaignId: string
    resourceType: AudiencePreviewResourceType
    /** Set on a detail page to lock the preview to the resource already on screen. */
    fixedResource?: ResourceOption
}

// Wraps AudiencePreviewPanel for the Quest/Knowledge collection and detail
// pages (Phase 13E-B manual-acceptance fix, item 3). Gates on the same
// access.manage capability CampaignAccessPage's own instance uses, checked
// entirely from the already-loaded session bootstrap -- a member without
// that capability never triggers the campaign-access-overview request
// this component needs for its member list.
export function AudiencePreviewSection({
    campaignId,
    resourceType,
    fixedResource,
}: AudiencePreviewSectionProps) {
    // Read the context directly rather than through useSession(): pages
    // that never needed session state before this control existed (most
    // Quest/Knowledge unit tests) don't wrap themselves in a
    // SessionContext.Provider, and an absent provider should simply mean
    // "cannot confirm GM authorization, so don't show anything" here, not
    // a hard error.
    const session = useContext(SessionContext)

    if (session === undefined || !canPreviewAudience(session.state, campaignId)) {
        return null
    }

    return (
        <AudiencePreviewSectionContent
            key={campaignId}
            campaignId={campaignId}
            resourceType={resourceType}
            fixedResource={fixedResource}
        />
    )
}

function AudiencePreviewSectionContent({
    campaignId,
    resourceType,
    fixedResource,
}: AudiencePreviewSectionProps) {
    const { state } = useAccessOverview(campaignId)

    if (state.status !== "success") {
        // Deliberately silent: this is a secondary, GM-only enhancement,
        // not this page's primary content, so a loading/error/unavailable
        // overview never blocks or disrupts the underlying quest/knowledge
        // page, and never shows a preview control backed by stale data.
        return null
    }

    return (
        <AudiencePreviewPanel
            campaignId={campaignId}
            members={state.overview.members.map((member) => ({
                campaign_membership_id: member.campaign_membership_id,
                display_name: member.display_name,
            }))}
            fixedResourceType={resourceType}
            fixedResource={fixedResource}
        />
    )
}
