import { useId, useState } from "react"
import { useChangeMembershipRole } from "../hooks/useChangeMembershipRole"
import type {
    AccessRoleSummary,
    AssignableRole,
} from "../types/accessOverview"

interface MemberRoleEditorProps {
    campaignId: string
    campaignName: string
    memberDisplayName: string
    role: AccessRoleSummary
    assignableRoles: AssignableRole[]
    onChanged: (message: string) => void
    onMutationStart: () => void
}

function statusMessage(
    kind:
        | "pending"
        | "success"
        | "denied"
        | "conflict"
        | "validation"
        | "error",
): string {
    switch (kind) {
        case "pending":
            return "Saving role change…"
        case "success":
            return "Role updated."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This role assignment changed elsewhere. Reload the page to see the current state."
        case "validation":
            return "That role can no longer be assigned. Reload the page to see the current choices."
        case "error":
            return "The role change could not be saved. Try again."
    }
}

// One editor per currently active role assignment (never per member): the
// backend contract changes exactly one `membership_role_id` at a time, so
// the UI never offers a single control that could silently replace every
// role a member holds — see dnd_ai.commands.memberships.
// change_membership_role's own docstring.
export function MemberRoleEditor({
    campaignId,
    campaignName,
    memberDisplayName,
    role,
    assignableRoles,
    onChanged,
    onMutationStart,
}: MemberRoleEditorProps) {
    const selectId = useId()
    const statusId = useId()

    const [isEditing, setIsEditing] = useState(false)
    const [selectedRoleId, setSelectedRoleId] =
        useState(role.role_id)

    const { status, submit, reset } = useChangeMembershipRole(
        campaignId,
        () => onChanged("Role updated."),
    )

    const isPending = status.kind === "pending"
    // Selecting the role the assignment already holds is not a change at
    // all — disabled here so the no-op never reaches the server in the
    // first place; dnd_ai.commands.memberships.change_membership_role
    // still rejects it server-side (422) as defense in depth.
    const isUnchangedSelection = selectedRoleId === role.role_id

    if (assignableRoles.length === 0) {
        // Nothing the contract marks as an eligible target — never show a
        // control with nowhere safe to send it.
        return null
    }

    if (!isEditing) {
        return (
            <button
                type="button"
                className="access-role-editor__trigger"
                onClick={() => {
                    reset()
                    setSelectedRoleId(role.role_id)
                    setIsEditing(true)
                }}
            >
                Change role
            </button>
        )
    }

    return (
        <form
            className="access-role-editor"
            onSubmit={(event) => {
                event.preventDefault()
                if (isUnchangedSelection) {
                    return
                }
                onMutationStart()
                submit(role.membership_role_id, selectedRoleId)
            }}
        >
            <label htmlFor={selectId}>
                Change {memberDisplayName}'s{" "}
                {role.display_name} role in {campaignName}
            </label>

            <select
                id={selectId}
                value={selectedRoleId}
                disabled={isPending}
                onChange={(event) => {
                    setSelectedRoleId(
                        event.currentTarget.value,
                    )
                }}
            >
                {assignableRoles.map((assignableRole) => (
                    <option
                        key={assignableRole.role_id}
                        value={assignableRole.role_id}
                    >
                        {assignableRole.display_name}
                    </option>
                ))}
            </select>

            <div className="access-role-editor__actions">
                <button
                    type="submit"
                    disabled={isPending || isUnchangedSelection}
                    aria-busy={isPending}
                >
                    {isPending ? "Saving…" : "Save"}
                </button>

                <button
                    type="button"
                    disabled={isPending}
                    onClick={() => {
                        reset()
                        setSelectedRoleId(role.role_id)
                        setIsEditing(false)
                    }}
                >
                    Cancel
                </button>
            </div>

            <p
                id={statusId}
                className={
                    status.kind === "denied" ||
                    status.kind === "conflict" ||
                    status.kind === "validation" ||
                    status.kind === "error"
                        ? "access-role-editor__status access-role-editor__status--error"
                        : "access-role-editor__status"
                }
                role="status"
                aria-live="polite"
            >
                {status.kind === "idle"
                    ? ""
                    : statusMessage(status.kind)}
            </p>
        </form>
    )
}
