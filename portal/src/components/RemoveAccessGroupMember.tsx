import { useEffect, useId, useRef, useState } from "react"
import { useRemoveAccessGroupMember } from "../hooks/useRemoveAccessGroupMember"

interface RemoveAccessGroupMemberProps {
    campaignId: string
    accessGroupMembershipId: string
    memberDisplayName: string
    groupName: string
    onChanged: (message: string) => void
    onMutationStart: () => void
}

function statusMessage(
    kind: "pending" | "success" | "denied" | "conflict" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Removing member…"
        case "success":
            return "Member removed from group."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This group's membership changed elsewhere. Reload the page to see the current state."
        case "error":
            return "The member could not be removed. Try again."
    }
}

// One control per group member row — a deliberate confirmation step
// naming both the member and the group, per this checkpoint's own
// requirement. Never ends the member's own campaign membership, and never
// touches the group's own grants or any other member's link to it — the
// server enforces this scope, not the UI.
export function RemoveAccessGroupMember({
    campaignId,
    accessGroupMembershipId,
    memberDisplayName,
    groupName,
    onChanged,
    onMutationStart,
}: RemoveAccessGroupMemberProps) {
    const statusId = useId()

    const [isConfirming, setIsConfirming] = useState(false)
    const triggerButtonRef = useRef<HTMLButtonElement>(null)
    const confirmButtonRef = useRef<HTMLButtonElement>(null)
    const wasConfirmingRef = useRef(false)

    const { status, submit, reset } = useRemoveAccessGroupMember(
        campaignId,
        () => onChanged("Member removed from group."),
    )

    const isPending = status.kind === "pending"

    useEffect(() => {
        if (isConfirming) {
            confirmButtonRef.current?.focus()
        } else if (wasConfirmingRef.current) {
            triggerButtonRef.current?.focus()
        }
        wasConfirmingRef.current = isConfirming
    }, [isConfirming])

    if (!isConfirming) {
        return (
            <button
                ref={triggerButtonRef}
                type="button"
                className="access-role-editor__trigger"
                onClick={() => {
                    reset()
                    setIsConfirming(true)
                }}
            >
                Remove from group
            </button>
        )
    }

    return (
        <span
            className="access-role-editor"
            role="group"
            aria-label={`Remove ${memberDisplayName} from ${groupName}`}
        >
            <span className="access-role-editor__confirm-text">
                Remove {memberDisplayName} from {groupName}? They will lose
                any access this group grants immediately; their campaign
                membership, roles, character relationships, and direct
                resource grants are not affected.
            </span>

            <div className="access-role-editor__actions">
                <button
                    ref={confirmButtonRef}
                    type="button"
                    disabled={isPending}
                    aria-busy={isPending}
                    onClick={() => {
                        onMutationStart()
                        submit(accessGroupMembershipId)
                    }}
                >
                    {isPending ? "Removing…" : "Confirm"}
                </button>

                <button
                    type="button"
                    disabled={isPending}
                    onClick={() => {
                        reset()
                        setIsConfirming(false)
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
        </span>
    )
}
