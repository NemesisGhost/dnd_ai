import {
    useState,
} from "react"
import type {
    SyntheticEvent,
} from "react"
import { Link, Navigate } from "react-router"
import { useSession } from "../context/SessionContext"
import { useInvitationOnboardingStatus } from "../hooks/useInvitationOnboardingStatus"
import { useLogin } from "../hooks/useLogin"
import PlaceholderPage from "./PlaceholderPage"

// Fixed internal destinations -- never derived from the URL, a query
// parameter, or history state, so Login can never be made an open redirect.
const ORDINARY_LOGIN_DESTINATION = "/campaigns"
const INVITATION_CONTINUATION_DESTINATION = "/campaign-invitations/accept"

export function LoginPage() {
    const {
        state: sessionState,
        reload,
    } = useSession()

    const {
        state: loginState,
        submit,
    } = useLogin()

    // Once signed in, ask the server whether this browser still holds a live
    // invitation-onboarding continuation (its opaque cookie is HttpOnly, so
    // only the server can say). Yes: resume the invitation workflow instead
    // of the ordinary destination. No: the ordinary destination, unchanged.
    const invitationContinuation = useInvitationOnboardingStatus({
        enabled: sessionState.status === "authenticated",
    })

    const [loginName, setLoginName] = useState("")
    const [password, setPassword] = useState("")

    const isSubmitting =
        loginState.status === "submitting" ||
        loginState.status === "complete"

    async function handleSubmit(
        event: SyntheticEvent<HTMLFormElement>
    ) {
        event.preventDefault()

        const succeeded = await submit({
            login_name: loginName,
            password,
        })

        setPassword("")

        if (succeeded) {
            setLoginName("")
        }
    }

    if (sessionState.status === "loading") {
        return (
            <PlaceholderPage
                title="Loading portal"
                description="Checking your current session."
            />
        )
    }

    if (sessionState.status === "authenticated") {
        if (invitationContinuation.state.status === "loading") {
            return (
                <PlaceholderPage
                    title="Signing you in"
                    description="Checking for a pending invitation."
                />
            )
        }

        if (invitationContinuation.state.status === "success") {
            return <Navigate to={INVITATION_CONTINUATION_DESTINATION} replace />
        }

        if (invitationContinuation.state.status === "error") {
            // Cannot tell whether an invitation is waiting; say so rather
            // than silently dropping it by following the ordinary route.
            return (
                <section
                    className="login-page"
                    aria-labelledby="continuation-error-heading"
                >
                    <div className="login-container">
                        <div className="login-box">
                            <h1
                                id="continuation-error-heading"
                                className="login-title"
                            >
                                Signed in
                            </h1>

                            <p className="login-subtitle">
                                We could not check for a pending invitation.
                            </p>

                            <button
                                type="button"
                                className="login-button"
                                onClick={invitationContinuation.retry}
                            >
                                Try again
                            </button>

                            <p>
                                <Link to={ORDINARY_LOGIN_DESTINATION}>Continue to campaigns</Link>
                            </p>
                        </div>
                    </div>
                </section>
            )
        }

        return <Navigate to={ORDINARY_LOGIN_DESTINATION} replace />
    }

    if (sessionState.status === "error") {
        return (
            <section
                className="login-page"
                aria-labelledby="session-error-heading"
            >
                <div className="login-container">
                    <div className="login-box">
                        <h1
                            id="session-error-heading"
                            className="login-title"
                        >
                            Portal unavailable
                        </h1>

                        <p className="login-subtitle">
                            Your session could not be checked.
                        </p>

                        <button
                            type="button"
                            className="login-button"
                            onClick={reload}
                        >
                            Try again
                        </button>
                    </div>
                </div>
            </section>
        )
    }

    return (
        <section
            className="login-page"
            aria-labelledby="login-heading"
        >
            <div className="login-container">
                <div className="login-box">
                    <h1
                        id="login-heading"
                        className="login-title"
                    >
                        D&amp;D AI World
                    </h1>

                    <p className="login-subtitle">
                        Sign in to your account
                    </p>

                    <form
                        className="login-form"
                        onSubmit={handleSubmit}
                        aria-busy={isSubmitting}
                    >
                        <div className="form-group">
                            <label
                                htmlFor="login-name"
                                className="form-label"
                            >
                                Email or Username
                            </label>

                            <input
                                id="login-name"
                                name="username"
                                type="text"
                                className="form-input"
                                placeholder="Enter your email or username"
                                autoComplete="username"
                                autoCapitalize="none"
                                spellCheck={false}
                                value={loginName}
                                onChange={(event) => {
                                    setLoginName(event.currentTarget.value)
                                }}
                                disabled={isSubmitting}
                                required
                            />
                        </div>

                        <div className="form-group">
                            <label
                                htmlFor="password"
                                className="form-label"
                            >
                                Password
                            </label>

                            <input
                                id="password"
                                name="password"
                                type="password"
                                className="form-input"
                                placeholder="Enter your password"
                                autoComplete="current-password"
                                value={password}
                                onChange={(event) => {
                                    setPassword(event.currentTarget.value)
                                }}
                                disabled={isSubmitting}
                                required
                            />
                        </div>

                        {loginState.status === "error" && (
                            <p
                                className="login-error"
                                role="alert"
                            >
                                {loginState.message}
                            </p>
                        )}

                        <button
                            type="submit"
                            className="login-button"
                            disabled={isSubmitting}
                        >
                            {isSubmitting
                                ? "Signing in\u2026"
                                : "Sign In"}
                        </button>
                    </form>
                </div>
            </div>
        </section>
    )
}