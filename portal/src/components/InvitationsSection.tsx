import { useEffect, useId, useRef, useState } from "react"
import { useCampaignInvitations } from "../hooks/useCampaignInvitations"
import { useCreateCampaignInvitation } from "../hooks/useCreateCampaignInvitation"
import { useRevokeCampaignInvitation } from "../hooks/useRevokeCampaignInvitation"
import type { PendingCampaignInvitation } from "../types/campaignInvitations"

interface InvitationsSectionProps {
    campaignId: string
    onChanged: (message: string) => void
    onMutationStart: () => void
    issuedToken: string | null
    onIssuedTokenChange: (token: string | null) => void
}

function formatTimestamp(timestamp: string): string {
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
    }).format(new Date(timestamp))
}

function createStatusMessage(
    kind: "pending" | "success" | "replayed" | "denied" | "conflict" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Issuing invitation…"
        case "success":
            return "Invitation issued."
        case "replayed":
            return "This invitation was already issued, but the original token is unavailable. Revoke the pending invitation and issue a new one if the token was not received."
        case "denied":
            return "You do not have permission to issue invitations."
        case "conflict":
            return "This invitation request conflicted with another request. Try again."
        case "error":
            return "The invitation could not be issued. Try again."
    }
}

function revokeStatusMessage(
    kind: "pending" | "success" | "denied" | "conflict" | "error",
): string {
    switch (kind) {
        case "pending":
            return "Revoking invitation…"
        case "success":
            return "Invitation revoked."
        case "denied":
            return "You do not have permission to revoke invitations."
        case "conflict":
            return "This invitation can no longer be revoked. Reload the page to see the current state."
        case "error":
            return "The invitation could not be revoked. Try again."
    }
}

function invitationLabel(invitation: PendingCampaignInvitation): string {
    return invitation.invited_email ?? "No email label"
}

interface RevokeInvitationButtonProps {
    campaignId: string
    invitation: PendingCampaignInvitation
    onChanged: (message: string) => void
    onMutationStart: () => void
    onSuccess: () => void
}

