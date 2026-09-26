import { useId, useState } from "react"
import { Link } from "react-router"
import { PasswordField } from "../components/PasswordField"
import { useResetPassword } from "../hooks/useResetPassword"
import PlaceholderPage from "./PlaceholderPage"

const _HASH_TOKEN_PREFIX = "#token="

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

function extractTokenFromLocationHash(): string | null {
    const hash = window.location.hash
    if (!hash.startsWith(_HASH_TOKEN_PREFIX)) {
        return null
    }
    const extracted = decodeURIComponent(hash.slice(_HASH_TOKEN_PREFIX.length))
    // See ActivateAccountPage's identical helper for why this runs from a
    // useState lazy initializer, not an effect, and why a StrictMode
    // double-invocation is a safe no-op on its second call.
    window.history.replaceState(null, "", window.location.pathname + window.location.search)
    return extracted
}

// Public route: same fragment-read discipline as ActivateAccountPage — no
// server-side continuation exists for this token either
// (dnd_ai.api.local_auth's single-shot /auth/password-reset), so it lives
// in this component's own state for the life of the form only.
export function ResetPasswordPage() {
    const [hadHash] = useState(() => window.location.hash.startsWith(_HASH_TOKEN_PREFIX))
    const [token] = useState<string | null>(extractTokenFromLocationHash)
    const [newPassword, setNewPassword] = useState("")
    const passwordFieldId = useId()

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

    if (!hadHash) {
        return (
            <main className="app-main">
                <section className="placeholder-page" aria-labelledby="reset-missing-heading">
                    <h1 id="reset-missing-heading">This password-reset link is not valid</h1>
                    <p>Check that you copied the entire link, including everything after the #.</p>
                </section>
            </main>
        )
    }

    if (token === null) {
        return (
            <main className="app-main">
                <PlaceholderPage
                    title="Opening your password-reset link"
                    description="Reading the password-reset link."
                />
            </main>
        )
    }

    const isSubmitting = status.kind === "pending"

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
