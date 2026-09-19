import { useId, useState } from "react"
import { useAssignMembershipRole } from "../hooks/useAssignMembershipRole"
import type { AssignableRole } from "../types/accessOverview"

interface AddMemberRoleProps {
    campaignId: string
    campaignName: string
    campaignMembershipId: string
    memberDisplayName: string
    assignableRoles: AssignableRole[]
    onChanged: (message: string) => void
    onMutationStart: () => void
}

function statusMessage(
    kind: "pending" | "success" | "denied" | "conflict" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Adding role…"
        case "success":
            return "Role added."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This member's roles changed elsewhere. Reload the page to see the current state."
        case "error":
            return "The role could not be added. Try again."
    }
}

// One control per member (never per role, unlike MemberRoleEditor/
// RevokeMemberRole below): "add a role" names a member and a role to add,
// not an existing assignment to act on. `assignableRoles` here is already
// narrowed to roles this member does not currently hold actively — see
// AccessPage's own derivation — so every option offered is a genuine,
// currently-possible addition; the server independently re-validates
// everything regardless (dnd_ai.commands.memberships.assign_membership_role).
export function AddMemberRole({
    campaignId,
    campaignName,
    campaignMembershipId,
    memberDisplayName,
    assignableRoles,
    onChanged,
    onMutationStart,
}: AddMemberRoleProps) {
    const selectId = useId()
    const statusId = useId()

    const [isEditing, setIsEditing] = useState(false)
    const [selectedRoleId, setSelectedRoleId] = useState(
        assignableRoles[0]?.role_id ?? "",
    )

    const { status, submit, reset } = useAssignMembershipRole(
        campaignId,
        () => onChanged("Role added."),
    )

    const isPending = status.kind === "pending"

    if (assignableRoles.length === 0) {
        // Every role this campaign could offer is already held — never
        // show a control with nothing left to add.
        return null
    }

    if (!isEditing) {
        return (
            <button
                type="button"
                className="access-role-editor__trigger"
                onClick={() => {
                    reset()
                    setSelectedRoleId(
                        assignableRoles[0]?.role_id ?? "",
                    )
                    setIsEditing(true)
                }}
            >
                Add role
            </button>
        )
    }

    return (
        <form
            className="access-role-editor"
            onSubmit={(event) => {
                event.preventDefault()
                if (selectedRoleId === "") {
                    return
                }
                onMutationStart()
                submit(campaignMembershipId, selectedRoleId)
            }}
        >
            <label htmlFor={selectId}>
                Add a role for {memberDisplayName} in{" "}
                {campaignName}
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
                {assignableRoles.map((role) => (
                    <option
                        key={role.role_id}
                        value={role.role_id}
                    >
                        {role.display_name}
                    </option>
                ))}
            </select>

            <div className="access-role-editor__actions">
                <button
                    type="submit"
                    disabled={
                        isPending || selectedRoleId === ""
                    }
                    aria-busy={isPending}
                >
                    {isPending ? "Adding…" : "Add"}
                </button>

                <button
                    type="button"
                    disabled={isPending}
                    onClick={() => {
                        reset()
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
