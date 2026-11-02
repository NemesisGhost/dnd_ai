import { useId } from "react"
import { useSystemRoleChange } from "../hooks/useSystemRoleChange"
import type { PlatformAccount } from "../types/platformAccounts"
import { SYSTEM_ROLE_OPTIONS } from "../utils/systemAccess"

interface SystemRolesEditorProps {
    account: PlatformAccount
    // True only while the server reports `system_roles.grant_admin`; otherwise the
    // Administrator checkbox is disabled with the operator-script explanation.
    canGrantAdmin: boolean
    onChanged: () => void
}

const ADMIN_NOTE = "Granting Administrator is done by the operator script on this deployment."

// A system role is an account classification plus a few platform capabilities. It
// never grants membership in a campaign or authority over a world, and revoking
// one never touches campaign or world roles.
export function SystemRolesEditor({ account, canGrantAdmin, onChanged }: SystemRolesEditorProps) {
    const noteId = useId()
    const { status, change } = useSystemRoleChange(onChanged)
    const held = new Set(account.system_roles)
    const pending = status.kind === "pending"

    return (
        <fieldset aria-describedby={noteId} className="admin-accounts__roles">
            <legend>System roles for {account.display_name}</legend>
            {SYSTEM_ROLE_OPTIONS.map((option) => {
                const checked = held.has(option.code)
                // An already-held Administrator role may always be revoked; only a
                // new grant is gated by the deployment setting.
                const adminLocked = option.code === "admin" && !checked && !canGrantAdmin
                return (
                    <label key={option.code}>
                        <input
                            type="checkbox"
                            checked={checked}
                            disabled={pending || adminLocked}
                            onChange={(event) =>
                                change(account.user_id, option.code, event.currentTarget.checked)
                            }
                        />{" "}
                        {option.label}
                    </label>
                )
            })}
            <p id={noteId} className="admin-accounts__roles-note">
                {canGrantAdmin ? "" : `${ADMIN_NOTE} `}A system role never grants access to any
                campaign or world.
            </p>
            <p role="status" aria-live="polite">
                {status.kind === "denied" && "You do not have permission to change this role."}
                {status.kind === "conflict" && status.message}
                {status.kind === "error" && "The role could not be changed. Try again."}
            </p>
        </fieldset>
    )
}
