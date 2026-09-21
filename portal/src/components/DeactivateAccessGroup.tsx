import { useEffect, useId, useRef, useState } from "react"
import { useDeactivateAccessGroup } from "../hooks/useDeactivateAccessGroup"

interface DeactivateAccessGroupProps {
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
            return "Deactivating access group…"
        case "success":
            return "Access group deactivated."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This group changed elsewhere. Reload the page to see the current state."
        case "error":
            return "The access group could not be deactivated. Try again."
    }
}

// One control per group — a deliberate confirmation step naming the group
// and explaining exactly what will and will not happen, per this
// checkpoint's own requirement. The server, not the UI, decides whether
// the request is authorized.
export function DeactivateAccessGroup({
    campaignId,
    accessGroupId,
    groupName,
    onChanged,
    onMutationStart,
}: DeactivateAccessGroupProps) {
    const statusId = useId()

    const [isConfirming, setIsConfirming] = useState(false)
    const triggerButtonRef = useRef<HTMLButtonElement>(null)
    const confirmButtonRef = useRef<HTMLButtonElement>(null)
    const wasConfirmingRef = useRef(false)

    const { status, submit, reset } = useDeactivateAccessGroup(
        campaignId,
        () => onChanged("Access group deactivated."),
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
                Deactivate
            </button>
        )
    }

    return (
        <span
            className="access-role-editor"
            role="group"
            aria-label={`Deactivate ${groupName}`}
        >
            <span className="access-role-editor__confirm-text">
                Deactivate &quot;{groupName}&quot;? Its members will lose any
                access this group grants immediately. Historical records are
                kept; direct roles, character relationships, and direct
                resource grants held by its members are not affected.
            </span>

            <div className="access-role-editor__actions">
                <button
                    ref={confirmButtonRef}
                    type="button"
                    disabled={isPending}
                    aria-busy={isPending}
                    onClick={() => {
                        onMutationStart()
                        submit(accessGroupId)
                    }}
                >
                    {isPending ? "Deactivating…" : "Confirm"}
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
