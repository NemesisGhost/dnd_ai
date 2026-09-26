import { useId, useState } from "react"
import { Link } from "react-router"
import { PasswordField } from "../components/PasswordField"
import { useActivateAccount } from "../hooks/useActivateAccount"
import PlaceholderPage from "./PlaceholderPage"

const _HASH_TOKEN_PREFIX = "#token="

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

function extractTokenFromLocationHash(): string | null {
    const hash = window.location.hash
    if (!hash.startsWith(_HASH_TOKEN_PREFIX)) {
        return null
    }
    const extracted = decodeURIComponent(hash.slice(_HASH_TOKEN_PREFIX.length))
    // Clears the fragment before this component ever fires a request, so
    // the token never appears in the address bar or session history
    // (R-1/R-2 discipline, mirroring AcceptCampaignInvitationPage). Called
    // from a useState lazy initializer rather than an effect: React 18
    // StrictMode double-invokes both, but window.location.hash is already
    // empty by the second call (this function's own replaceState made it
    // so), which is what makes a second call a safe no-op without a
    // separate ref latch.
    window.history.replaceState(null, "", window.location.pathname + window.location.search)
    return extracted
}

// Public route: reads the activation token from the URL fragment exactly
// once (see extractTokenFromLocationHash above). No server-side
// continuation exists for this token (dnd_ai.api.local_auth's own
// single-shot /auth/activate), so the extracted value lives in this
// component's own state for the life of the form and nowhere else.
export function ActivateAccountPage() {
    const [hadHash] = useState(() => window.location.hash.startsWith(_HASH_TOKEN_PREFIX))
    const [token] = useState<string | null>(extractTokenFromLocationHash)
    const [password, setPassword] = useState("")
    const passwordFieldId = useId()

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

    if (!hadHash) {
        return (
            <main className="app-main">
                <section className="placeholder-page" aria-labelledby="activate-missing-heading">
                    <h1 id="activate-missing-heading">This activation link is not valid</h1>
                    <p>Check that you copied the entire link, including everything after the #.</p>
                </section>
            </main>
        )
    }

    if (token === null) {
        return (
            <main className="app-main">
                <PlaceholderPage
                    title="Opening your activation link"
                    description="Reading the activation link."
                />
            </main>
        )
    }

    const isSubmitting = status.kind === "pending"

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
