import { useId, useState } from "react"
import { useCreateAccount } from "../hooks/useCreateAccount"
import { OneTimeSecretPanel } from "./OneTimeSecretPanel"
import { buildFragmentLink } from "../utils/oneTimeLink"
import type { CreateAccountResponse } from "../types/platformAccounts"
import { SYSTEM_ROLE_OPTIONS, type SystemRoleCode } from "../utils/systemAccess"

interface CreateAccountPanelProps {
    onCreated: () => void
    // True only while the server reports `system_roles.grant_admin`.
    canGrantAdmin?: boolean
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

export function CreateAccountPanel({ onCreated, canGrantAdmin = false }: CreateAccountPanelProps) {
    const loginNameId = useId()
    const displayNameId = useId()
    const emailId = useId()
    const [loginName, setLoginName] = useState("")
    const [displayName, setDisplayName] = useState("")
    const [email, setEmail] = useState("")
    const [created, setCreated] = useState<CreateAccountResponse | null>(null)
    // New accounts default to Player; at least one system role is always chosen.
    const [roles, setRoles] = useState<readonly SystemRoleCode[]>(["player"])

    const { status, submit, reset } = useCreateAccount((result) => {
        setCreated(result)
        setLoginName("")
        setDisplayName("")
        setEmail("")
        setRoles(["player"])
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
                if (
                    isPending ||
                    loginName.trim() === "" ||
                    displayName.trim() === "" ||
                    roles.length === 0
                ) {
                    return
                }
                submit(
                    loginName.trim(),
                    displayName.trim(),
                    email.trim() === "" ? null : email.trim(),
                    roles,
                )
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

            <fieldset disabled={isPending}>
                <legend>System roles</legend>
                {SYSTEM_ROLE_OPTIONS.map((option) => (
                    <label key={option.code}>
                        <input
                            type="checkbox"
                            checked={roles.includes(option.code)}
                            disabled={option.code === "admin" && !canGrantAdmin}
                            onChange={(event) => {
                                const checked = event.currentTarget.checked
                                setRoles((current) =>
                                    checked
                                        ? [...current, option.code]
                                        : current.filter((code) => code !== option.code),
                                )
                            }}
                        />{" "}
                        {option.label}
                    </label>
                ))}
                <p>
                    {canGrantAdmin
                        ? ""
                        : "Granting Administrator is done by the operator script on this deployment. "}
                    A system role never grants access to any campaign or world.
                </p>
            </fieldset>

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
