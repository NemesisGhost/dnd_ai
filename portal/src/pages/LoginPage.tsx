import {
    useState,
} from "react"
import type {
    SyntheticEvent,
} from "react"
import { Navigate } from "react-router"
import { useSession } from "../context/SessionContext"
import { useLogin } from "../hooks/useLogin"
import PlaceholderPage from "./PlaceholderPage"

export function LoginPage() {
    const {
        state: sessionState,
        reload,
    } = useSession()

    const {
        state: loginState,
        submit,
    } = useLogin()

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
        return <Navigate to="/campaigns" replace />
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