import { useState } from "react"
import { useParams } from "react-router"
import { AccessOverviewBoundary } from "../components/AccessOverviewBoundary"
import { AccessPage } from "./AccessPage"
import PlaceholderPage from "./PlaceholderPage"

interface RoleChangeAnnouncement {
    campaignId: string
    message: string
}

// Every role-mutation control (change/add/revoke) reports its own outcome
// text through this one path (Phase 13E-B checkpoint 2) — a single
// persistent announcement mechanism rather than three parallel ones, so
// "starting another operation clears or supersedes stale success
// messaging deliberately" and "does not retain stale Access records merely
// to keep an announcement visible" both hold identically regardless of
// which control produced the message.

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
    const [issuedInvitationToken, setIssuedInvitationToken] = useState<string | null>(null)

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

    function handleRoleChanged(
        retry: () => void,
        message: string,
    ): void {
        // Starting (or completing) another operation always replaces
        // whatever announcement was showing — a fresh call here, whatever
        // its text, is never merged with or appended to a stale one.
        setAnnouncement({
            campaignId: activeCampaignId,
            message,
        })
        // The authoritative refresh runs immediately — this announcement
        // exists to survive it, never to delay it.
        retry()
    }

    // Called the moment a new Add/Change/Remove mutation is submitted
    // (before the request is even sent), never when the overview's own
    // success-triggered refetch begins on its own. Without this, a stale
    // "Role added."/"Role updated."/"Role removed." from a previous,
    // already-completed operation would keep sitting in this persistent
    // region — indistinguishable from a fresh success — right alongside a
    // different row's own current pending/error state for the operation
    // the user is now watching.
    function handleMutationStart(): void {
        setAnnouncement(null)
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
                        onChanged={(message) =>
                            handleRoleChanged(retry, message)
                        }
                        onMutationStart={handleMutationStart}
                        issuedInvitationToken={issuedInvitationToken}
                        onIssuedInvitationTokenChange={setIssuedInvitationToken}
                    />
                )}
            </AccessOverviewBoundary>
        </>
    )
}
