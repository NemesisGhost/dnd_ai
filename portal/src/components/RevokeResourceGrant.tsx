import { useEffect, useId, useRef, useState } from "react"
import { useRevokeResourceGrant } from "../hooks/useRevokeResourceGrant"
import type { AccessResourceGrantSummary } from "../types/accessOverview"
import type { WriteNotice } from "../types/accessWrite"
import { denyDescription, denyReturns } from "../utils/characterDenies"
import type { CharacterDenyInfo } from "../utils/characterDenies"
import { humanizeCode } from "../utils/humanize"

interface RevokeResourceGrantProps {
    campaignId: string
    memberDisplayName: string
    grant: AccessResourceGrantSummary
    // Set by the page when the grant is a character denial (P15-C02-S04, D-6). Null or absent: the grant is
    // described and removed exactly as before.
    denyInfo?: CharacterDenyInfo | null
    // The member or group whose "Direct resource access" heading takes focus after a confirmed removal.
    grantsOwnerId?: string
    // A read of the access list (sends nothing): the recovery offered after a 404 of a character denial.
    onRefreshAccess?: () => void
    onChanged: (message: string, notice?: WriteNotice) => void
    onMutationStart: () => void
}

// A "deny" grant is an explicit block, not a permission — revoking one
// removes the block rather than removing access, and doing so may *restore*
// access the member already had from some other source (a role, a character
// relationship, an access group, or another allow grant), not take access
// away. Every trigger/confirmation/status string below branches on this so
// the portal never tells an operator "this access may disappear" about a
// control whose actual effect is the opposite (checkpoint-5 correction).
function isDenyEffect(grant: AccessResourceGrantSummary): boolean {
    return grant.effect === "deny"
}

function grantLabel(grant: AccessResourceGrantSummary): string {
    const target = grant.target_display_name ?? humanizeCode(grant.target_type)
    return `${grant.capability_display_name} on ${target}`
}

function triggerLabel(grant: AccessResourceGrantSummary): string {
    return isDenyEffect(grant) ? "Remove denial" : "Revoke access"
}

function confirmText(
    grant: AccessResourceGrantSummary,
    memberDisplayName: string,
): string {
    const label = grantLabel(grant)
    return isDenyEffect(grant)
        ? `Remove ${memberDisplayName}'s explicit denial of ${label}? ` +
              "Access may be restored from another role, relationship, group, or allow grant."
        : `Revoke ${memberDisplayName}'s ${label} access? ` +
              "This access may disappear immediately."
}

function triggerAriaLabel(
    grant: AccessResourceGrantSummary,
    memberDisplayName: string,
): string {
    return isDenyEffect(grant)
        ? `Remove denial of ${grantLabel(grant)} from ${memberDisplayName}`
        : `Revoke ${grantLabel(grant)} from ${memberDisplayName}`
}

function successMessage(grant: AccessResourceGrantSummary): string {
    return isDenyEffect(grant)
        ? "Explicit denial removed. Access may be restored from another role, relationship, group, or allow grant."
        : "Resource access revoked."
}

function statusMessage(
    kind: "pending" | "success" | "denied" | "conflict" | "error",
    grant: AccessResourceGrantSummary,
): string {
    switch (kind) {
        case "pending":
            return isDenyEffect(grant)
                ? "Removing denial…"
                : "Revoking resource access…"
        case "success":
            return successMessage(grant)
        case "denied":
            return "You do not have permission to make this change."
        case "conflict":
            return "This grant changed elsewhere. Reload the page to see the current state."
        case "error":
            return isDenyEffect(grant)
                ? "The denial could not be removed. Try again."
                : "The resource access could not be revoked. Try again."
    }
}

// The removal of a character denial (P15-C02-S04): says which denial, and what may come back. The words for
// what may come back are the portal's approved copy for the two known permissions (utils/characterDenies).
function characterDenyConfirmText(
    grant: AccessResourceGrantSummary,
    denyInfo: CharacterDenyInfo,
    memberDisplayName: string,
): string {
    const returns =
        denyReturns(denyInfo.code, denyInfo.characterName) ??
        "Access may be restored from another role, relationship, group, or allow grant."
    return `Remove ${memberDisplayName}'s denial of ${denyDescription(denyInfo, grant.capability_display_name)}? ${returns}`
}

function characterDenyStatusMessage(
    kind: "pending" | "success" | "denied" | "conflict" | "error",
    failureStatus: number | null,
    grant: AccessResourceGrantSummary,
): string {
    switch (kind) {
        case "denied":
            return failureStatus === 403
                ? "You no longer have permission to manage access."
                : "This denial is no longer available."
        case "error":
            return "We couldn't confirm whether the denial was removed. Trying again sends the same request."
        default:
            return statusMessage(kind, grant)
    }
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
    denyInfo = null,
    grantsOwnerId,
    onRefreshAccess,
    onChanged,
    onMutationStart,
}: RevokeResourceGrantProps) {
    const statusId = useId()

    const [isConfirming, setIsConfirming] = useState(false)
    const triggerButtonRef = useRef<HTMLButtonElement>(null)
    const confirmButtonRef = useRef<HTMLButtonElement>(null)
    const wasConfirmingRef = useRef(false)

    const { status, failureStatus, submit, reset } = useRevokeResourceGrant(campaignId, () =>
        denyInfo === null
            ? onChanged(successMessage(grant))
            : onChanged("Denial removed.", { focusGrantsOf: grantsOwnerId }),
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
                {triggerLabel(grant)}
            </button>
        )
    }

    return (
        <span
            className="access-role-editor"
            role="group"
            aria-label={
                denyInfo === null
                    ? triggerAriaLabel(grant, memberDisplayName)
                    : `Remove denial of ${denyDescription(denyInfo, grant.capability_display_name)} from ${memberDisplayName}`
            }
        >
            <span className="access-role-editor__confirm-text">
                {denyInfo === null
                    ? confirmText(grant, memberDisplayName)
                    : characterDenyConfirmText(grant, denyInfo, memberDisplayName)}
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
                    {isPending
                        ? isDenyEffect(grant)
                            ? "Removing…"
                            : "Revoking…"
                        : denyInfo !== null && status.kind === "error"
                          ? "Try again"
                          : "Confirm"}
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
                    : denyInfo === null
                      ? statusMessage(status.kind, grant)
                      : characterDenyStatusMessage(status.kind, failureStatus, grant)}
            </p>
            {denyInfo !== null && status.kind === "denied" && failureStatus === 404 && (
                <button type="button" onClick={() => onRefreshAccess?.()}>
                    Refresh access list
                </button>
            )}
        </span>
    )
}
