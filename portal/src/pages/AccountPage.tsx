import { useId, useState } from "react"
import { PasswordField } from "../components/PasswordField"
import { OwnSessionsList } from "../components/OwnSessionsList"
import { useChangePassword } from "../hooks/useChangePassword"
import { useOwnSessions } from "../hooks/useOwnSessions"
import { useRevokeOwnSession } from "../hooks/useRevokeOwnSession"
import { useSession } from "../context/SessionContext"

function changePasswordStatusMessage(
    kind: "pending" | "denied" | "policy_violation" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Changing password…"
        case "denied":
            return "Your current password did not match."
        case "policy_violation":
            return "Choose a passphrase of at least 15 characters that is not commonly used."
        case "error":
            return "The password could not be changed. Try again."
    }
}

export function AccountPage() {
    const { reload } = useSession()
    const currentPasswordId = useId()
    const newPasswordId = useId()
    const [currentPassword, setCurrentPassword] = useState("")
    const [newPassword, setNewPassword] = useState("")

    const { status: changeStatus, submit: submitChange, reset: resetChange } = useChangePassword(
        () => {
            setCurrentPassword("")
            setNewPassword("")
        },
    )

    const { state: sessionsState, retry: retrySessions } = useOwnSessions()
    const [pendingRevokeSessionId, setPendingRevokeSessionId] = useState<string | null>(null)

    const { submit: submitRevokeInternal } = useRevokeOwnSession((_browserSessionId, isCurrent) => {
        setPendingRevokeSessionId(null)
        if (isCurrent) {
            // A successful password change does not itself revoke other
            // sessions (change_password's own documented behavior);
            // revoking the *current* one, however, is treated as an
            // intentional sign-out here -- reload() re-derives
            // AuthenticatedSessionBoundary's state from a fresh
            // GET /auth/session, which now 401s and redirects to /login
            // on its own, rather than this page navigating directly.
            reload()
            return
        }
        retrySessions()
    })

    function submitRevoke(browserSessionId: string, isCurrent: boolean): void {
        setPendingRevokeSessionId(browserSessionId)
        submitRevokeInternal(browserSessionId, isCurrent)
    }

    const isChanging = changeStatus.kind === "pending"

    return (
        <main className="app-main">
            <section aria-labelledby="account-heading">
                <h1 id="account-heading">Your account</h1>

                <section aria-labelledby="account-password-heading">
                    <h2 id="account-password-heading">Change password</h2>
                    <form
                        className="login-form"
                        aria-busy={isChanging}
                        onSubmit={(event) => {
                            event.preventDefault()
                            if (isChanging) {
                                return
                            }
                            submitChange(currentPassword, newPassword)
                        }}
                    >
                        <PasswordField
                            id={currentPasswordId}
                            label="Current password"
                            value={currentPassword}
                            onChange={(value) => {
                                setCurrentPassword(value)
                                if (changeStatus.kind !== "idle") {
                                    resetChange()
                                }
                            }}
                            autoComplete="current-password"
                            disabled={isChanging}
                        />
                        <PasswordField
                            id={newPasswordId}
                            label="New password"
                            value={newPassword}
                            onChange={(value) => {
                                setNewPassword(value)
                                if (changeStatus.kind !== "idle") {
                                    resetChange()
                                }
                            }}
                            autoComplete="new-password"
                            minLength={15}
                            disabled={isChanging}
                        />

                        <p role="status" aria-live="polite" className="login-error">
                            {changeStatus.kind === "success"
                                ? "Password changed."
                                : changeStatus.kind === "idle"
                                  ? ""
                                  : changePasswordStatusMessage(changeStatus.kind)}
                        </p>

                        <button type="submit" className="login-button" disabled={isChanging}>
                            {isChanging ? "Changing…" : "Change password"}
                        </button>
                    </form>
                </section>

                <section aria-labelledby="account-sessions-heading">
                    <h2 id="account-sessions-heading">Browser sessions</h2>
                    <p>
                        Changing your password does not sign out other devices. Revoke each session
                        individually below.
                    </p>

                    {sessionsState.status === "loading" && <p>Loading sessions…</p>}
                    {sessionsState.status === "error" && (
                        <>
                            <p>Sessions could not be loaded.</p>
                            <button type="button" onClick={retrySessions}>
                                Try again
                            </button>
                        </>
                    )}
                    {sessionsState.status === "success" && (
                        <OwnSessionsList
                            sessions={sessionsState.sessions}
                            onRevoke={submitRevoke}
                            revokingSessionId={pendingRevokeSessionId}
                        />
                    )}
                </section>
            </section>
        </main>
    )
}
