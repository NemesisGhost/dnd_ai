import { useState } from "react"
import { useParams } from "react-router"
import { AccessTabNav } from "../components/AccessTabNav"
import { InvitationsSection } from "../components/InvitationsSection"
import PlaceholderPage from "./PlaceholderPage"

interface InvitationAnnouncement {
    campaignId: string
    message: string
}

interface IssuedInvitationToken {
    campaignId: string
    token: string
}

// Split out of CampaignAccessPage/AccessPage (Access/Invitations
// navigation redesign) so that opening /access never fetches or mutates
// invitations, and opening /access/invitations never fetches the
// role/relationship/grant access-overview the management page owns —
// the same rationale that already split /access/audit into its own
// route. A direct reload of this URL works the same as navigating to it
// from the Access submenu or the AccessTabNav tab above.
export function CampaignInvitationsPage() {
    const { campaignId } = useParams<{ campaignId: string }>()

    const [announcement, setAnnouncement] =
        useState<InvitationAnnouncement | null>(null)
    const [issuedInvitationToken, setIssuedInvitationToken] =
        useState<IssuedInvitationToken | null>(null)

    if (campaignId === undefined) {
        return (
            <PlaceholderPage
                title="Access unavailable"
                description="The requested access information is not available."
            />
        )
    }

    const activeCampaignId: string = campaignId

    const announcementMessage =
        announcement !== null &&
        announcement.campaignId === activeCampaignId
            ? announcement.message
            : ""

    const activeIssuedInvitationToken =
        issuedInvitationToken !== null &&
        issuedInvitationToken.campaignId === activeCampaignId
            ? issuedInvitationToken.token
            : null

    function handleChanged(message: string): void {
        setAnnouncement({
            campaignId: activeCampaignId,
            message,
        })
    }

    function handleMutationStart(): void {
        setAnnouncement(null)
    }

    function handleIssuedTokenChange(token: string | null): void {
        setIssuedInvitationToken(
            token === null
                ? null
                : {
                      campaignId: activeCampaignId,
                      token,
                  },
        )
    }

    return (
        <>
            <AccessTabNav campaignId={activeCampaignId} />

            <p
                className="campaign-access-page__announcement"
                role="status"
                aria-live="polite"
            >
                {announcementMessage}
            </p>

            <InvitationsSection
                campaignId={activeCampaignId}
                onChanged={handleChanged}
                onMutationStart={handleMutationStart}
                issuedToken={activeIssuedInvitationToken}
                onIssuedTokenChange={handleIssuedTokenChange}
            />
        </>
    )
}
