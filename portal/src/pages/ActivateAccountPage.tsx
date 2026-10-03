import { useCallback, useEffect, useId, useRef, useState } from "react"
import type { ReactNode } from "react"
import { Link } from "react-router"
import { PasswordField } from "../components/PasswordField"
import { useActivateAccount } from "../hooks/useActivateAccount"
import type { ActivateAccountStatus } from "../hooks/useActivateAccount"
import { useActivationLinkCheck } from "../hooks/useActivationLinkCheck"
import { captureFragmentToken } from "../utils/fragmentToken"

const INVALID_LINK_MESSAGE = "This activation link is invalid, expired, or has already been used."

function statusMessage(kind: "pending" | "policy_violation" | "rate_limited" | "error"): string {
    switch (kind) {
        case "pending":
            return "Activating…"
        case "policy_violation":
            return "Choose a passphrase of at least 15 characters that is not commonly used."
        case "rate_limited":
            return "Too many attempts. Wait and try again."
        case "error":
            return "The account could not be activated. Try again."
    }
}

interface ActivationLink {
    // Identity of this link, so a response for an older link can never apply to a newer one.
    id: number
    // Held only in memory; set to null as soon as the link is known to be unusable.
    token: string | null
}

let nextLinkId = 0

function newLink(token: string | null): ActivationLink {
    nextLinkId += 1
    return { id: nextLinkId, token }
}

// Moves focus to the heading once, when a state's view mounts. Each state
// renders its own keyed view, so re-renders within a state never refocus.
function StateHeading({ id, children }: { id: string; children: ReactNode }) {
    const ref = useRef<HTMLHeadingElement>(null)
    useEffect(() => {
        ref.current?.focus()
    }, [])
    return (
        <h1 id={id} ref={ref} tabIndex={-1}>
            {children}
        </h1>
    )
}

function Notice({ headingId, heading, children }: { headingId: string; heading: string; children: ReactNode }) {
    return (
        <main className="app-main">
            <section className="placeholder-page" aria-labelledby={headingId}>
                <StateHeading id={headingId}>{heading}</StateHeading>
                {children}
            </section>
        </main>
    )
}

// Public route. The fragment token is read once (see captureFragmentToken),
// then checked with a read-only, advisory request before any password field is
// rendered. POST /auth/activate remains authoritative and repeats every check.
// The token lives only in this component's state, never in storage or the URL.
export function ActivateAccountPage() {
    // Lazy initializer, not an effect: StrictMode's second call sees an already
    // sanitized URL, and React keeps the first call's result.
    const [link, setLink] = useState<ActivationLink>(() => newLink(captureFragmentToken()))
    // Drop the raw token as soon as it is known to be unusable.
    const dropToken = useCallback(() => {
        setLink((current) => ({ ...current, token: null }))
    }, [])
    const dropTokenOfLink = useCallback((linkId: number) => {
        setLink((current) => (current.id === linkId ? { ...current, token: null } : current))
    }, [])
    const { status: activation, submit, reset } = useActivateAccount(dropToken)
    const { status: check, retry } = useActivationLinkCheck(link.id, link.token, dropTokenOfLink)

    // A second activation URL opened in the same tab replaces the first.
    useEffect(() => {
        const onHashChange = () => {
            const token = captureFragmentToken()
            if (token !== null) {
                reset()
                setLink(newLink(token))
            }
        }
        window.addEventListener("hashchange", onHashChange)
        return () => window.removeEventListener("hashchange", onHashChange)
    }, [reset])

    const unusable = check === "invalid" || activation.kind === "unavailable"
    const hasToken = link.token !== null

    if (activation.kind === "success") {
        return (
            <Notice key="success" headingId="activate-success-heading" heading="Account activated">
                <p>
                    Signed in as <strong>{activation.result.login_name}</strong>. You can now sign in with your
                    chosen password.
                </p>
                <p>
                    <Link to="/login">Go to sign in</Link>
                </p>
            </Notice>
        )
    }

    if (unusable) {
        return (
            <Notice key="invalid" headingId="activate-invalid-heading" heading="This activation link is not valid">
                <p>{INVALID_LINK_MESSAGE}</p>
                <p>Ask an administrator for a new activation link.</p>
            </Notice>
        )
    }

    if (!hasToken) {
        return (
            <Notice key="missing" headingId="activate-missing-heading" heading="This activation link is not valid">
                <p>Check that you copied the entire link, including everything after the #.</p>
                <p>
                    The link is removed from the address bar when this page opens, so refreshing the page
                    cannot recover it. Open the original link again.
                </p>
            </Notice>
        )
    }

    if (check === "checking") {
        return (
            <Notice key="checking" headingId="activate-checking-heading" heading="Activate your account">
                <p role="status">Checking activation link…</p>
            </Notice>
        )
    }

    if (check === "error") {
        return (
            <Notice key="check-error" headingId="activate-check-error-heading" heading="Activate your account">
                <p role="alert">We could not check this activation link. This is not a problem with the link itself.</p>
                <button type="button" className="login-button" onClick={retry}>
                    Retry
                </button>
            </Notice>
        )
    }

    return <ActivateForm key={link.id} token={link.token ?? ""} status={activation} submit={submit} reset={reset} />
}

// Owns both password values, so they are discarded when the page leaves the
// ready state (this component unmounts).
function ActivateForm({
    token,
    status,
    submit,
    reset,
}: {
    token: string
    status: Exclude<ActivateAccountStatus, { kind: "success" } | { kind: "unavailable" }>
    submit: ReturnType<typeof useActivateAccount>["submit"]
    reset: () => void
}) {
    const [password, setPassword] = useState("")
    const [confirmation, setConfirmation] = useState("")
    const passwordFieldId = useId()
    const confirmFieldId = useId()
    const mismatchId = useId()

    const isSubmitting = status.kind === "pending"
    const mismatch = confirmation !== "" && confirmation !== password

    return (
        <main className="app-main">
            <section className="login-page" aria-labelledby="activate-heading">
                <div className="login-container">
                    <div className="login-box">
                        <StateHeading id="activate-heading">Set passphrase</StateHeading>
                        <p className="login-subtitle">Choose a passphrase to finish setting up your account.</p>

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
