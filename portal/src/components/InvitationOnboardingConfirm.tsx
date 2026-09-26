import { useEffect, useId, useState } from "react"
import { logout } from "../api/logout"
import { useSession } from "../context/SessionContext"
import { useCompleteInvitationOnboarding } from "../hooks/useCompleteInvitationOnboarding"
import type { CompleteInvitationOnboardingResponse } from "../types/invitationOnboarding"

interface InvitationOnboardingConfirmProps {
    campaignDisplayName: string
    signedInDisplayName: string
    onCompleted: (result: CompleteInvitationOnboardingResponse) => void
    // Called after "Use a different account" signs the current account
    // out, and separately when this account's session has expired
    // mid-flow (R-5) -- either way, the parent re-reads onboarding status
    // in place so next_action reflects the change, rather than navigating
    // away from the invitation link.
    onNeedsStatusRefresh: () => void
}

// The account that will join is always the caller's own current session
// (S-1/S-4 of PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §7.1) -- this
// component never accepts an asserted identity, only displays and
// confirms the one the server already resolved.
export function InvitationOnboardingConfirm({
    campaignDisplayName,
    signedInDisplayName,
    onCompleted,
    onNeedsStatusRefresh,
}: InvitationOnboardingConfirmProps) {
    const { status, submit } = useCompleteInvitationOnboarding()
    const { state: sessionState, reload } = useSession()
    const [switchAccountError, setSwitchAccountError] = useState(false)
    const [isSwitchingAccount, setIsSwitchingAccount] = useState(false)
    const statusId = useId()

    const isSubmitting = status.kind === "pending"

    useEffect(() => {
        if (status.kind === "success") {
            onCompleted(status.result)
        }
        if (status.kind === "session_expired") {
            onNeedsStatusRefresh()
        }
    }, [status, onCompleted, onNeedsStatusRefresh])

    async function handleUseDifferentAccount(): Promise<void> {
        if (sessionState.status !== "authenticated" || isSubmitting) {
            return
        }
        setIsSwitchingAccount(true)
        setSwitchAccountError(false)
        try {
            await logout(sessionState.bootstrap.csrf_token)
            reload()
            onNeedsStatusRefresh()
        } catch {
            setSwitchAccountError(true)
        } finally {
            setIsSwitchingAccount(false)
        }
    }

    return (
        <section aria-labelledby="onboarding-confirm-heading">
            <h1 id="onboarding-confirm-heading">Join {campaignDisplayName}?</h1>
            <p>
                You are signed in as <strong>{signedInDisplayName}</strong>. Joining will add this
                account to the campaign.
            </p>

            <div className="access-role-editor__actions">
                <button
                    type="button"
                    className="login-button"
                    disabled={isSubmitting || isSwitchingAccount}
                    aria-busy={isSubmitting}
                    onClick={() => {
                        submit()
                    }}
                >
                    {isSubmitting ? "Joining…" : `Join ${campaignDisplayName}`}
                </button>
                <button
                    type="button"
                    disabled={isSubmitting || isSwitchingAccount}
                    onClick={() => void handleUseDifferentAccount()}
                >
                    Use a different account
                </button>
            </div>

            <p id={statusId} className="login-error" role="alert" aria-live="polite">
                {status.kind === "unavailable" &&
                    "This invitation is no longer available. It may have expired, been revoked, or already been used."}
                {status.kind === "error" && "Something went wrong. Try again."}
                {switchAccountError && "Could not sign out. Try again."}
            </p>
        </section>
    )
}
