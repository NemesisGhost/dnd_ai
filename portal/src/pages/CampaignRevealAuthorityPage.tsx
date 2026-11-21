import { useEffect, useRef } from "react"
import { useParams } from "react-router"
import { AccessTabNav } from "../components/AccessTabNav"
import { StaleReadNotice } from "../components/StaleReadNotice"
import { TaskBreadcrumb } from "../components/navigation/TaskBreadcrumb"
import { revealDelegationsPath } from "../api/revealDelegations"
import { useSession } from "../context/SessionContext"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { useKept } from "../hooks/useKeptResource"
import type { LapsedRevealDelegation, RevealDelegationMember, RevealDelegationState } from "../types/revealDelegations"
import PlaceholderPage from "./PlaceholderPage"

const when = (iso: string): string => new Date(iso).toLocaleString()

const grantedBy = (name: string | null): string => `granted by ${name ?? "a former member"}`

// The Access section's Reveal authority tab (docs/delivery/p15-c02-s03-reveal-delegations-plan.md). A separate
// route, so opening it reads only the reveal-delegation state and no other Access tab reads it. Everything shown
// is what the server says: who holds the GM role, whether a delegation authorizes them, and whether the caller
// is an owner. The page never decides ownership, eligibility or effectiveness itself.
export function CampaignRevealAuthorityPage() {
    const { campaignId } = useParams<{ campaignId: string }>()
    if (campaignId === undefined) {
        return (
            <PlaceholderPage title="Access unavailable" description="The requested access information is not available." />
        )
    }
    // Keyed on the campaign: nothing read, typed or pending for one campaign can appear under another.
    return <RevealAuthorityContent key={campaignId} campaignId={campaignId} />
}

function RevealAuthorityContent({ campaignId }: { campaignId: string }) {
    // The content is bound to what the applied session says this campaign grants: without `access.manage` nothing
    // below is mounted, an in-flight read is aborted with it and cannot publish.
    const canManageAccess = useCampaignCapability(campaignId, "access.manage")
    return (
        <>
            <TaskBreadcrumb />
            <AccessTabNav campaignId={campaignId} />
            {canManageAccess ? (
                <RevealAuthorityBody campaignId={campaignId} />
            ) : (
                <PlaceholderPage title="Access unavailable" description="The requested access information is not available." />
            )}
        </>
    )
}

function RevealAuthorityBody({ campaignId }: { campaignId: string }) {
    const path = revealDelegationsPath(campaignId)
    const { state, refetch } = useAuthoringResource<RevealDelegationState>(path)
    const view = useKept(state, path)
    const { refresh } = useSession()
    const gone = state.kind === "denied" || state.kind === "unavailable"
    const stale = state.kind === "error" && view !== null

    // A 403 or 404 on the read says the right to read may be gone: everything is dropped (the list is not kept) and
    // the session is read once in place, so a lost `access.manage` also removes the tab. No retry loop.
    const refreshRef = useRef(refresh)
    useEffect(() => {
        refreshRef.current = refresh
    })
    useEffect(() => {
        if (gone) refreshRef.current()
    }, [gone])

    if (gone) {
        return (
            <PlaceholderPage title="Reveal authority unavailable" description="Reveal authority is not available to you." />
        )
    }
    return (
        <section aria-labelledby="reveal-authority-heading" className="reveal-authority">
            <h2 id="reveal-authority-heading">Reveal authority</h2>
            <p>
                Campaign owners can always reveal characters. A GM can also reveal characters when an owner delegates
                that to them here.
            </p>
            {view === null ? (
                state.kind === "error" ? (
                    <StaleReadNotice what="reveal authority" onRetry={() => void refetch()} />
                ) : (
                    <p role="status">Loading reveal authority…</p>
                )
            ) : (
                <>
                    {state.kind === "error" ? (
                        <StaleReadNotice what="reveal authority" onRetry={() => void refetch()} />
                    ) : null}
                    {/* What the caller may do is the server's `can_manage`, and only from a read that is current. */}
                    {stale ? null : (
                        <p>
                            {view.can_manage
                                ? "You can grant or revoke reveal authority."
                                : "Only a campaign owner can grant or revoke reveal authority."}
                        </p>
                    )}
                    {view.members.length === 0 ? (
                        <p>No member currently holds the GM role.</p>
                    ) : (
                        <ul className="op-list" aria-label="GMs">
                            {view.members.map((member) => (
                                <MemberRow key={member.campaign_membership_id} member={member} />
                            ))}
                        </ul>
                    )}
                    {view.lapsed_delegations.length > 0 ? (
                        <section aria-labelledby="reveal-lapsed-heading">
                            <h3 id="reveal-lapsed-heading">Delegations that no longer apply</h3>
                            <ul className="op-list">
                                {view.lapsed_delegations.map((entry) => (
                                    <LapsedRow key={entry.campaign_membership_id} entry={entry} />
                                ))}
                            </ul>
                        </section>
                    ) : null}
                </>
            )}
        </section>
    )
}

function MemberRow({ member }: { member: RevealDelegationMember }) {
    return (
        <li>
            <p>
                <strong>{member.display_name}</strong>
            </p>
            {member.delegation !== null ? (
                <p>
                    Can reveal characters. Delegated on {when(member.delegation.granted_at)},{" "}
                    {grantedBy(member.delegation.granted_by_name)}.
                </p>
            ) : (
                <p>Cannot reveal characters.</p>
            )}
        </li>
    )
}

function LapsedRow({ entry }: { entry: LapsedRevealDelegation }) {
    return (
        <li>
            <p>
                <strong>{entry.display_name}</strong>
            </p>
            <p>
                {entry.display_name} no longer holds the GM role, so this gives no authority. Delegated on{" "}
                {when(entry.granted_at)}, {grantedBy(entry.granted_by_name)}.
            </p>
        </li>
    )
}
