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
    selectedCount: number,
): string {
    switch (kind) {
        case "pending":
            return selectedCount === 1
                ? "Adding 1 member…"
                : `Adding ${selectedCount} members…`
        case "success":
            return "Members added to group."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This group's membership changed elsewhere. Reload the page to see the current state."
        case "error":
            return "The selected members could not be added. Try again."
    }
}

function addedMessage(addedCount: number): string {
    return addedCount === 1
        ? "1 member added to group."
        : `${addedCount} members added to group.`
}

export function AddAccessGroupMember({
    campaignId,
    accessGroupId,
    groupName,
    eligibleMembers,
    onChanged,
    onMutationStart,
}: AddAccessGroupMemberProps) {
    const checkboxGroupId = useId()
    const selectionCountId = useId()
    const statusId = useId()

    const [isEditing, setIsEditing] = useState(false)
    const [selectedMembershipIds, setSelectedMembershipIds] =
        useState<string[]>([])

    const eligibleMembershipIds = new Set(
        eligibleMembers.map(
            (member) => member.campaign_membership_id,
        ),
    )

    const validSelectedMembershipIds =
        selectedMembershipIds.filter((membershipId) =>
            eligibleMembershipIds.has(membershipId),
        )

    const { status, submit, reset } =
        useAddAccessGroupMember(
            campaignId,
            (addedCount) => {
                setSelectedMembershipIds([])
                setIsEditing(false)
                onChanged(addedMessage(addedCount))
            },
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
                    setSelectedMembershipIds([])
                    setIsEditing(true)
                }}
            >
                Add members
            </button>
        )
    }

    return (
        <form
            className="access-role-editor"
            onSubmit={(event) => {
                event.preventDefault()

                if (
                    validSelectedMembershipIds.length === 0
                ) {
                    return
                }

                onMutationStart()
                submit(
                    accessGroupId,
                    validSelectedMembershipIds,
                )
            }}
        >
            <fieldset
                className="access-group-member-picker"
                disabled={isPending}
                aria-describedby={`${selectionCountId} ${statusId}`}
            >
                <legend>
                    Add members to {groupName}
                </legend>

                <ul
                    id={checkboxGroupId}
                    className="access-group-member-picker__list"
                >
                    {eligibleMembers.map((member, index) => {
                        const checkboxId =
                            `${checkboxGroupId}-${index}`
                        const isSelected =
                            validSelectedMembershipIds.includes(
                                member.campaign_membership_id,
                            )

                        return (
                            <li
                                key={
                                    member.campaign_membership_id
                                }
                                className="access-group-member-picker__item"
                            >
                                <input
                                    id={checkboxId}
                                    className="access-group-member-picker__checkbox"
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={(event) => {
                                        if (
                                            event.currentTarget
                                                .checked
                                        ) {
                                            setSelectedMembershipIds(
                                                (
                                                    currentIds,
                                                ) => [
                                                        ...currentIds,
                                                        member.campaign_membership_id,
                                                    ],
                                            )
                                            return
                                        }

                                        setSelectedMembershipIds(
                                            (currentIds) =>
                                                currentIds.filter(
                                                    (
                                                        membershipId,
                                                    ) =>
                                                        membershipId !==
                                                        member.campaign_membership_id,
                                                ),
                                        )
                                    }}
                                />

                                <label htmlFor={checkboxId}>
                                    {member.display_name}
                                </label>
                            </li>
                        )
                    })}
                </ul>

                <p
                    id={selectionCountId}
                    className="access-group-member-picker__count"
                    aria-live="polite"
                >
                    {validSelectedMembershipIds.length ===
                        0
                        ? "No members selected."
                        : validSelectedMembershipIds.length ===
                            1
                            ? "1 member selected."
                            : `${validSelectedMembershipIds.length} members selected.`}
                </p>
            </fieldset>

            <div className="access-role-editor__actions">
                <button
                    type="submit"
                    disabled={
                        isPending ||
                        validSelectedMembershipIds.length ===
                        0
                    }
                    aria-busy={isPending}
                >
                    {isPending
                        ? "Adding…"
                        : "Add selected members"}
                </button>

                <button
                    type="button"
                    disabled={isPending}
                    onClick={() => {
                        reset()
                        setSelectedMembershipIds([])
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
                    : statusMessage(
                        status.kind,
                        validSelectedMembershipIds.length,
                    )}
            </p>
        </form>
    )
}