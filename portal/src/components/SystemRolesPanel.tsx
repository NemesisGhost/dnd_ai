import { useEffect, useId, useRef } from "react"
import type { PlatformAccount } from "../types/platformAccounts"
import { SYSTEM_ROLE_OPTIONS } from "../utils/systemAccess"
import type { SystemRoleCode } from "../utils/systemAccess"
import { describeChange, isDirty, stagedChanges } from "../utils/systemRoleStaging"

interface SystemRolesPanelProps {
    // The roles the account held when editing began (the baseline); never changed by ticking.
    account: PlatformAccount
    draft: readonly SystemRoleCode[]
    // True when this is the signed-in account (its own Administrator removal is ordered last).
    ownAccount: boolean
    // True only while the server reports `system_roles.grant_admin`.
    canGrantAdmin: boolean
    // The id the page's disabled Edit roles buttons point at to explain why they are disabled.
    reasonId: string
    // Changes every time Edit roles is pressed for this account, so the heading takes focus again.
    focusSignal: number
    onToggle: (code: SystemRoleCode, checked: boolean) => void
    // Cancel (dirty) restores the baseline and closes; Close (clean) just closes. Neither sends anything.
    onCancel: () => void
    onClose: () => void
}

const ADMIN_NOTE = "Granting Administrator is done by the operator script on this deployment."

// One account's system roles, staged locally. Nothing in this panel is sent anywhere: it sits above the
// accounts table (never inside a row), so a list reload cannot unmount it. A system role never grants
// membership in a campaign or authority over a world.
export function SystemRolesPanel({
    account,
    draft,
    ownAccount,
    canGrantAdmin,
    reasonId,
    focusSignal,
    onToggle,
    onCancel,
    onClose,
}: SystemRolesPanelProps) {
    const headingId = useId()
    const noteId = useId()
    const changesId = useId()
    const headingRef = useRef<HTMLHeadingElement>(null)

    useEffect(() => {
        headingRef.current?.focus()
    }, [focusSignal])

    const dirty = isDirty(account.system_roles, draft)
    const changes = stagedChanges(account.system_roles, draft, ownAccount)
    const baseline = new Set(account.system_roles)

    return (
        <section aria-labelledby={headingId} className="admin-accounts__roles-panel">
            <h2 id={headingId} ref={headingRef} tabIndex={-1}>
                System roles for {account.display_name}
            </h2>
            <fieldset aria-describedby={noteId} className="admin-accounts__roles">
                <legend>Roles</legend>
                {SYSTEM_ROLE_OPTIONS.map((option) => {
                    const checked = draft.includes(option.code)
                    // An already-held Administrator role may always be removed; only a new grant is gated by the
                    // deployment setting.
                    const adminLocked = option.code === "admin" && !baseline.has("admin") && !canGrantAdmin
                    return (
                        <label key={option.code}>
                            <input
                                type="checkbox"
                                checked={checked}
                                disabled={adminLocked}
                                onChange={(event) => onToggle(option.code, event.currentTarget.checked)}
                            />{" "}
                            {option.label}
                        </label>
                    )
                })}
                <p id={noteId} className="admin-accounts__roles-note">
                    {canGrantAdmin ? "" : `${ADMIN_NOTE} `}A system role never grants access to any campaign or world.
                </p>
            </fieldset>
            <p>Changes are saved one at a time; some can be saved while others are not.</p>

            {dirty ? (
                <>
                    <p id={changesId}>Changes not saved yet</p>
                    <ul aria-labelledby={changesId}>
                        {changes.map((change) => (
                            <li key={change.code}>{describeChange(change)}</li>
                        ))}
                    </ul>
                    <p id={reasonId}>Save or cancel these changes before editing another account.</p>
                </>
            ) : (
                <p>No changes</p>
            )}

            <div className="authoring-actions">
                {dirty ? (
                    <button type="button" className="authoring-button" onClick={onCancel}>
                        Cancel
                    </button>
                ) : (
                    <button type="button" className="authoring-button" onClick={onClose}>
                        Close
                    </button>
                )}
            </div>
        </section>
    )
}
