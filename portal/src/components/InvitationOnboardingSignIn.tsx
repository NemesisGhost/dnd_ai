import { useId, useState } from "react"
import type { SyntheticEvent } from "react"
import { useLogin } from "../hooks/useLogin"

interface InvitationOnboardingSignInProps {
    // Called only after a successful sign-in, once useLogin's own reload()
    // has been fired -- the parent page re-reads onboarding status so
    // next_action reflects the newly authenticated session.
    onSignedIn: () => void
}

export function InvitationOnboardingSignIn({ onSignedIn }: InvitationOnboardingSignInProps) {
    const { state, submit } = useLogin()
    const [loginName, setLoginName] = useState("")
    const [password, setPassword] = useState("")
    const loginNameId = useId()
    const passwordId = useId()

    const isSubmitting = state.status === "submitting" || state.status === "complete"

    async function handleSubmit(event: SyntheticEvent<HTMLFormElement>): Promise<void> {
        event.preventDefault()

        const succeeded = await submit({ login_name: loginName, password })
        setPassword("")

        if (succeeded) {
            setLoginName("")
            onSignedIn()
        }
    }

    return (
        <form
            className="login-form"
            aria-label="Sign in to your account"
            onSubmit={(event) => void handleSubmit(event)}
            aria-busy={isSubmitting}
        >
            <div className="form-group">
                <label htmlFor={loginNameId} className="form-label">
                    Login name
                </label>
                <input
                    id={loginNameId}
                    type="text"
                    className="form-input"
                    autoComplete="username"
                    autoCapitalize="none"
                    spellCheck={false}
                    value={loginName}
                    disabled={isSubmitting}
                    onChange={(event) => {
                        setLoginName(event.currentTarget.value)
                    }}
                    required
                />
            </div>

            <div className="form-group">
                <label htmlFor={passwordId} className="form-label">
                    Password
                </label>
                <input
                    id={passwordId}
                    type="password"
                    className="form-input"
                    autoComplete="current-password"
                    value={password}
                    disabled={isSubmitting}
                    onChange={(event) => {
                        setPassword(event.currentTarget.value)
                    }}
                    required
                />
            </div>

            {state.status === "error" && (
                <p className="login-error" role="alert">
                    {state.message}
                </p>
            )}

            <button type="submit" className="login-button" disabled={isSubmitting}>
                {isSubmitting ? "Signing in…" : "Sign in"}
            </button>
        </form>
    )
}
