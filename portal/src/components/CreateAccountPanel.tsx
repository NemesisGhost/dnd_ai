import { useEffect, useId, useRef, useState } from "react"
import { useNavigate } from "react-router"
import { useCreateAccount } from "../hooks/useCreateAccount"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import { ACCOUNTS_FOCUS_STATE } from "../navigation/platformAccountsReturn"
import { ConfirmDialog } from "./authoring/ConfirmDialog"
import { OneTimeSecretPanel } from "./OneTimeSecretPanel"
import { buildFragmentLink } from "../utils/oneTimeLink"
import type { CreateAccountResponse } from "../types/platformAccounts"
import { SYSTEM_ROLE_OPTIONS, type SystemRoleCode } from "../utils/systemAccess"

interface CreateAccountPanelProps {
    // The validated list address Cancel and Back to accounts go to (rebuilt by the page, never router state
    // as written).
    returnTo: { pathname: string; search: string }
    // True only while the server reports `system_roles.grant_admin`.
    canGrantAdmin?: boolean
}

type VisibleStatus = "pending" | "denied" | "error" | "unknown"

function statusMessage(kind: VisibleStatus): string {
    switch (kind) {
        case "pending":
            return "Creating account…"
        case "denied":
            return "You do not have permission to create accounts."
        case "error":
            return "The account could not be created. Try again."
        case "unknown":
            return "We could not confirm whether the account was created. Check the account list before trying again: creating it again would add a second account."
    }
}

const DEFAULT_ROLES: readonly SystemRoleCode[] = ["player"]

function isDefaultRoles(roles: readonly SystemRoleCode[]): boolean {
    return roles.length === DEFAULT_ROLES.length && DEFAULT_ROLES.every((code) => roles.includes(code))
}

interface CreatedAccount {
    response: CreateAccountResponse
    displayName: string
}

