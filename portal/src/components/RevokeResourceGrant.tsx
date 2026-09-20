import { useEffect, useId, useRef, useState } from "react"
import { useRevokeResourceGrant } from "../hooks/useRevokeResourceGrant"
import type { AccessResourceGrantSummary } from "../types/accessOverview"
import { humanizeCode } from "../utils/humanize"

interface RevokeResourceGrantProps {
    campaignId: string
    memberDisplayName: string
    grant: AccessResourceGrantSummary
    onChanged: (message: string) => void
    onMutationStart: () => void
}

function statusMessage(
    kind: "pending" | "success" | "denied" | "conflict" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Revoking resource access…"
        case "success":
            return "Resource access revoked."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This grant changed elsewhere. Reload the page to see the current state."
        case "error":
            return "The resource access could not be revoked. Try again."
    }
}

function grantLabel(grant: AccessResourceGrantSummary): string {
    const target = grant.target_display_name ?? humanizeCode(grant.target_type)
    return `${grant.capability_display_name} on ${target}`
}

// One control per currently active resource grant (mirrors
// RevokeCharacterRelationship's own per-row shape, never per-member) — a
// deliberate confirmation step naming the member, the resource, and the
// permission being removed, and explaining that access may disappear
// immediately, per this checkpoint's own requirement. The server, not the
// UI, decides whether a self-targeted revocation is authorized.
export function RevokeResourceGrant({
    campaignId,
    memberDisplayName,
    grant,
    onChanged,
    onMutationStart,
}: RevokeResourceGrantProps) {
    const statusId = useId()

    const [isConfirming, setIsConfirming] = useState(false)
    const triggerButtonRef = useRef<HTMLButtonElement>(null)
    const confirmButtonRef = useRef<HTMLButtonElement>(null)
    const wasConfirmingRef = useRef(false)

    const { status, submit, reset } = useRevokeResourceGrant(
        campaignId,
        () => onChanged("Resource access revoked."),
    )

    const isPending = status.kind === "pending"

    // Moves focus deliberately between the trigger and confirmation UI
    // whenever one replaces the other in the DOM — mirrors
    // RevokeCharacterRelationship's own identical fix for the focus-loss
    // gap an unmounted button would otherwise create.
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
                Revoke access
            </button>
        )
    }

    return (
        <span
            className="access-role-editor"
            role="group"
            aria-label={`Revoke ${grantLabel(grant)} from ${memberDisplayName}`}
        >
            <span className="access-role-editor__confirm-text">
                Revoke {memberDisplayName}'s {grantLabel(grant)} access?
                This access may disappear immediately.
            </span>

            <div className="access-role-editor__actions">
                <button
                    ref={confirmButtonRef}
                    type="button"
                    disabled={isPending}
                    aria-busy={isPending}
                    onClick={() => {
                        onMutationStart()
                        submit(grant.resource_grant_id)
                    }}
                >
                    {isPending ? "Revoking…" : "Confirm"}
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
