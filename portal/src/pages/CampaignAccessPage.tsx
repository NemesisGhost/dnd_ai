import { useEffect, useRef, useState } from "react"
import { useParams, useSearchParams } from "react-router"
import { AccessOverviewBoundary } from "../components/AccessOverviewBoundary"
import { AccessTabNav } from "../components/AccessTabNav"
import { AudiencePreviewPanel } from "../components/AudiencePreviewPanel"
import { useSession } from "../context/SessionContext"
import { useAccessDisclosure } from "../hooks/useAccessDisclosure"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import type { AccessDisclosure } from "../hooks/useAccessDisclosure"
import type { WriteNotice } from "../types/accessWrite"
import { canPreviewAudience as canPreviewAudienceFor } from "../utils/canPreviewAudience"
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

// Rendered only while the overview is loaded, so it mounts exactly when a read has succeeded:
//   - an open card or explanation whose member is not in this answer is forgotten, so it cannot
//     reappear if the member does later;
//   - a pending "Refresh access" is confirmed (announced, focus returned) only now.
interface RefreshIntent {
    campaignId: string
    membershipId: string
    // Which refresh this intent belongs to (see refreshEpisode).
    episode: number
}

// A character-denial write confirmed and not yet followed by a successful overview read: whose grants
// heading takes focus if the re-read displaced it (D-5).
interface FocusIntent {
    campaignId: string
    ownerId: string
    episode: number
}

