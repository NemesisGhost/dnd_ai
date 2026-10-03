import { useId, useState } from "react"
import { Link } from "react-router"
import { PasswordField } from "../components/PasswordField"
import { useResetPassword } from "../hooks/useResetPassword"
import type { ResetPasswordStatus } from "../hooks/useResetPassword"
import { captureFragmentToken } from "../utils/fragmentToken"

function statusMessage(
    kind: "pending" | "policy_violation" | "unavailable" | "rate_limited" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Resetting…"
        case "policy_violation":
            return "Choose a passphrase of at least 15 characters that is not commonly used."
        case "unavailable":
            return "This password-reset link is no longer available. It may have expired or already been used."
        case "rate_limited":
            return "Too many attempts. Wait and try again."
        case "error":
            return "The password could not be reset. Try again."
    }
}

// Public route: same fragment-read discipline as ActivateAccountPage — no
// server-side continuation exists for this token either
// (dnd_ai.api.local_auth's single-shot POST /auth/password-reset; browser page: /reset-password), so it lives
// in this component's own state for the life of the form only.
export function ResetPasswordPage() {
    const { status, submit, reset } = useResetPassword()

    if (status.kind === "success") {
        return (
            <main className="app-main">
                <section className="placeholder-page" aria-labelledby="reset-success-heading">
                    <h1 id="reset-success-heading">Password reset</h1>
                    <p>
                        {status.result.sessions_revoked
                            ? "Your password has been reset and every existing browser session has been signed out."
                            : "Your password has been reset."}
                    </p>
                    <p>
                        <Link to="/login">Go to sign in</Link>
                    </p>
                </section>
            </main>
        )
    }

    return <ResetForm status={status} submit={submit} reset={reset} />
}

// Owns the raw token and both password values, so they are discarded when
// the page swaps to the success view (this component unmounts).
function ResetForm({
    status,
    submit,
    reset,
}: {
    status: Exclude<ResetPasswordStatus, { kind: "success" }>
    submit: ReturnType<typeof useResetPassword>["submit"]
    reset: () => void
}) {
    // Lazy initializer, not an effect: StrictMode's second call sees an already
    // sanitized URL, and React keeps the first call's result.
    const [token] = useState<string | null>(captureFragmentToken)
    const [newPassword, setNewPassword] = useState("")
    const [confirmation, setConfirmation] = useState("")
    const passwordFieldId = useId()
    const confirmFieldId = useId()
    const mismatchId = useId()


    if (token === null) {
        return (
            <main className="app-main">
                <section className="placeholder-page" aria-labelledby="reset-missing-heading">
                    <h1 id="reset-missing-heading">This password-reset link is not valid</h1>
                    <p>Check that you copied the entire link, including everything after the #.</p>
                </section>
            </main>
        )
    }

    const isSubmitting = status.kind === "pending"
    const mismatch = confirmation !== "" && confirmation !== newPassword

    return (
        <main className="app-main">
            <section className="login-page" aria-labelledby="reset-heading">
                <div className="login-container">
                    <div className="login-box">
                        <h1 id="reset-heading" className="login-title">
                            Reset your password
                        </h1>
                        <p className="login-subtitle">Choose a new password for your account.</p>

                        <form
                            className="login-form"
                            aria-busy={isSubmitting}
                            onSubmit={(event) => {
                                event.preventDefault()
                                if (isSubmitting) {
                                    return
                                }
                                if (confirmation !== newPassword) {
                                    document.getElementById(confirmFieldId)?.focus()
                                    return
                                }
                                submit(token, newPassword)
                            }}
                        >
                            <PasswordField
                                id={passwordFieldId}
                                label="New passphrase"
                                value={newPassword}
                                onChange={(value) => {
                                    setNewPassword(value)
                                    if (status.kind !== "idle") {
                                        reset()
                                    }
                                }}
                                autoComplete="new-password"
                                minLength={15}
                                disabled={isSubmitting}
                            />

                            <PasswordField
                                id={confirmFieldId}
                                label="Confirm passphrase"
                                value={confirmation}
                                onChange={(value) => {
                                    setConfirmation(value)
                                    if (status.kind !== "idle") {
                                        reset()
                                    }
                                }}
                                autoComplete="new-password"
                                minLength={15}
                                disabled={isSubmitting}
                                invalid={mismatch}
                                describedBy={mismatch ? mismatchId : undefined}
                            />

                            <p
                                id={mismatchId}
                                className="login-error"
                                role={mismatch ? "alert" : undefined}
                                hidden={!mismatch}
                            >
                                {mismatch ? "The passphrases do not match." : ""}
                            </p>

                            {status.kind !== "idle" && status.kind !== "pending" && (
                                <p className="login-error" role="alert">
                                    {statusMessage(status.kind)}
                                </p>
                            )}

                            <button type="submit" className="login-button" disabled={isSubmitting}>
                                {isSubmitting ? statusMessage("pending") : "Reset password"}
                            </button>
                        </form>
                    </div>
                </div>
            </section>
        </main>
    )
}