// The creation form and, once an account exists, its one-time activation link. The link is held in this
// component's memory only: never in an address, router state, storage or an announcement. Leaving with
// unsaved input, while the request is pending, or while the link is shown is asked about.
export function CreateAccountPanel({ returnTo, canGrantAdmin = false }: CreateAccountPanelProps) {
    const navigate = useNavigate()
    const loginNameId = useId()
    const displayNameId = useId()
    const emailId = useId()
    const loginRef = useRef<HTMLInputElement>(null)
    const submitRef = useRef<HTMLButtonElement>(null)
    const focusLoginNext = useRef(false)
    const [loginName, setLoginName] = useState("")
    const [displayName, setDisplayName] = useState("")
    const [email, setEmail] = useState("")
    const [created, setCreated] = useState<CreatedAccount | null>(null)
    // New accounts default to Player; at least one system role is always chosen.
    const [roles, setRoles] = useState<readonly SystemRoleCode[]>(DEFAULT_ROLES)

    const { status, submit, reset } = useCreateAccount((result) => {
        setCreated({ response: result, displayName: displayName.trim() })
        setLoginName("")
        setDisplayName("")
        setEmail("")
        setRoles(DEFAULT_ROLES)
    })

    const isPending = status.kind === "pending"
    const isDirty = loginName !== "" || displayName !== "" || email !== "" || !isDefaultRoles(roles)
    const guard = useUnsavedChangesGuard(isDirty || isPending || created !== null)

    // After a refusal or an unknown outcome the submit button is enabled again and keeps focus; if focus was
    // lost while the fields were disabled it returns there. A control the person moved to keeps it.
    const previousKind = useRef(status.kind)
    useEffect(() => {
        const before = previousKind.current
        previousKind.current = status.kind
        if (
            before !== "pending" ||
            (status.kind !== "error" && status.kind !== "denied" && status.kind !== "unknown")
        ) {
            return
        }
        const active = document.activeElement
        if (active === null || active === document.body) {
            submitRef.current?.focus()
        }
    }, [status.kind])

    // Create another account: the empty form, with focus on Login name.
    useEffect(() => {
        if (created === null && focusLoginNext.current) {
            focusLoginNext.current = false
            loginRef.current?.focus()
        }
    }, [created])

    function leave() {
        guard.release()
        void navigate(returnTo, { state: ACCOUNTS_FOCUS_STATE })
    }

    const dialog = isPending
        ? {
              title: "Leave while the account is being created?",
              description: "The account may still be created, but its activation link will not be shown.",
              confirmLabel: "Leave",
              cancelLabel: "Stay",
          }
        : created !== null
          ? {
                title: "Leave without the activation link?",
                description: "It is shown once and cannot be shown again.",
                confirmLabel: "Leave",
                cancelLabel: "Stay",
            }
          : {
                title: "Discard unsaved changes?",
                description: "You have entered details for a new account that have not been created.",
                confirmLabel: "Discard changes",
                cancelLabel: "Keep editing",
            }

    const confirm = (
        <ConfirmDialog
            open={guard.blocked}
            title={dialog.title}
            description={dialog.description}
            confirmLabel={dialog.confirmLabel}
            cancelLabel={dialog.cancelLabel}
            onConfirm={guard.discard}
            onCancel={guard.stay}
        />
    )

    if (created !== null) {
        return (
            <>
                <OneTimeSecretPanel
                    heading={`Copy the activation link for ${created.displayName} now`}
                    description={`This link is for ${created.displayName} only, is shown once, and cannot be recovered later. Send it to the new account holder out of band.`}
                    secretLabel="Activation link"
                    secret={buildFragmentLink("/activate", created.response.raw_activation_token)}
                    focusHeading
                    actions={
                        <>
                            <button type="button" onClick={leave}>
                                Back to accounts
                            </button>
                            <button
                                type="button"
                                onClick={() => {
                                    focusLoginNext.current = true
                                    reset()
                                    setCreated(null)
                                }}
                            >
                                Create another account
                            </button>
                        </>
                    }
                />
                {confirm}
            </>
        )
    }

    return (
        <>
            <form
                className="authoring-form"
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
                <div className="authoring-field">
                    <label htmlFor={loginNameId} className="authoring-field__label">Login name</label>
                    <input
                        ref={loginRef}
                        className="authoring-field__control"
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
                            // An outcome the portal could not confirm stays until a press replaces it.
                            if (status.kind !== "idle" && status.kind !== "unknown") {
                                reset()
                            }
                        }}
                        required
                    />
                </div>

                <div className="authoring-field">
                    <label htmlFor={displayNameId} className="authoring-field__label">Display name</label>
                    <input
                        className="authoring-field__control"
                        id={displayNameId}
                        type="text"
                        autoComplete="off"
                        minLength={1}
                        maxLength={100}
                        value={displayName}
                        disabled={isPending}
                        onChange={(event) => {
                            setDisplayName(event.currentTarget.value)
                            if (status.kind !== "idle" && status.kind !== "unknown") {
                                reset()
                            }
                        }}
                        required
                    />
                </div>

                <div className="authoring-field">
                    <label htmlFor={emailId} className="authoring-field__label">Optional email label</label>
                    <input
                        className="authoring-field__control"
                        id={emailId}
                        type="text"
                        autoComplete="off"
                        value={email}
                        disabled={isPending}
                        onChange={(event) => {
                            setEmail(event.currentTarget.value)
                        }}
                    />
                </div>

                <fieldset className="authoring-field" disabled={isPending}>
                    <legend className="authoring-field__label">System roles</legend>
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

                <div className="authoring-actions">
                    <button
                        ref={submitRef}
                        type="submit"
                        className="authoring-button authoring-button--primary"
                        disabled={isPending}
                        aria-busy={isPending}
                    >
                        {isPending ? "Creating…" : "Create account"}
                    </button>
                    <button
                        type="button"
                        className="authoring-button"
                        onClick={() => void navigate(returnTo, { state: ACCOUNTS_FOCUS_STATE })}
                    >
                        Cancel
                    </button>
                </div>

                <p
                    className={
                        status.kind === "denied" || status.kind === "error" || status.kind === "unknown"
                            ? "access-role-editor__status access-role-editor__status--error"
                            : "access-role-editor__status"
                    }
                    role="status"
                    aria-live="polite"
                >
                    {status.kind === "idle" || status.kind === "success" ? "" : statusMessage(status.kind)}
                </p>
            </form>
            {confirm}
        </>
    )
}
