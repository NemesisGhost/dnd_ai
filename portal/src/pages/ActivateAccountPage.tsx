import { useId, useState } from "react"
import { Link } from "react-router"
import { PasswordField } from "../components/PasswordField"
import { useActivateAccount } from "../hooks/useActivateAccount"
import type { ActivateAccountStatus } from "../hooks/useActivateAccount"
import { captureFragmentToken } from "../utils/fragmentToken"

function statusMessage(
    kind: "pending" | "policy_violation" | "unavailable" | "rate_limited" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Activating…"
        case "policy_violation":
            return "Choose a passphrase of at least 15 characters that is not commonly used."
        case "unavailable":
            return "This activation link is no longer available. It may have expired or already been used."
        case "rate_limited":
            return "Too many attempts. Wait and try again."
        case "error":
            return "The account could not be activated. Try again."
    }
}

// Public route: reads the activation token from the URL fragment exactly
// once (see captureFragmentToken). No server-side
// continuation exists for this token (dnd_ai.api.local_auth's own
// single-shot POST /auth/activate; browser page: /activate), so the extracted value lives in this
// component's own state for the life of the form and nowhere else.
export function ActivateAccountPage() {
    const { status, submit, reset } = useActivateAccount()

    if (status.kind === "success") {
        return (
            <main className="app-main">
                <section className="placeholder-page" aria-labelledby="activate-success-heading">
                    <h1 id="activate-success-heading">Account activated</h1>
                    <p>
                        Signed in as <strong>{status.result.login_name}</strong>. You can now sign in
                        with your chosen password.
                    </p>
                    <p>
                        <Link to="/login">Go to sign in</Link>
                    </p>
                </section>
            </main>
        )
    }

    return <ActivateForm status={status} submit={submit} reset={reset} />
}

// Owns the raw token and both password values, so they are discarded when
// the page swaps to the success view (this component unmounts).
function ActivateForm({
    status,
    submit,
    reset,
}: {
    status: Exclude<ActivateAccountStatus, { kind: "success" }>
    submit: ReturnType<typeof useActivateAccount>["submit"]
    reset: () => void
}) {
    // Lazy initializer, not an effect: StrictMode's second call sees an already
    // sanitized URL, and React keeps the first call's result.
    const [token] = useState<string | null>(captureFragmentToken)
    const [password, setPassword] = useState("")
    const [confirmation, setConfirmation] = useState("")
    const passwordFieldId = useId()
    const confirmFieldId = useId()
    const mismatchId = useId()


    if (token === null) {
        return (
            <main className="app-main">
                <section className="placeholder-page" aria-labelledby="activate-missing-heading">
                    <h1 id="activate-missing-heading">This activation link is not valid</h1>
                    <p>Check that you copied the entire link, including everything after the #.</p>
                </section>
            </main>
        )
    }

    const isSubmitting = status.kind === "pending"
    const mismatch = confirmation !== "" && confirmation !== password

    return (
        <main className="app-main">
            <section className="login-page" aria-labelledby="activate-heading">
                <div className="login-container">
                    <div className="login-box">
                        <h1 id="activate-heading" className="login-title">
                            Activate your account
                        </h1>
                        <p className="login-subtitle">Choose a password to finish setting up your account.</p>

                        <form
                            className="login-form"
                            aria-busy={isSubmitting}
                            onSubmit={(event) => {
                                event.preventDefault()
                                if (isSubmitting) {
                                    return
                                }
                                if (confirmation !== password) {
                                    document.getElementById(confirmFieldId)?.focus()
                                    return
                                }
                                submit(token, password)
                            }}
                        >
                            <PasswordField
                                id={passwordFieldId}
                                label="Choose a passphrase"
                                value={password}
                                onChange={(value) => {
                                    setPassword(value)
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
                                {isSubmitting ? statusMessage("pending") : "Activate account"}
                            </button>
                        </form>
                    </div>
                </div>
            </section>
        </main>
    )
}
