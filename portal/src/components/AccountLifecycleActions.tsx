import { useState } from "react"
import { useDisableAccount } from "../hooks/useDisableAccount"
import { useIssuePasswordReset } from "../hooks/useIssuePasswordReset"
import { useReactivateAccount } from "../hooks/useReactivateAccount"
import { useRevokeAllSessions } from "../hooks/useRevokeAllSessions"
import { buildFragmentLink } from "../utils/oneTimeLink"
import { OneTimeSecretPanel } from "./OneTimeSecretPanel"
import type { PlatformAccount } from "../types/platformAccounts"

interface AccountLifecycleActionsProps {
    account: PlatformAccount
    onChanged: () => void
}

const _ACTIVE_STATUS_CODE = "active"

export function AccountLifecycleActions({ account, onChanged }: AccountLifecycleActionsProps) {
    const [resetToken, setResetToken] = useState<string | null>(null)
    const [confirmingDisable, setConfirmingDisable] = useState(false)
    const [message, setMessage] = useState<string | null>(null)

    const { status: resetStatus, submit: submitReset } = useIssuePasswordReset((result) => {
        setResetToken(result.raw_reset_token)
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

    if (resetToken !== null) {
        return (
            <OneTimeSecretPanel
                heading="Copy the password-reset link now"
                description="This link is shown once and cannot be recovered later. Send it to the account holder out of band."
                secretLabel="Password-reset link"
                secret={buildFragmentLink("/auth/password-reset", resetToken)}
                onDismiss={() => setResetToken(null)}
            />
        )
    }

    return (
        <div className="access-role-editor__actions">
            <button
                type="button"
                disabled={anyPending}
                onClick={() => submitReset(account.user_id, true)}
            >
                Issue password reset
            </button>

            {isActive ? (
                confirmingDisable ? (
                    <>
                        <button
                            type="button"
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
                    <button type="button" disabled={anyPending} onClick={() => setConfirmingDisable(true)}>
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
                {disableStatus.kind === "conflict"
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
