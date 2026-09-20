import { useEffect, useId, useRef, useState } from "react"
import { useRemoveCampaignMembership } from "../hooks/useRemoveCampaignMembership"
import { useSession } from "../context/SessionContext"

interface RemoveCampaignMemberProps {
    campaignId: string
    campaignMembershipId: string
    memberUserId: string
    memberDisplayName: string
    onChanged: (message: string) => void
    onMutationStart: () => void
}

function statusMessage(
    kind:
        | "pending"
        | "success"
        | "denied"
        | "last_manager"
        | "conflict"
        | "error",
): string {
    switch (kind) {
        case "pending":
            return "Removing member…"
        case "success":
            return "Member removed."
        case "denied":
            return "You do not have permission to make this change."
        case "last_manager":
            return "This member cannot be removed — the campaign must always retain at least one access manager."
        case "conflict":
            return "This membership changed elsewhere. Reload the page to see the current state."
        case "error":
            return "The member could not be removed. Try again."
    }
}

// One control per member card (never per-role, unlike MemberRoleEditor/
// AddMemberRole/RevokeMemberRole) — removing a member ends the whole
// membership, not one role assignment. The server remains authoritative
// on whether removal is permitted (in particular, the last-manager
// invariant); memberUserId is compared only to the caller's own
// SessionBootstrap.user.user_id for presentation ("your own access"
// wording) — never used to decide whether the control is shown or enabled.
export function RemoveCampaignMember({
    campaignId,
    campaignMembershipId,
    memberUserId,
    memberDisplayName,
    onChanged,
    onMutationStart,
}: RemoveCampaignMemberProps) {
    const statusId = useId()
    const { state: sessionState } = useSession()

    const [isConfirming, setIsConfirming] = useState(false)
    const confirmButtonRef = useRef<HTMLButtonElement>(null)

    const { status, submit, reset } =
        useRemoveCampaignMembership(campaignId, () =>
            onChanged("Member removed."),
        )

    const isPending = status.kind === "pending"

    // Moves focus deliberately into the confirmation UI the moment it
    // replaces the trigger button — without this, the trigger's own
    // removal from the DOM drops focus to <body>, breaking keyboard
    // continuity right when a keyboard user most needs it (the next
    // action, Confirm, is what they almost always want). Keyed only on
    // isConfirming, not on isPending/status, so an unrelated rerender
    // while already confirming (a status change, a re-render from a
    // sibling row) never steals focus back from wherever the user has
    // since moved it.
    useEffect(() => {
        if (isConfirming) {
            confirmButtonRef.current?.focus()
        }
    }, [isConfirming])

    const isSelf =
        sessionState.status === "authenticated" &&
        sessionState.bootstrap.user.user_id === memberUserId

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
                Remove member
            </button>
        )
    }

    return (
        <span
            className="access-role-editor"
            role="group"
            aria-label={`Remove ${memberDisplayName} from this campaign`}
        >
            <span className="access-role-editor__confirm-text">
                {isSelf ? (
                    <>
                        Remove your own access to this campaign?
                        You will lose access immediately.
                    </>
                ) : (
                    <>
                        Remove {memberDisplayName} from this
                        campaign? Their access will end
                        immediately.
                    </>
                )}
            </span>

            <div className="access-role-editor__actions">
                <button
                    ref={confirmButtonRef}
                    type="button"
                    disabled={isPending}
                    aria-busy={isPending}
                    onClick={() => {
                        onMutationStart()
                        submit(campaignMembershipId)
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
                    status.kind === "last_manager" ||
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