function RevokeInvitationButton({
    campaignId,
    invitation,
    onChanged,
    onMutationStart,
    onSuccess,
}: RevokeInvitationButtonProps) {
    const statusId = useId()
    const [isConfirming, setIsConfirming] = useState(false)
    const triggerButtonRef = useRef<HTMLButtonElement>(null)
    const confirmButtonRef = useRef<HTMLButtonElement>(null)
    const wasConfirmingRef = useRef(false)

    const { status, submit, reset } = useRevokeCampaignInvitation(campaignId, () => {
        onSuccess()
        onChanged("Invitation revoked.")
    })

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
                Revoke
            </button>
        )
    }

    return (
        <span
            className="access-role-editor"
            role="group"
            aria-label={`Revoke invitation ${invitationLabel(invitation)}`}
        >
            <span className="access-role-editor__confirm-text">
                Revoke invitation for {invitationLabel(invitation)}? The token will stop working.
            </span>

            <div className="access-role-editor__actions">
                <button
                    ref={confirmButtonRef}
                    type="button"
                    disabled={isPending}
                    aria-busy={isPending}
                    onClick={() => {
                        onMutationStart()
                        submit(invitation.campaign_invitation_id)
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
                {status.kind === "idle" ? "" : revokeStatusMessage(status.kind)}
            </p>
        </span>
    )
}

export function InvitationsSection({
    campaignId,
    onChanged,
    onMutationStart,
    issuedToken,
    onIssuedTokenChange,
}: InvitationsSectionProps) {
    const emailInputId = useId()
    const createStatusId = useId()
    const copyStatusId = useId()
    const { state, retry } = useCampaignInvitations(campaignId)
    const [invitedEmail, setInvitedEmail] = useState("")
    const [copyStatus, setCopyStatus] = useState<"idle" | "success" | "error">("idle")

    const { status: createStatus, submit, reset } = useCreateCampaignInvitation(
        campaignId,
        (result) => {
            if (result.token !== null) {
                onIssuedTokenChange(result.token)
                onChanged("Invitation issued.")
            } else {
                onIssuedTokenChange(null)
            }
            setCopyStatus("idle")
            retry()
        },
    )

    const isCreatePending = createStatus.kind === "pending"

    async function handleCopyToken(): Promise<void> {
        if (issuedToken === null) {
            return
        }
        try {
            await navigator.clipboard.writeText(issuedToken)
            setCopyStatus("success")
        } catch {
            setCopyStatus("error")
        }
    }

    return (
        <section aria-labelledby="access-invitations-heading" className="access-page__groups">
            <h2 id="access-invitations-heading">Invitations</h2>

            <p className="access-page__description">
                Issue and revoke campaign invitations. The optional email label is a delivery aid
                only and does not bind the token to any account.
            </p>

            <form
                className="access-role-editor"
                aria-label="Issue invitation"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (isCreatePending) {
                        return
                    }
                    onIssuedTokenChange(null)
                    setCopyStatus("idle")
                    onMutationStart()
                    submit(invitedEmail.trim() === "" ? null : invitedEmail.trim())
                }}
            >
                <label htmlFor={emailInputId}>Optional email label</label>
                <input
                    id={emailInputId}
                    type="text"
                    value={invitedEmail}
                    disabled={isCreatePending}
                    autoComplete="off"
                    onChange={(event) => {
                        setInvitedEmail(event.currentTarget.value)
                        if (createStatus.kind !== "idle") {
                            reset()
                        }
                    }}
                />
                <p className="access-role-editor__confirm-text">
                    This label can help you deliver the token, but it does not restrict who can
                    accept it.
                </p>

                <div className="access-role-editor__actions">
                    <button type="submit" disabled={isCreatePending} aria-busy={isCreatePending}>
                        {isCreatePending ? "Issuing…" : "Issue invitation"}
                    </button>
                </div>

                <p
                    id={createStatusId}
                    className={
                        createStatus.kind === "replayed" ||
                        createStatus.kind === "denied" ||
                        createStatus.kind === "conflict" ||
                        createStatus.kind === "error"
                            ? "access-role-editor__status access-role-editor__status--error"
                            : "access-role-editor__status"
                    }
                    role="status"
                    aria-live="polite"
                >
                    {createStatus.kind === "idle" ? "" : createStatusMessage(createStatus.kind)}
                </p>
            </form>

            {issuedToken !== null && (
                <section aria-labelledby="issued-token-heading" className="access-member-card__body">
                    <h3 id="issued-token-heading">Copy invitation token now</h3>
                    <p>This token is shown once and cannot be recovered later.</p>
                    <input type="text" value={issuedToken} readOnly aria-label="Invitation token" />
                    <div className="access-role-editor__actions">
                        <button type="button" onClick={() => void handleCopyToken()}>
                            Copy token
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                onIssuedTokenChange(null)
                                setCopyStatus("idle")
                            }}
                        >
                            Dismiss token
                        </button>
                    </div>
                    <p id={copyStatusId} className="access-role-editor__status" role="status" aria-live="polite">
                        {copyStatus === "idle"
                            ? ""
                            : copyStatus === "success"
                              ? "Token copied."
                              : "The token could not be copied. Copy it manually."}
                    </p>
                </section>
            )}

            {state.status === "loading" && <p>Loading invitations…</p>}

            {state.status === "denied" && (
                <p>You do not have permission to view invitations for this campaign.</p>
            )}

            {state.status === "error" && (
                <section className="placeholder-page" aria-labelledby="invitations-error-heading">
                    <h3 id="invitations-error-heading">Invitation list unavailable</h3>
                    <p>The portal could not load the current invitations. Try again.</p>
                    <button type="button" onClick={retry}>
                        Try again
                    </button>
                </section>
            )}

            {state.status === "success" && state.invitations.length === 0 && (
                <p>No outstanding invitations.</p>
            )}

            {state.status === "success" && state.invitations.length > 0 && (
                <ul className="access-page__member-list" aria-label="Outstanding invitations">
                    {state.invitations.map((invitation) => (
                        <li key={invitation.campaign_invitation_id}>
                            <details className="access-member-card">
                                <summary>
                                    <strong>{invitationLabel(invitation)}</strong>
                                    <span>Invited by {invitation.invited_by_display_name}</span>
                                    <span>Expires {formatTimestamp(invitation.expires_at)}</span>
                                    <span className="access-member-card__indicator" aria-hidden="true" />
                                </summary>

                                <div className="access-member-card__body">
                                    <p>Created {formatTimestamp(invitation.created_at)}</p>
                                    <p>Expires {formatTimestamp(invitation.expires_at)}</p>
                                    <p>Invited by {invitation.invited_by_display_name}</p>

                                    <RevokeInvitationButton
                                        campaignId={campaignId}
                                        invitation={invitation}
                                        onChanged={onChanged}
                                        onMutationStart={onMutationStart}
                                        onSuccess={retry}
                                    />
                                </div>
                            </details>
                        </li>
                    ))}
                </ul>
            )}
        </section>
    )
}