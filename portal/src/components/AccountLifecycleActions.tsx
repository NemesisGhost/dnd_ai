import { useState } from "react"
import { useDisableAccount } from "../hooks/useDisableAccount"
import { useIssuePasswordReset } from "../hooks/useIssuePasswordReset"
import { useReactivateAccount } from "../hooks/useReactivateAccount"
import { useRevokeAllSessions } from "../hooks/useRevokeAllSessions"
import type { PlatformAccount } from "../types/platformAccounts"

export interface IssuedPasswordReset {
    displayName: string
    rawToken: string
    expiresAt: string
}

interface AccountLifecycleActionsProps {
    account: PlatformAccount
    onChanged: () => void
    // The one-time reset secret is owned by a parent that outlives the
    // account-list refetch (which unmounts this row); this component only
    // reports start/success and never retains the token itself.
    onResetStarted: () => void
    onResetIssued: (issued: IssuedPasswordReset) => void
}

const _RESET_ERROR_MESSAGE = "The password-reset link could not be issued. Try again."

const _ACTIVE_STATUS_CODE = "active"

export function AccountLifecycleActions({
    account,
    onChanged,
    onResetStarted,
    onResetIssued,
}: AccountLifecycleActionsProps) {
    const [confirmingDisable, setConfirmingDisable] = useState(false)
    const [message, setMessage] = useState<string | null>(null)

    const { status: resetStatus, submit: submitReset } = useIssuePasswordReset((result) => {
        onResetIssued({
            displayName: account.display_name,
            rawToken: result.raw_reset_token,
            expiresAt: result.expires_at,
        })
        onChanged()
    })
    const { status: disableStatus, submit: submitDisable } = useDisableAccount(() => {
        setConfirmingDisable(false)
        setMessage("Account disabled.")
        onChanged()
    })
    const { status: reactivateStatus, submit: submitReactivate } = useReactivateAccount(() => {
        setMessage("Account reactivated.")
        onChanged()
    })
    const { status: revokeStatus, submit: submitRevoke } = useRevokeAllSessions((result) => {
        setMessage(`Revoked ${result.revoked_count} session(s).`)
        onChanged()
    })

    const isActive = account.lifecycle_status_code === _ACTIVE_STATUS_CODE
    const anyPending =
        resetStatus.kind === "pending" ||
        disableStatus.kind === "pending" ||
        reactivateStatus.kind === "pending" ||
        revokeStatus.kind === "pending"

    return (
        <div className="access-role-editor__actions account-actions">
            <button
                type="button"
                disabled={anyPending}
                onClick={() => {
                    onResetStarted()
                    submitReset(account.user_id, true)
                }}
            >
                Issue password reset
            </button>

            {isActive ? (
                confirmingDisable ? (
                    <>
                        <button
                            type="button"
                            className="account-actions__danger"
                            disabled={anyPending}
                            onClick={() => submitDisable(account.user_id)}
                        >
                            Confirm disable
                        </button>
                        <button type="button" onClick={() => setConfirmingDisable(false)}>
                            Cancel
                        </button>
                    </>
                ) : (
                    <button
                        type="button"
                        className="account-actions__danger"
                        disabled={anyPending}
                        onClick={() => setConfirmingDisable(true)}
                    >
                        Disable
                    </button>
                )
            ) : (
                <button
                    type="button"
                    disabled={anyPending}
                    onClick={() => submitReactivate(account.user_id)}
                >
                    Reactivate
                </button>
            )}

            <button
                type="button"
                disabled={anyPending}
                onClick={() => submitRevoke(account.user_id)}
            >
                Revoke all sessions
            </button>

            <p role="status" aria-live="polite" className="access-role-editor__status">
                {resetStatus.kind === "pending"
                    ? "Issuing password-reset link…"
                    : resetStatus.kind === "success"
                      ? "Password-reset link issued. Copy it from the panel above the table."
                      : resetStatus.kind === "error"
                        ? _RESET_ERROR_MESSAGE
                        : disableStatus.kind === "conflict"
                          ? disableStatus.message
                          : disableStatus.kind === "denied" ||
                        reactivateStatus.kind === "denied" ||
                        revokeStatus.kind === "denied" ||
                        resetStatus.kind === "denied"
                      ? "You do not have permission to make this change."
                      : (message ?? "")}
            </p>
        </div>
    )
}
