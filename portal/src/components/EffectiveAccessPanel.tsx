import { useId, useState } from "react"
import { useEffectiveAccess } from "../hooks/useEffectiveAccess"
import { humanizeCode } from "../utils/humanize"

const SOURCE_KIND_LABELS: Record<string, string> = {
    role: "Role",
    character_relationship: "Character relationship",
    resource_grant: "Direct grant",
    access_group: "Group grant",
}

function sourceKindLabel(kind: string): string {
    return SOURCE_KIND_LABELS[kind] ?? humanizeCode(kind)
}

interface EffectiveAccessContentProps {
    campaignId: string
    campaignMembershipId: string
}

// Mounted only while its own disclosure is open — see
// EffectiveAccessPanel below. Unmounting this component (rather than
// merely hiding it) is what actually drops the fetched access shape from
// memory the moment the disclosure closes or a different member's own
// disclosure is opened instead, satisfying this checkpoint's own "the
// panel clears when the selected member changes or the panel closes, so
// protected data cannot linger" security invariant without any explicit
// reset effect.
function EffectiveAccessContent({ campaignId, campaignMembershipId }: EffectiveAccessContentProps) {
    const { state, retry } = useEffectiveAccess(campaignId, campaignMembershipId)

    if (state.status === "loading") {
        return <p>Loading access explanation…</p>
    }

    if (state.status === "unavailable") {
        return <p>This member's access explanation is not available.</p>
    }

    if (state.status === "error") {
        return (
            <p>
                The access explanation could not be loaded.{" "}
                <button type="button" onClick={retry}>
                    Retry
                </button>
            </p>
        )
    }

    const { access } = state

    return (
        <>
            {access.capabilities.length > 0 ? (
                <ul className="effective-access-panel__capabilities">
                    {access.capabilities.map((capability) => (
                        <li key={capability.code}>
                            <strong>{capability.display_name}</strong>
                            <ul className="effective-access-panel__sources">
                                {capability.sources.map((source, index) => (
                                    <li key={`${capability.code}-${index}`}>
                                        {sourceKindLabel(source.kind)}: {source.label}
                                        {source.target_display_name !== null &&
                                            ` (${source.target_display_name})`}
                                    </li>
                                ))}
                            </ul>
                        </li>
                    ))}
                </ul>
            ) : (
                <p>This member holds no capability in this campaign.</p>
            )}

            {access.denials.length > 0 && (
                <>
                    <p className="effective-access-panel__denials-heading">
                        Explicitly denied for a specific resource:
                    </p>
                    <ul className="effective-access-panel__denials">
                        {access.denials.map((denial, index) => (
                            <li key={index}>
                                {denial.capability_code} — {humanizeCode(denial.target_type)}
                                {denial.target_display_name !== null &&
                                    ` (${denial.target_display_name})`}
                            </li>
                        ))}
                    </ul>
                </>
            )}
        </>
    )
}

interface EffectiveAccessPanelProps {
    campaignId: string
    campaignMembershipId: string
    memberDisplayName: string
}

// The GM-facing "why can this person see this?" explanation (docs/
// UI_DESIGN.md §6.4 "Effective-access explanation" / §8.3, checkpoint 13).
// One disclosure per member row rather than a single shared side panel —
// each disclosure's own EffectiveAccessContent only ever mounts (and
// therefore only ever fetches) while that specific member's own toggle is
// open, so no member's access shape is ever fetched, held, or shown
// without an explicit, per-row action, and closing a row's own disclosure
// clears its data immediately by unmounting rather than merely hiding it.
export function EffectiveAccessPanel({
    campaignId,
    campaignMembershipId,
    memberDisplayName,
}: EffectiveAccessPanelProps) {
    const [isOpen, setIsOpen] = useState(false)
    const headingId = useId()

    return (
        <div className="effective-access-panel">
            <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => setIsOpen((currentIsOpen) => !currentIsOpen)}
            >
                {isOpen ? "Hide access explanation" : "Explain access"}
            </button>

            {isOpen && (
                <section aria-labelledby={headingId}>
                    <h4 id={headingId}>Why {memberDisplayName} can see this</h4>
                    <EffectiveAccessContent
                        campaignId={campaignId}
                        campaignMembershipId={campaignMembershipId}
                    />
                </section>
            )}
        </div>
    )
}
