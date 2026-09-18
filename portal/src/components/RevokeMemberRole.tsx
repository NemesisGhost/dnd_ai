import { useId, useState } from "react"
import { useRevokeMembershipRole } from "../hooks/useRevokeMembershipRole"
import type { AccessRoleSummary } from "../types/accessOverview"

interface RevokeMemberRoleProps {
    campaignId: string
    memberDisplayName: string
    role: AccessRoleSummary
    onChanged: (message: string) => void
}

function statusMessage(
    kind: "pending" | "success" | "denied" | "conflict" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Removing role…"
        case "success":
            return "Role removed."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This role assignment changed elsewhere. Reload the page to see the current state."
        case "error":
            return "The role could not be removed. Try again."
    }
}

// One control per currently active role assignment (mirrors
// MemberRoleEditor's own per-row shape, never per-member) — a deliberate
// confirmation step in place of the change control's immediate select, per
// this checkpoint's own requirement that revocation always name the member
// and role and require an explicit confirm.
export function RevokeMemberRole({
    campaignId,
    memberDisplayName,
    role,
    onChanged,
}: RevokeMemberRoleProps) {
    const statusId = useId()

    const [isConfirming, setIsConfirming] = useState(false)

    const { status, submit, reset } = useRevokeMembershipRole(
        campaignId,
        () => onChanged("Role removed."),
    )

    const isPending = status.kind === "pending"

    if (!isConfirming) {
        return (
            <button
                type="button"
                className="access-role-editor__trigger"
                onClick={() => {
                    reset()
                    setIsConfirming(true)
                }}
            >
                Remove role
            </button>
        )
    }

    return (
        <span
            className="access-role-editor"
            role="group"
            aria-label={`Remove ${role.display_name} from ${memberDisplayName}`}
        >
            <span className="access-role-editor__confirm-text">
                Remove {memberDisplayName}'s{" "}
                {role.display_name} role?
            </span>

            <div className="access-role-editor__actions">
                <button
                    type="button"
                    disabled={isPending}
                    aria-busy={isPending}
                    onClick={() => {
                        submit(role.membership_role_id)
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
                {status.kind === "idle"
                    ? ""
                    : statusMessage(status.kind)}
            </p>
        </span>
    )
}
