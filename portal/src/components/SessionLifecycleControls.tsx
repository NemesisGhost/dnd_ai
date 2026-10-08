import { useState } from "react"
import { archiveSession, restoreSession } from "../api/sessionAuthoring"
import { ConfirmDialog } from "./authoring/ConfirmDialog"
import { useAnnounce } from "./authoring/announcer"
import { MutationStatusMessage, StaleWriteNotice } from "./authoring/feedback"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import type { CampaignSessionDetail, SessionReceipt } from "../types/campaignSession"
import { SESSION_ERROR_MESSAGE } from "../utils/sessionForm"
import "./authoring/authoring.css"

// Archive and Restore for the session detail page. Offered only to a member
// with canon.edit and only when the server lists the action; the confirmation
// dialog and the reason Restore requires are unchanged.
export function SessionLifecycleControls({
    campaignId,
    session,
    canManage,
    refresh,
    blockedReason,
}: {
    campaignId: string
    session: CampaignSessionDetail
    canManage: boolean
    refresh: () => Promise<boolean>
    // Why Archive is unavailable right now (unsaved changes), if it is.
    blockedReason?: string | null
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [dialog, setDialog] = useState<"archive" | "restore" | null>(null)
    const [reason, setReason] = useState("")
    const [reasonError, setReasonError] = useState<string | null>(null)
    const actions = canManage ? (session.available_actions ?? []) : []
    const mutation = useAuthoringMutation<"archive" | "restore", SessionReceipt>({
        scopeKey: `session-lifecycle:${session.session_id}:${session.row_version ?? 0}`,
        request: (action, ctx) =>
            action === "archive"
                ? archiveSession(
                      campaignId,
                      session.session_id,
                      { expected_row_version: session.row_version ?? 1, reason: reason.trim() || null },
                      ctx,
                  )
                : restoreSession(
                      campaignId,
                      session.session_id,
                      { expected_row_version: session.row_version ?? 1, reason: reason.trim() },
                      ctx,
                  ),
        onSuccess: async () => {
            const done = dialog === "archive" ? "Session archived" : "Session restored"
            setDialog(null)
            setReason("")
            await refresh()
            announce(done)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = error?.code ? (SESSION_ERROR_MESSAGE[error.code] ?? null) : null
    const inProgress = canManage && session.play_status === "in_progress"

    if (!actions.includes("archive") && !actions.includes("restore") && !inProgress) return null
    return (
        <section aria-labelledby="session-lifecycle-heading">
            <h2 id="session-lifecycle-heading">Archive</h2>
            {inProgress ? (
                <p className="authoring-note">End the session before archiving it.</p>
            ) : null}
            {actions.includes("archive") ? (
                <button
                    type="button"
                    className="authoring-button"
                    disabled={Boolean(blockedReason)}
                    onClick={() => {
                        mutation.reset()
                        setDialog("archive")
                    }}
                >
                    Archive session
                </button>
            ) : null}
            {actions.includes("archive") && blockedReason ? (
                <p className="authoring-note">{blockedReason}</p>
            ) : null}
            {actions.includes("restore") ? (
                <button
                    type="button"
                    className="authoring-button"
                    onClick={() => {
                        mutation.reset()
                        setDialog("restore")
                    }}
                >
                    Restore session
                </button>
            ) : null}
            <ConfirmDialog
                open={dialog !== null}
                title={dialog === "restore" ? "Restore this session?" : "Archive this session?"}
                description={
                    dialog === "restore"
                        ? "The session is visible to the campaign again."
                        : "The session is hidden from players. It can be restored later."
                }
                confirmLabel={dialog === "restore" ? "Restore session" : "Archive session"}
                pending={mutation.status.kind === "pending"}
                reason={{
                    label: dialog === "restore" ? "Reason" : "Reason (optional)",
                    required: dialog === "restore",
                    value: reason,
                    onChange: (value) => {
                        setReason(value)
                        setReasonError(null)
                    },
                    error: reasonError,
                }}
                error={
                    error?.kind === "stale" ? (
                        <StaleWriteNotice
                            onLoadLatest={() => {
                                mutation.reset()
                                setDialog(null)
                                void refresh()
                            }}
                        />
                    ) : message !== null ? (
                        <p role="alert">{message}</p>
                    ) : error !== null ? (
                        <MutationStatusMessage
                            error={error}
                            onRetry={mutation.retry}
                            onCheckSession={reload}
                        />
                    ) : null
                }
                onConfirm={() => {
                    if (dialog === "restore" && reason.trim() === "") {
                        setReasonError("Enter a reason.")
                        return
                    }
                    if (dialog !== null) mutation.submit(dialog)
                }}
                onCancel={() => {
                    setDialog(null)
                    setReason("")
                    setReasonError(null)
                    mutation.reset()
                }}
            />
        </section>
    )
}
