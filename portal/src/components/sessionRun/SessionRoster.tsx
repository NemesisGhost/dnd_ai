import type { ReactNode } from "react"
import { Link } from "react-router"
import type { SessionParticipant } from "../../types/campaignSession"
import { characterKindLabel } from "../../utils/characterKind"
import { ROLE_LABEL } from "./participantRoles"
import { RealWorldTime } from "./RealWorldTime"

// The roster for one session (the GM's: every stint; a member's: the same stints, only for characters they may discover). Present first, then those who left.
// A character removed and added again is two rows (keyed by the participant record, not the
// character). Read-only on its own; the Run page passes `controls` for the rows it may change.
export function SessionRoster({
    campaignId,
    participants,
    controls,
    emptyText = "No one is in this session yet.",
}: {
    campaignId: string
    participants: readonly SessionParticipant[]
    // Rendered after a present participant's details. Never called for someone who has left.
    controls?: (participant: SessionParticipant) => ReactNode
    emptyText?: string
}) {
    if (participants.length === 0) {
        return <p>{emptyText}</p>
    }
    const present = participants.filter((p) => p.removed_at === null)
    const gone = participants.filter((p) => p.removed_at !== null)
    return (
        <ul className="op-list" aria-label="Session participants">
            {[...present, ...gone].map((p) => (
                <li key={p.session_participant_id}>
                    {p.can_open_character === false ? (
                        p.character_name
                    ) : (
                        <Link
                            to={`/app/${encodeURIComponent(campaignId)}/characters/${encodeURIComponent(p.character_id)}`}
                        >
                            {p.character_name}
                        </Link>
                    )}{" "}
                    ({characterKindLabel(p.character_kind)}; role: {ROLE_LABEL[p.participation_role] ?? p.participation_role}
                    ). <strong>{p.removed_at === null ? "Present" : "Left"}</strong>.{" "}
                    <RealWorldTime label="Added" value={p.added_at} />
                    {p.removed_at !== null ? (
                        <>
                            {". "}
                            <RealWorldTime label="Removed" value={p.removed_at} />
                        </>
                    ) : null}{" "}
                    {p.removed_at === null ? controls?.(p) : null}
                </li>
            ))}
        </ul>
    )
}
