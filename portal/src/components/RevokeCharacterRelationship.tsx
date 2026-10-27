import { useEffect, useId, useRef, useState } from "react"
import { useRevokeCharacterRelationship } from "../hooks/useRevokeCharacterRelationship"
import type { AccessCharacterRelationshipSummary } from "../types/accessOverview"

interface RevokeCharacterRelationshipProps {
    campaignId: string
    memberDisplayName: string
    relationship: AccessCharacterRelationshipSummary
    onChanged: (message: string) => void
    onMutationStart: () => void
}

function statusMessage(
    kind: "pending" | "success" | "denied" | "conflict" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Removing character access…"
        case "success":
            return "Character access removed."
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This character access changed elsewhere. Reload the page to see the current state."
        case "error":
            return "The character access could not be removed. Try again."
    }
}

// One control per currently active character relationship (mirrors
// CharacterRelationshipEditor's/RevokeMemberRole's own per-row shape,
// never per-member) — a deliberate confirmation step naming both the
// character and the member, and explaining that the character perspective
// will no longer be available, per this checkpoint's own requirement that
// revocation always be deliberate. The server, not the UI, decides whether
// a self-targeted revocation is authorized.
export function RevokeCharacterRelationship({
    campaignId,
    memberDisplayName,
    relationship,
    onChanged,
    onMutationStart,
}: RevokeCharacterRelationshipProps) {
    const statusId = useId()

    const [isConfirming, setIsConfirming] = useState(false)
    const triggerButtonRef = useRef<HTMLButtonElement>(null)
    const confirmButtonRef = useRef<HTMLButtonElement>(null)
    const wasConfirmingRef = useRef(false)

    const { status, submit, reset } = useRevokeCharacterRelationship(
        campaignId,
        () => onChanged("Character access removed."),
    )

    const isPending = status.kind === "pending"

    // Moves focus deliberately between the trigger and confirmation UI
    // whenever one replaces the other in the DOM — mirrors
    // RemoveCampaignMember's own fix for the identical focus-loss gap
    // (an unmounted button would otherwise drop focus to <body>), extended
    // to the reverse direction (confirm -> trigger) for an explicit
    // Cancel, per this checkpoint's own "returns focus sensibly on cancel"
    // requirement. Keyed only on isConfirming, not on isPending/status, so
    // an unrelated rerender while already confirming never steals focus
    // back from wherever the user has since moved it.
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
                Remove access
            </button>
        )
    }

    return (
        <span
            className="access-role-editor"
            role="group"
            aria-label={`Remove ${relationship.character_display_name} access from ${memberDisplayName}`}
        >
            <span className="access-role-editor__confirm-text">
                Remove {memberDisplayName}'s{" "}
                {relationship.relationship_type_display_name} access
                to {relationship.character_display_name}? The character
                perspective will no longer be available to{" "}
                {memberDisplayName}.
            </span>

            <div className="access-role-editor__actions">
                <button
                    ref={confirmButtonRef}
                    type="button"
                    disabled={isPending}
                    aria-busy={isPending}
                    onClick={() => {
                        onMutationStart()
                        submit(
                            relationship.membership_character_relationship_id,
                        )
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
