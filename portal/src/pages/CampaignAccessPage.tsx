import { useState } from "react"
import { useParams } from "react-router"
import { AccessOverviewBoundary } from "../components/AccessOverviewBoundary"
import { AccessPage } from "./AccessPage"
import PlaceholderPage from "./PlaceholderPage"

interface RoleChangeAnnouncement {
    campaignId: string
    message: string
}

export function CampaignAccessPage() {
    const { campaignId } =
        useParams<{ campaignId: string }>()

    // Owned here, above AccessOverviewBoundary, so this live region
    // survives the overview's own transition to its loading state after a
    // role change succeeds. That transition (useChangeMembershipRole's
    // onSuccess calling the boundary's retry()) unmounts AccessPage and
    // MemberRoleEditor in the same commit that would otherwise announce
    // "Role updated." from the editor's own, now-unmounted status region
    // — a screen reader never gets the chance to observe it. Keeping this
    // paragraph mounted for the whole life of the page means its text
    // content change is an observable mutation on an already-watched
    // live region, regardless of what else unmounts alongside it.
    const [announcement, setAnnouncement] =
        useState<RoleChangeAnnouncement | null>(null)

    if (campaignId === undefined) {
        return (
            <PlaceholderPage
                title="Access unavailable"
                description="The requested access information is not available."
            />
        )
    }

    // A fresh, explicitly-typed binding: TypeScript's narrowing of the
    // destructured `campaignId` above does not reliably carry into the
    // nested closures below, even though it can never be undefined past
    // this point.
    const activeCampaignId: string = campaignId

    // Scoped to the active campaign: a stored announcement from a
    // previous campaign is never shown after navigating away, and no
    // effect-based reset is needed — the derived value is simply empty
    // the moment the route's campaignId no longer matches.
    const announcementMessage =
        announcement !== null &&
        announcement.campaignId === activeCampaignId
            ? announcement.message
            : ""

    function handleRoleChanged(retry: () => void): void {
        setAnnouncement({
            campaignId: activeCampaignId,
            message: "Role updated.",
        })
        // The authoritative refresh runs immediately — this announcement
        // exists to survive it, never to delay it.
        retry()
    }

    return (
        <>
            <p
                className="campaign-access-page__announcement"
                role="status"
                aria-live="polite"
            >
                {announcementMessage}
            </p>

            <AccessOverviewBoundary campaignId={activeCampaignId}>
                {(overview, retry) => (
                    <AccessPage
                        campaignId={activeCampaignId}
                        overview={overview}
                        onChanged={() =>
                            handleRoleChanged(retry)
                        }
                    />
                )}
            </AccessOverviewBoundary>
        </>
    )
}
