import { useId, useState } from "react"
import { useAddAccessGroupMember } from "../hooks/useAddAccessGroupMember"

export interface EligibleGroupMember {
    campaign_membership_id: string
    display_name: string
}

interface AddAccessGroupMemberProps {
    campaignId: string
    accessGroupId: string
    groupName: string
    eligibleMembers: EligibleGroupMember[]
    onChanged: (message: string) => void
    onMutationStart: () => void
}

function statusMessage(
    kind: "pending" | "success" | "denied" | "conflict" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Adding member…"
        case "success":
            return "Member added to group."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This group's membership changed elsewhere. Reload the page to see the current state."
        case "error":
            return "The member could not be added. Try again."
    }
}

// One control per group — "add a member" names an existing, active
// campaign member and the group to add them to. eligibleMembers is already
// narrowed by the caller (AccessPage) to currently active campaign members
// not already open in this group — presentation only; the server
// independently re-validates and re-locks the target membership and group
// regardless (dnd_ai.commands.access_groups.add_access_group_member).
export function AddAccessGroupMember({
    campaignId,
    accessGroupId,
    groupName,
    eligibleMembers,
    onChanged,
    onMutationStart,
}: AddAccessGroupMemberProps) {
    const selectId = useId()
    const statusId = useId()

    const [isEditing, setIsEditing] = useState(false)
    const [selectedMembershipIds, setSelectedMembershipIds] = useState<string[]>(
        eligibleMembers.length > 0 ? [eligibleMembers[0].campaign_membership_id] : [],
    )

    const { status, submit, reset } = useAddAccessGroupMember(campaignId, () =>
        onChanged("Members added to group."),
    )

    const isPending = status.kind === "pending"

    if (eligibleMembers.length === 0) {
        return null
    }

    if (!isEditing) {
        return (
            <button
                type="button"
                className="access-role-editor__trigger"
                onClick={() => {
                    reset()
                    setSelectedMembershipIds(
                        eligibleMembers.length > 0 ? [eligibleMembers[0].campaign_membership_id] : [],
                    )
                    setIsEditing(true)
                }}
            >
                Add member
            </button>
        )
    }

    return (
        <form
            className="access-role-editor"
            onSubmit={(event) => {
                event.preventDefault()
                if (selectedMembershipIds.length === 0) {
                    return
                }
                onMutationStart()
                submit(accessGroupId, selectedMembershipIds)
            }}
        >
            <label htmlFor={selectId}>Add members to {groupName}</label>

            <select
                id={selectId}
                value={selectedMembershipIds}
                multiple
                size={Math.min(eligibleMembers.length, 8)}
                disabled={isPending}
                aria-describedby={statusId}
                onChange={(event) => {
                    const nextIds = Array.from(
                        event.currentTarget.selectedOptions,
                        (option) => option.value,
                    )
                    setSelectedMembershipIds(nextIds)
                }}
            >
                {eligibleMembers.map((member) => (
                    <option
                        key={member.campaign_membership_id}
                        value={member.campaign_membership_id}
                    >
                        {member.display_name}
                    </option>
                ))}
            </select>

            <div className="access-role-editor__actions">
                <button
                    type="submit"
                    disabled={isPending || selectedMembershipIds.length === 0}
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
                {status.kind === "idle" ? "" : statusMessage(status.kind)}
            </p>
        </form>
    )
}
