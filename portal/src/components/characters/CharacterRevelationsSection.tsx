import { useEffect, useRef } from "react"
import { revelationsPath } from "../../api/characterRevelations"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import { useKept } from "../../hooks/useKeptResource"
import type { CharacterRevelation, CharacterRevelationsRead } from "../../types/characterRevelations"
import { StaleReadNotice } from "../StaleReadNotice"
import "../authoring/authoring.css"

const END_REASON: Readonly<Record<string, string>> = {
    revoked: "Revoked",
    target_membership_ended: "Membership ended",
    access_group_deactivated: "Group deactivated",
}

const AUTHORITY: Readonly<Record<string, string>> = { owner: "Owner", delegation: "Delegated GM" }

const when = (iso: string): string => new Date(iso).toLocaleString()

const newestFirst = (rows: readonly CharacterRevelation[]): CharacterRevelation[] =>
    [...rows].sort((a, b) => b.created_at.localeCompare(a.created_at))

// What the audience of a revelation is called. Names only, never ids.
function audienceLabel(revelation: CharacterRevelation): string {
    switch (revelation.audience_kind) {
        case "member":
            return revelation.target_member_name ?? "A member"
        case "access_group":
            return `Group: ${revelation.target_access_group_name ?? "an access group"}`
        case "campaign_current":
            return `Campaign members at the time (${revelation.audience_size ?? 0})`
        case "campaign_current_and_future":
            return "All campaign members, including future ones"
    }
}

// The Revelations section of a character's Public profile page (docs/delivery/p15-c02-s02-revelations-plan.md).
// The page mounts it only while its own read is held, so its audience is the page's audience (the
// D8 read rule), and it keys the page on the character, so a read for one character is never shown
// under another. A 404 means the list may no longer be read: the content is dropped and the page is
// asked to read again, which decides whether the whole page is gone.
export function CharacterRevelationsSection({
    campaignId,
    characterId,
    onGone,
}: {
    campaignId: string
    characterId: string
    onGone: () => void
}) {
    const path = revelationsPath(campaignId, characterId)
    const { state, refetch } = useAuthoringResource<CharacterRevelationsRead>(path)
    const view = useKept(state, path)
    const gone = state.kind === "unavailable" || state.kind === "denied"
    const goneRef = useRef(onGone)
    useEffect(() => {
        goneRef.current = onGone
    })
    useEffect(() => {
        if (gone) goneRef.current()
    }, [gone])

    let body
    if (gone) {
        body = <p>The revelations of this character are not available to you.</p>
    } else if (view === null) {
        body =
            state.kind === "error" ? (
                <StaleReadNotice what="revelations" onRetry={() => void refetch()} />
            ) : (
                <p role="status">Loading revelations…</p>
            )
    } else {
        const live = newestFirst(view.revelations.filter((r) => r.live))
        const ended = newestFirst(view.revelations.filter((r) => !r.live))
        body = (
            <>
                {state.kind === "error" ? <StaleReadNotice what="revelations" onRetry={() => void refetch()} /> : null}
                {view.revelations.length === 0 ? <p>This character hasn't been revealed to anyone.</p> : null}
                {live.length > 0 ? (
                    <section aria-label="Visible to">
                        <h3>Visible to</h3>
                        <ul className="op-list">
                            {live.map((revelation) => (
                                <RevelationRow key={revelation.character_revelation_id} revelation={revelation} />
                            ))}
                        </ul>
                    </section>
                ) : null}
                {ended.length > 0 ? (
                    <section aria-label="Ended">
                        <h3>Ended</h3>
                        <ul className="op-list">
                            {ended.map((revelation) => (
                                <RevelationRow key={revelation.character_revelation_id} revelation={revelation} />
                            ))}
                        </ul>
                    </section>
                ) : null}
            </>
        )
    }
    return (
        <section aria-label="Revelations" className="authoring-section">
            <h2>Revelations</h2>
            {body}
        </section>
    )
}

function RevelationRow({ revelation }: { revelation: CharacterRevelation }) {
    return (
        <li>
            <p>
                <strong>{audienceLabel(revelation)}</strong>
            </p>
            <p>
                Revealed by {revelation.created_by_name} on {when(revelation.created_at)} (
                {AUTHORITY[revelation.authority_source] ?? revelation.authority_source})
            </p>
            {!revelation.live && revelation.ended_at !== null ? (
                <p>
                    Ended {when(revelation.ended_at)}: {END_REASON[revelation.end_reason ?? ""] ?? "Ended"}
                </p>
            ) : null}
            {revelation.audience_kind === "campaign_current" && revelation.snapshot_members !== undefined ? (
                <details>
                    <summary>Members at the time</summary>
                    <ul>
                        {revelation.snapshot_members.map((member) => (
                            <li key={member.campaign_membership_id}>
                                {member.display_name}
                                {member.removed_at !== null ? " (Left the campaign)" : ""}
                            </li>
                        ))}
                    </ul>
                </details>
            ) : null}
        </li>
    )
}
