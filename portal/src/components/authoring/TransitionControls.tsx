import { useState } from "react"
import type { MutationContext } from "../../api/worlds"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import type { RefetchOutcome } from "../../hooks/useAuthoringResource"
import { useConfirmedRefresh } from "../../hooks/useConfirmedRefresh"
import type { TransitionRequest } from "../../types/worldAuthoring"
import { validateReason } from "../../utils/authoringValidation"
import { useAnnounce } from "./announcer"
import { ConfirmDialog } from "./ConfirmDialog"
import { MutationStatusMessage } from "./feedback"
import "./authoring.css"

type Pending = "archive" | "restore" | null

interface TransitionControlsProps {
    // "world", "timeline": used in labels and announcements.
    noun: string
    scopeId: string
    rowVersion: number
    // The server's `available_actions`; a button appears only for an action the
    // server reports.
    availableActions: readonly string[]
    archive: (body: TransitionRequest, ctx: MutationContext) => Promise<unknown>
    restore: (body: TransitionRequest, ctx: MutationContext) => Promise<unknown>
    // Authoritative refetch of the record; awaited before the success announcement, and its outcome
    // decides whether the change is announced as done or reported as saved but not yet read.
    refetch: () => Promise<RefetchOutcome>
    // The page's latest read of the record failed and it shows the last one that loaded: its version
    // may be behind, so the transition waits for the read.
    pageStale?: boolean
    archiveDescription: string
    restoreDescription: string
}

// Archive and Restore buttons plus their confirmation dialog, shared by every
// record that supports the pair. Renders a fragment of buttons so the caller
// places them in its own action row. The dialog closes only on success and
// shows failures inside itself; a stale version offers "Load latest version".
export function TransitionControls({
    noun,
    scopeId,
    rowVersion,
    availableActions,
    archive,
    restore,
    refetch,
    pageStale = false,
    archiveDescription,
    restoreDescription,
}: TransitionControlsProps) {
    const announce = useAnnounce()
    const { reload } = useSession()
    const [pendingAction, setPendingAction] = useState<Pending>(null)
    // What was saved without the record being read back. The mutation's own status cannot carry it:
    // its scope names the open dialog, and the dialog closes once the change is saved.
    const [unread, setUnread] = useState<string | null>(null)
    const [reason, setReason] = useState("")
    const [reasonError, setReasonError] = useState<string | null>(null)
    const available = new Set(availableActions)
    const capitalized = noun.charAt(0).toUpperCase() + noun.slice(1)

    const mutation = useAuthoringMutation<TransitionRequest, unknown>({
        scopeKey: `${pendingAction ?? "none"}:${scopeId}`,
        request: (body, ctx) =>
            pendingAction === "restore" ? restore(body, ctx) : archive(body, ctx),
        onSuccess: async () => {
            const message = pendingAction === "restore" ? `${capitalized} restored` : `${capitalized} archived`
            const outcome = await refetch()
            setPendingAction(null)
            setReason("")
            if (outcome === "ok") {
                announce(message)
            } else {
                // Saved, but the record on screen is the one from before: it still offers the same
                // transition at the old version, so it is held until the record is read again.
                setUnread(message)
            }
            return outcome
        },
    })
    const refreshed = useConfirmedRefresh({
        status: unread === null ? { kind: "idle" } : { kind: "confirmed", refresh: "failed" },
        reset: () => setUnread(null),
        what: noun,
        message: unread,
        read: refetch,
        pageStale,
    })
    const writesHeld = refreshed.held || pageStale

    function open(action: Exclude<Pending, null>) {
        if (writesHeld) return
        mutation.reset()
        setReason("")
        setReasonError(null)
        setPendingAction(action)
    }

    function confirm() {
        const problem = validateReason(reason, false)
        setReasonError(problem)
        if (problem) {
            return
        }
        mutation.submit({
            expected_row_version: rowVersion,
            reason: reason.trim() === "" ? null : reason.trim(),
        })
    }

    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const verb = pendingAction === "restore" ? "Restore" : "Archive"

    return (
        <>
            {available.has("archive") ? (
                <button type="button" className="authoring-button" disabled={writesHeld} onClick={() => open("archive")}>
                    Archive {noun}
                </button>
            ) : null}
            {available.has("restore") ? (
                <button type="button" className="authoring-button" disabled={writesHeld} onClick={() => open("restore")}>
                    Restore {noun}
                </button>
            ) : null}
            {refreshed.notice}

            <ConfirmDialog
                open={pendingAction !== null}
                title={`${verb} this ${noun}?`}
                description={pendingAction === "restore" ? restoreDescription : archiveDescription}
                confirmLabel={`${verb} ${noun}`}
                onConfirm={confirm}
                onCancel={() => setPendingAction(null)}
                pending={mutation.status.kind === "pending"}
                reason={{
                    label: "Reason (optional)",
                    required: false,
                    value: reason,
                    onChange: setReason,
                    error: reasonError,
                }}
                error={
                    error === null ? null : error.kind === "stale" ? (
                        <div role="alert" className="authoring-message authoring-message--warning">
                            <div>
                                <p>
                                    Someone else changed this {noun}. Reload it to see the latest
                                    version.
                                </p>
                                <button
                                    type="button"
                                    className="authoring-button"
                                    onClick={() => {
                                        mutation.reset()
                                        void refetch()
                                    }}
                                >
                                    Load latest version
                                </button>
                            </div>
                        </div>
                    ) : (
                        <MutationStatusMessage
                            error={error}
                            onRetry={mutation.retry}
                            onCheckSession={reload}
                        />
                    )
                }
            />
        </>
    )
}
