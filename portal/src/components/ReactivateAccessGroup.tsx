import { useId } from "react"
import { useReactivateAccessGroup } from "../hooks/useReactivateAccessGroup"

interface ReactivateAccessGroupProps {
    campaignId: string
    accessGroupId: string
    groupName: string
    onChanged: (message: string) => void
    onMutationStart: () => void
}

function statusMessage(
    kind: "pending" | "success" | "denied" | "conflict" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Reactivating access group…"
        case "success":
            return "Access group reactivated. It has no members or resource access until you add them again."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This group changed elsewhere, or the campaign is not currently active. Reload the page to see the current state."
        case "error":
            return "The access group could not be reactivated. Try again."
    }
}

// One control per archived group — a single, non-destructive action (it
// only ever restores the group's own active status, never its historical
// members or grants), so no separate confirmation step is layered on top,
// matching this codebase's own "Add role"/"Add member" precedent for a
// restorative rather than destructive action.
export function ReactivateAccessGroup({
    campaignId,
    accessGroupId,
    groupName,
    onChanged,
    onMutationStart,
}: ReactivateAccessGroupProps) {
    const statusId = useId()

    const { status, submit, reset } = useReactivateAccessGroup(
        campaignId,
        () => onChanged("Access group reactivated."),
    )

    const isPending = status.kind === "pending"

    return (
        <span className="access-role-editor">
            <button
                type="button"
                title={`Reactivate ${groupName}`}
                disabled={isPending}
                aria-busy={isPending}
                onClick={() => {
                    reset()
                    onMutationStart()
                    submit(accessGroupId)
                }}
            >
                {isPending ? "Reactivating…" : "Reactivate"}
            </button>

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
