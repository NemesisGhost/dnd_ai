import { useId, useState } from "react"
import type { SyntheticEvent } from "react"
import { useRegisterInvitedAccount } from "../hooks/useRegisterInvitedAccount"
import type { RegisterInvitedAccountResponse } from "../types/invitationOnboarding"

interface InvitationOnboardingRegisterProps {
    onboardingCsrfToken: string
    onRegistered: (result: RegisterInvitedAccountResponse) => void
}

const _LOGIN_NAME_MIN_LENGTH = 3
const _LOGIN_NAME_MAX_LENGTH = 64
const _DISPLAY_NAME_MAX_LENGTH = 100
const _PASSWORD_MIN_LENGTH = 15

function statusMessage(
    kind:
        | "pending"
        | "policy_violation"
        | "login_name_taken"
        | "unavailable"
        | "denied"
        | "rate_limited"
        | "error",
): string {
    switch (kind) {
        case "pending":
            return "Creating your account…"
        case "policy_violation":
            return "Choose a login name of 3-64 lowercase letters/digits/./_/- and a passphrase of at least 15 characters that is not commonly used."
        case "login_name_taken":
            return "That login name was already claimed. Choose a different one."
        case "unavailable":
            return "This invitation is no longer available."
        case "denied":
            return "The request could not be completed."
        case "rate_limited":
            return "Too many attempts. Wait and try again."
        case "error":
            return "Registration failed. Try again."
    }
}

export function InvitationOnboardingRegister({
    onboardingCsrfToken,
    onRegistered,
}: InvitationOnboardingRegisterProps) {
    const { status, submit, reset } = useRegisterInvitedAccount(onRegistered)
    const [loginName, setLoginName] = useState("")
    const [displayName, setDisplayName] = useState("")
    const [password, setPassword] = useState("")
    const loginNameId = useId()
    const displayNameId = useId()
    const passwordId = useId()

    const isSubmitting = status.kind === "pending"

    function handleSubmit(event: SyntheticEvent<HTMLFormElement>): void {
        event.preventDefault()
        if (isSubmitting) {
            return
        }
        submit({ loginName, displayName, password, onboardingCsrfToken })
    }

    function clearErrorOnEdit(): void {
        if (status.kind !== "idle" && status.kind !== "pending") {
            reset()
        }
    }

    return (
        <form
            className="login-form"
            aria-label="Create an account"
            onSubmit={handleSubmit}
            aria-busy={isSubmitting}
        >
            <div className="form-group">
                <label htmlFor={loginNameId} className="form-label">
                    Choose a login name
                </label>
                <input
                    id={loginNameId}
                    type="text"
                    className="form-input"
                    autoComplete="username"
                    autoCapitalize="none"
                    spellCheck={false}
                    minLength={_LOGIN_NAME_MIN_LENGTH}
                    maxLength={_LOGIN_NAME_MAX_LENGTH}
                    value={loginName}
                    disabled={isSubmitting}
                    onChange={(event) => {
                        setLoginName(event.currentTarget.value)
                        clearErrorOnEdit()
                    }}
                    required
                />
            </div>

            <div className="form-group">
                <label htmlFor={displayNameId} className="form-label">
                    Display name
                </label>
                <input
                    id={displayNameId}
                    type="text"
                    className="form-input"
                    autoComplete="name"
                    minLength={1}
                    maxLength={_DISPLAY_NAME_MAX_LENGTH}
                    value={displayName}
                    disabled={isSubmitting}
                    onChange={(event) => {
                        setDisplayName(event.currentTarget.value)
                        clearErrorOnEdit()
                    }}
                    required
                />
            </div>

            <div className="form-group">
                <label htmlFor={passwordId} className="form-label">
                    Choose a passphrase
                </label>
                <input
                    id={passwordId}
                    type="password"
                    className="form-input"
                    autoComplete="new-password"
                    minLength={_PASSWORD_MIN_LENGTH}
                    value={password}
                    disabled={isSubmitting}
                    onChange={(event) => {
                        setPassword(event.currentTarget.value)
                        clearErrorOnEdit()
                    }}
                    required
                />
            </div>

            {status.kind !== "idle" && status.kind !== "pending" && status.kind !== "success" && (
                <p className="login-error" role="alert">
                    {statusMessage(status.kind)}
                </p>
            )}

            <button type="submit" className="login-button" disabled={isSubmitting}>
                {isSubmitting ? statusMessage("pending") : "Create account and join"}
            </button>
        </form>
    )
}
