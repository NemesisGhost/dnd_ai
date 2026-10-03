import { useId, useState } from "react"
import { useCreateAccount } from "../hooks/useCreateAccount"
import { OneTimeSecretPanel } from "./OneTimeSecretPanel"
import { buildFragmentLink } from "../utils/oneTimeLink"
import type { CreateAccountResponse } from "../types/platformAccounts"

interface CreateAccountPanelProps {
    onCreated: () => void
}

function statusMessage(kind: "pending" | "denied" | "error"): string {
    switch (kind) {
        case "pending":
            return "Creating account…"
        case "denied":
            return "You do not have permission to create accounts."
        case "error":
            return "The account could not be created. Try again."
    }
}

export function CreateAccountPanel({ onCreated }: CreateAccountPanelProps) {
    const loginNameId = useId()
    const displayNameId = useId()
    const emailId = useId()
    const [loginName, setLoginName] = useState("")
    const [displayName, setDisplayName] = useState("")
    const [email, setEmail] = useState("")
    const [created, setCreated] = useState<CreateAccountResponse | null>(null)

    const { status, submit, reset } = useCreateAccount((result) => {
        setCreated(result)
        setLoginName("")
        setDisplayName("")
        setEmail("")
        onCreated()
    })

    const isPending = status.kind === "pending"

    if (created !== null) {
        return (
            <OneTimeSecretPanel
                heading="Copy the activation link now"
                description="This link is shown once and cannot be recovered later. Send it to the new account holder out of band."
                secretLabel="Activation link"
                secret={buildFragmentLink("/activate", created.raw_activation_token)}
                onDismiss={() => setCreated(null)}
            />
        )
    }

    return (
        <form
            className="access-role-editor"
            aria-label="Create account"
            onSubmit={(event) => {
                event.preventDefault()
                if (isPending || loginName.trim() === "" || displayName.trim() === "") {
                    return
                }
                submit(loginName.trim(), displayName.trim(), email.trim() === "" ? null : email.trim())
            }}
        >
            <label htmlFor={loginNameId}>Login name</label>
            <input
                id={loginNameId}
                type="text"
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                minLength={3}
                maxLength={64}
                value={loginName}
                disabled={isPending}
                onChange={(event) => {
                    setLoginName(event.currentTarget.value)
                    if (status.kind !== "idle") {
                        reset()
                    }
                }}
                required
            />

            <label htmlFor={displayNameId}>Display name</label>
            <input
                id={displayNameId}
                type="text"
                autoComplete="off"
                minLength={1}
                maxLength={100}
                value={displayName}
                disabled={isPending}
                onChange={(event) => {
                    setDisplayName(event.currentTarget.value)
                    if (status.kind !== "idle") {
                        reset()
                    }
                }}
                required
            />

            <label htmlFor={emailId}>Optional email label</label>
            <input
                id={emailId}
                type="text"
                autoComplete="off"
                value={email}
                disabled={isPending}
                onChange={(event) => {
                    setEmail(event.currentTarget.value)
                }}
            />

            <div className="access-role-editor__actions">
                <button type="submit" disabled={isPending} aria-busy={isPending}>
                    {isPending ? "Creating…" : "Create account"}
                </button>
            </div>

            <p
                className={
                    status.kind === "denied" || status.kind === "error"
                        ? "access-role-editor__status access-role-editor__status--error"
                        : "access-role-editor__status"
                }
                role="status"
                aria-live="polite"
            >
                {status.kind === "idle" || status.kind === "success" ? "" : statusMessage(status.kind)}
            </p>
        </form>
    )
}