function OverviewSettled({
    memberIds,
    disclosure,
    refresh,
    onRefreshSettled,
    focus,
    onFocusSettled,
}: {
    memberIds: string[]
    disclosure: AccessDisclosure
    refresh: RefreshIntent | null
    onRefreshSettled: (refresh: RefreshIntent) => void
    focus: FocusIntent | null
    onFocusSettled: (focus: FocusIntent) => void
}) {
    const key = memberIds.join("|")
    useEffect(() => {
        disclosure.prune(new Set(key === "" ? [] : key.split("|")))
        // eslint-disable-next-line react-hooks/exhaustive-deps -- `disclosure.prune` is stable per campaign.
    }, [key])
    useEffect(() => {
        if (refresh !== null) onRefreshSettled(refresh)
        if (focus !== null) onFocusSettled(focus)
        // Only on mount: a read that succeeded is what confirms a refresh.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])
    return null
}

export function CampaignAccessPage() {
    const { campaignId } =
        useParams<{ campaignId: string }>()

    const { state: sessionState } = useSession()
    // `?character=<id>` (a player character's "Link a player" link) starts the
    // relationship control on that character.
    const [searchParams] = useSearchParams()
    const preselectCharacterId = searchParams.get("character")

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
    const announcementRef = useRef<HTMLParagraphElement | null>(null)
    // Which member cards and explanations are open, by membership id, held here (above the boundary)
    // so they survive the overview's reload. Ids only: no access data is held outside the boundary.
    const disclosure = useAccessDisclosure(campaignId ?? "")
    // A "Refresh access" asked for and not yet answered by a successful overview read: the member
    // whose control asked, for returning focus once the list is back.
    const [pendingRefresh, setPendingRefresh] =
        useState<RefreshIntent | null>(null)
    // Counts refreshes asked for on this page. A completion acts only if it still belongs to the latest.
    const refreshEpisode = useRef(0)
    // The same for a confirmed character-denial write whose grants heading should take focus (D-5).
    const [pendingFocus, setPendingFocus] = useState<FocusIntent | null>(null)
    const focusEpisode = useRef(0)

    // The mounted Access content is bound to what the applied session says THIS campaign grants: the
    // existing capability resolver (the bootstrap's per-campaign capabilities), read on every render. A
    // session read that is applied in place (a write the caller could not be affected by, O-5) does not
    // remount this page, so the overview must not be allowed to outlive the capability that authorizes it.
    // Without `access.manage` nothing below is mounted: the overview, members, sources, explanations and
    // the hooks holding their responses are gone (a response still in flight is aborted with them and
    // cannot publish), and no explanation is read. The ids held here are dropped too, so a capability that
    // comes back starts from a fresh overview read with every card and explanation closed.
    const canManageAccess = useCampaignCapability(campaignId, "access.manage")
    const { prune } = disclosure
    useEffect(() => {
        if (!canManageAccess) {
            prune(new Set())
            // A refresh asked for before the loss no longer belongs to anything: its completion is ignored.
            refreshEpisode.current += 1
            focusEpisode.current += 1
        }
    }, [canManageAccess, prune])

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

    const canPreviewAudience = canPreviewAudienceFor(sessionState, activeCampaignId)

    function handleRoleChanged(
        retry: () => void,
        message: string,
        notice?: WriteNotice,
    ): void {
        // Starting (or completing) another operation always replaces
        // whatever announcement was showing — a fresh call here, whatever
        // its text, is never merged with or appended to a stale one.
        // A mutation supersedes a refresh that has not been answered: its completion must not act.
        setPendingRefresh(null)
        focusEpisode.current += 1
        setPendingFocus(
            notice?.focusGrantsOf === undefined
                ? null
                : {
                      campaignId: activeCampaignId,
                      ownerId: notice.focusGrantsOf,
                      episode: focusEpisode.current,
                  },
        )
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
        setPendingRefresh(null)
        focusEpisode.current += 1
        setPendingFocus(null)
        setAnnouncement(null)
    }

    // "Refresh access" reloads the member list and, because the list unmounts every explanation while
    // it loads, every open explanation with it. Nothing is announced yet: "refreshed" is said only
    // once the list has actually been read again (handleRefreshSettled), never for a failed read.
    function handleRefreshAccess(retry: () => void, membershipId: string): void {
        setAnnouncement(null)
        refreshEpisode.current += 1
        setPendingRefresh({ campaignId: activeCampaignId, membershipId, episode: refreshEpisode.current })
        retry()
    }

    function handleRefreshSettled(refresh: RefreshIntent): void {
        // A completion belonging to an older refresh, or to another campaign, does nothing.
        if (refresh.episode !== refreshEpisode.current || refresh.campaignId !== activeCampaignId) return
        setPendingRefresh(null)
        setAnnouncement({ campaignId: activeCampaignId, message: "Access list refreshed." })
        // The control that asked was unmounted by the reload, which displaces focus to the page body.
        // Return it only if it is still displaced: a manager who has since moved to another control
        // (the tab links stay mounted while the list loads) keeps that focus.
        const active = document.activeElement
        if (active !== null && active !== document.body && active.isConnected) return
        // The same member's explanation toggle, or the status line when that member is gone.
        const toggle = Array.from(document.querySelectorAll<HTMLElement>("[data-explain-toggle]")).find(
            (element) => element.dataset.explainToggle === refresh.membershipId,
        )
        ;(toggle ?? announcementRef.current)?.focus()
    }

    // Called once the list has been read again after a confirmed character-denial write. The intent is always
    // consumed; it acts only if it is still the latest and focus was displaced to the page body by the re-read
    // (a manager who has moved to another control keeps that focus). Then the same card's grants heading, or the
    // persistent status line when that card is gone.
    function handleFocusSettled(intent: FocusIntent): void {
        setPendingFocus(null)
        if (intent.episode !== focusEpisode.current || intent.campaignId !== activeCampaignId) return
        const active = document.activeElement
        if (active !== null && active !== document.body && active.isConnected) return
        const heading = Array.from(document.querySelectorAll<HTMLElement>("[data-grants-heading]")).find(
            (element) => element.dataset.grantsHeading === intent.ownerId,
        )
        ;(heading ?? announcementRef.current)?.focus()
    }

    const focusForThisCampaign =
        pendingFocus !== null && pendingFocus.campaignId === activeCampaignId ? pendingFocus : null

    const refreshForThisCampaign =
        pendingRefresh !== null && pendingRefresh.campaignId === activeCampaignId ? pendingRefresh : null

    return (
        <>
            <AccessTabNav campaignId={activeCampaignId} />

            <p
                className="campaign-access-page__announcement"
                role="status"
                aria-live="polite"
                ref={announcementRef}
                tabIndex={-1}
            >
                {announcementMessage}
            </p>

            {!canManageAccess ? (
                <PlaceholderPage
                    title="Access unavailable"
                    description="The requested access information is not available."
                />
            ) : (
            <AccessOverviewBoundary campaignId={activeCampaignId}>
                {(overview, retry) => (
                    <>
                        <OverviewSettled
                            memberIds={overview.members.map((member) => member.campaign_membership_id)}
                            disclosure={disclosure}
                            refresh={refreshForThisCampaign}
                            onRefreshSettled={handleRefreshSettled}
                            focus={focusForThisCampaign}
                            onFocusSettled={handleFocusSettled}
                        />
                        <AccessPage
                            campaignId={activeCampaignId}
                            overview={overview}
                            preselectCharacterId={preselectCharacterId}
                            onChanged={(message, notice) =>
                                handleRoleChanged(retry, message, notice)
                            }
                            onMutationStart={handleMutationStart}
                            disclosure={disclosure}
                            onRefreshAccess={(membershipId) =>
                                handleRefreshAccess(retry, membershipId)
                            }
                        />
                        {canPreviewAudience && (
                            <AudiencePreviewPanel
                                key={activeCampaignId}
                                campaignId={activeCampaignId}
                                members={overview.members.map((member) => ({
                                    campaign_membership_id: member.campaign_membership_id,
                                    display_name: member.display_name,
                                }))}
                            />
                        )}
                    </>
                )}
            </AccessOverviewBoundary>
            )}
        </>
    )
}
