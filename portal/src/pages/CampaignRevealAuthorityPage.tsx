import { AlertTriangle } from "lucide-react"
import { useEffect, useLayoutEffect, useRef, useState } from "react"
import type { ReactNode } from "react"
import { useParams } from "react-router"
import { AccessTabNav } from "../components/AccessTabNav"
import { StaleReadNotice } from "../components/StaleReadNotice"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { useAnnounce } from "../components/authoring/announcer"
import { TaskBreadcrumb } from "../components/navigation/TaskBreadcrumb"
import { grantRevealDelegation, revealDelegationsPath, revokeRevealDelegation } from "../api/revealDelegations"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { useAnnounceWhenRead, useConfirmedRefresh } from "../hooks/useConfirmedRefresh"
import { useKept } from "../hooks/useKeptResource"
import { classifyApiError } from "../types/apiError"
import type { AuthoringError } from "../types/apiError"
import type {
    GrantRevealDelegationBody,
    GrantRevealDelegationReceipt,
    LapsedRevealDelegation,
    RevealDelegationMember,
    RevealDelegationState,
    RevokeRevealDelegationReceipt,
    RevokeRevealDelegationSubmit,
} from "../types/revealDelegations"
import { canTakeFocus } from "../utils/focusEligibility"
import "../components/authoring/authoring.css"
import PlaceholderPage from "./PlaceholderPage"

const REASON_MAX = 1000

const when = (iso: string): string => new Date(iso).toLocaleString()

const grantedBy = (name: string | null): string => `granted by ${name ?? "a former member"}`

// What the page says for a refusal. The server's own message is never shown: `campaign_owner_required`'s text
// names the owner role in a way that is wrong here.
const OWNER_ONLY = "Only a campaign owner can grant or revoke reveal authority."

interface Refusal {
    message: string
    // The person's own unsent reason, shown back read-only; null when it must not be.
    reason: string | null
}

// The person is working with one member's grant or revoke dialog.
interface DialogTarget {
    kind: "grant" | "revoke"
    id: string
    name: string
    // The delegation belongs to someone who no longer holds the GM role.
    lapsed: boolean
}

// An error that leaves the outcome unknown: the request may have been applied.
const isUnknownOutcome = (error: AuthoringError): boolean => error.kind === "network" || error.kind === "server"

// The Access section's Reveal authority tab (docs/delivery/p15-c02-s03-reveal-delegations-plan.md). A separate
// route, so opening it reads only the reveal-delegation state and no other Access tab reads it. Everything shown
// is what the server says: who holds the GM role, whether a delegation authorizes them, and whether the caller
// is an owner. The page never decides ownership, eligibility or effectiveness itself, and offers grant and revoke
// only while the server's `can_manage` is true on a read that is current.
export function CampaignRevealAuthorityPage() {
    const { campaignId } = useParams<{ campaignId: string }>()
    if (campaignId === undefined) {
        return (
            <PlaceholderPage title="Access unavailable" description="The requested access information is not available." />
        )
    }
    // Keyed on the campaign: nothing read, typed or pending for one campaign can appear under another.
    return <RevealAuthorityContent key={campaignId} campaignId={campaignId} />
}

function RevealAuthorityContent({ campaignId }: { campaignId: string }) {
    // The content is bound to what the applied session says this campaign grants: without `access.manage` nothing
    // below is mounted, an in-flight read or write is aborted with it and cannot publish.
    const canManageAccess = useCampaignCapability(campaignId, "access.manage")
    return (
        <>
            <TaskBreadcrumb />
            <AccessTabNav campaignId={campaignId} />
            {canManageAccess ? (
                <RevealAuthorityBody campaignId={campaignId} />
            ) : (
                <PlaceholderPage title="Access unavailable" description="The requested access information is not available." />
            )}
        </>
    )
}

function RevealAuthorityBody({ campaignId }: { campaignId: string }) {
    const path = revealDelegationsPath(campaignId)
    const { state, refetch } = useAuthoringResource<RevealDelegationState>(path)
    const view = useKept(state, path)
    const { refresh } = useSession()
    const announce = useAnnounce()
    const announceWhenRead = useAnnounceWhenRead(state.kind === "ready" && !state.refreshing, state)

    // A write's 403 or 404 (other than `campaign_owner_required`) says the right to use this page may be gone: it is
    // treated as a read's would be.
    const [writeDenied, setWriteDenied] = useState(false)
    const gone = state.kind === "denied" || state.kind === "unavailable" || writeDenied
    const stale = state.kind === "error" && view !== null
    const reading = state.kind === "ready" && state.refreshing

    // A 403 or 404 drops everything (the list is not kept) and the session is read once in place, so a lost
    // `access.manage` also removes the tab. No retry loop.
    const refreshRef = useRef(refresh)
    useEffect(() => {
        refreshRef.current = refresh
    })
    useEffect(() => {
        if (gone) void refreshRef.current()
    }, [gone])

    // The one dialog (a grant or a revoke), and what the person has typed into it.
    const [dialog, setDialog] = useState<DialogTarget | null>(null)
    const [reason, setReason] = useState("")
    const [refusal, setRefusal] = useState<Refusal | null>(null)
    const [outcomeCheck, setOutcomeCheck] = useState<"none" | "read" | "failed">("none")
    const [grantedMessage, setGrantedMessage] = useState<string | null>(null)
    const [revokedMessage, setRevokedMessage] = useState<string | null>(null)
    // Raised after a confirmed write is read back, so focus lost with a removed control is put back.
    const [refocus, setRefocus] = useState<{ n: number; id: string; to: "grant" | "revoke" }>({ n: 0, id: "", to: "grant" })
    const headingRef = useRef<HTMLHeadingElement>(null)
    const lastName = useRef("")

    function refuse(error: AuthoringError, kind: "grant" | "revoke", typed: string) {
        const code = error.code ?? ""
        if (error.kind === "denied" && code === "campaign_owner_required") {
            setDialog(null)
            setReason("")
            setRefusal({ message: `${OWNER_ONLY} Nothing was changed.`, reason: typed })
            void refetch()
            return
        }
        if (error.kind === "denied" || error.kind === "unavailable") {
            setDialog(null)
            setReason("")
            announce("Reveal authority isn't available.")
            setWriteDenied(true)
            return
        }
        if (error.kind === "conflict" && code === "reveal_delegation_recipient_not_gm" && kind === "grant") {
            setDialog(null)
            setReason("")
            setRefusal({ message: "That member no longer holds the GM role. Nothing was changed.", reason: null })
            void refetch()
            return
        }
        if (error.kind === "conflict" && code === "reveal_delegation_recipient_changed") {
            // The dialog stays open with the reason; the list is read again so the person sees what changed.
            void refetch()
            return
        }
        // The request failed without an answer about the state: it may have been applied. The dialog closes (a repeat
        // is a new, deliberate action after a look at the current state) and nothing is sent again.
        if (isUnknownOutcome(error)) {
            setDialog(null)
            setReason("")
        }
    }

    const grantMutation = useAuthoringMutation<GrantRevealDelegationBody, GrantRevealDelegationReceipt>({
        scopeKey: `reveal-delegation-grant:${campaignId}`,
        // The key the hook offers is ignored: the server ignores it, and sending it would imply replay protection.
        request: async (body, ctx) => {
            try {
                return await grantRevealDelegation(campaignId, body, ctx)
            } catch (cause) {
                if (!ctx.signal.aborted) refuse(classifyApiError(cause), "grant", body.reason)
                throw cause
            }
        },
        onSuccess: async (result, body) => {
            const message = result.granted
                ? `${lastName.current} can now reveal characters.`
                : `${lastName.current} already had reveal authority.`
            setGrantedMessage(message)
            setDialog(null)
            setReason("")
            setRefusal(null)
            const outcome = await refetch()
            if (outcome === "ok") announce(message)
            else announceWhenRead(message)
            setRefocus((r) => ({ n: r.n + 1, id: body.grantee_campaign_membership_id, to: "revoke" }))
            return outcome
        },
        // An older confirmed grant after a reset and replacement only re-reads; the dialog and focus are the replacement's.
        onSupersededSuccess: () => {
            void refetch()
        },
    })
    const revokeMutation = useAuthoringMutation<RevokeRevealDelegationSubmit, RevokeRevealDelegationReceipt>({
        scopeKey: `reveal-delegation-revoke:${campaignId}`,
        request: async (submit, ctx) => {
            try {
                return await revokeRevealDelegation(campaignId, submit.grantee_campaign_membership_id, submit.reason, ctx)
            } catch (cause) {
                if (!ctx.signal.aborted) refuse(classifyApiError(cause), "revoke", submit.reason)
                throw cause
            }
        },
        onSuccess: async (result, submit) => {
            const message = result.revoked
                ? `Reveal authority revoked for ${lastName.current}.`
                : "That member's reveal authority had already ended."
            setRevokedMessage(message)
            setDialog(null)
            setReason("")
            setRefusal(null)
            const outcome = await refetch()
            if (outcome === "ok") announce(message)
            else announceWhenRead(message)
            setRefocus((r) => ({ n: r.n + 1, id: submit.grantee_campaign_membership_id, to: "grant" }))
            return outcome
        },
        onSupersededSuccess: () => {
            void refetch()
        },
    })
    const grantRefresh = useConfirmedRefresh({
        status: grantMutation.status,
        reset: grantMutation.reset,
        what: "reveal authority",
        message: grantedMessage,
        read: refetch,
        pageStale: stale,
        quietRecovery: true,
    })
    const revokeRefresh = useConfirmedRefresh({
        status: revokeMutation.status,
        reset: revokeMutation.reset,
        what: "reveal authority",
        message: revokedMessage,
        read: refetch,
        pageStale: stale,
        quietRecovery: true,
    })

    // After a write has been read back, the control that held focus may be gone (the dialog closed, the row changed).
    // Focus goes to the same member's counterpart control, or to the heading, only if it is on nothing: focus the
    // person moved to something still on the page is left alone.
    useLayoutEffect(() => {
        if (refocus.n === 0) return
        const active = document.activeElement
        if (active !== null && active !== document.body) return
        const counterpart = Array.from(document.querySelectorAll<HTMLElement>("[data-reveal-action]")).find(
            (element) => element.dataset.revealMember === refocus.id && element.dataset.revealAction === refocus.to,
        )
        const place = counterpart !== undefined && canTakeFocus(counterpart) ? counterpart : headingRef.current
        place?.focus()
    }, [refocus])

    // Authority for a write is the server's `can_manage` on a read that is current. Without it nothing is offered.
    // A write still in flight when the whole right to use this page is lost cannot publish: the page is unmounted and
    // the request aborted with it (a restored right starts a fresh page with nothing to repeat).
    const canManage = view?.can_manage === true && !stale && !reading
    const discardGrant = grantMutation.discard
    const discardRevoke = revokeMutation.discard
    // A write whose answer was lost is not repeatable: both writes ignore any idempotency key, so a repeat would run
    // again against whatever the state is by then. Its body goes at once (the hook keeps only a withdrawn, unknown
    // outcome), and the person looks at the current state before deciding.
    const grantError = grantMutation.status.kind === "error" ? grantMutation.status.error : null
    const revokeError = revokeMutation.status.kind === "error" ? revokeMutation.status.error : null
    useEffect(() => {
        if (grantError !== null && isUnknownOutcome(grantError) && !grantMutation.withdrawn) discardGrant()
    }, [grantError, grantMutation.withdrawn, discardGrant])
    useEffect(() => {
        if (revokeError !== null && isUnknownOutcome(revokeError) && !revokeMutation.withdrawn) discardRevoke()
    }, [revokeError, revokeMutation.withdrawn, discardRevoke])

    const outcomeUnknown = grantMutation.withdrawn || revokeMutation.withdrawn
    const [seenUnknown, setSeenUnknown] = useState(outcomeUnknown)
    if (seenUnknown !== outcomeUnknown) {
        setSeenUnknown(outcomeUnknown)
        if (!outcomeUnknown) setOutcomeCheck("none")
    }

    // A re-read that no longer lists the dialog's member closes the dialog (a member who left, or whose role ended).
    if (dialog !== null && state.kind === "ready" && !state.refreshing && view !== null) {
        const listed =
            dialog.kind === "grant"
                ? view.members.some((m) => m.campaign_membership_id === dialog.id)
                : view.members.some((m) => m.campaign_membership_id === dialog.id) ||
                  view.lapsed_delegations.some((m) => m.campaign_membership_id === dialog.id)
        if (!listed) {
            setDialog(null)
            setReason("")
        }
    }

    const writesHeld = reading || stale || grantRefresh.held || revokeRefresh.held
    const busy = grantMutation.status.kind === "pending" || revokeMutation.status.kind === "pending"

    function open(target: DialogTarget) {
        if (!canManage || writesHeld || busy) return
        // Starting a new operation clears an old refusal and a settled error; an unknown outcome stays until it is
        // checked or dismissed, or until this attempt replaces it.
        setRefusal(null)
        setReason("")
        if (!grantMutation.withdrawn) grantMutation.reset()
        if (!revokeMutation.withdrawn) revokeMutation.reset()
        setDialog(target)
    }

    function confirm() {
        if (dialog === null || !canManage || writesHeld || busy) return
        const trimmed = reason.trim()
        if (trimmed === "" || trimmed.length > REASON_MAX) return
        lastName.current = dialog.name
        if (dialog.kind === "grant") {
            grantMutation.submit({ grantee_campaign_membership_id: dialog.id, reason: trimmed })
        } else {
            revokeMutation.submit({ grantee_campaign_membership_id: dialog.id, reason: trimmed })
        }
    }

    // A refusal the dialog shows in place (it stays open, with the reason): a changed GM assignment, or a reason the
    // server did not accept. Nothing is ever sent again for it automatically.
    const dialogMutation = dialog?.kind === "revoke" ? revokeMutation : grantMutation
    const dialogFailure =
        dialog !== null && dialogMutation.status.kind === "error" && !dialogMutation.withdrawn
            ? dialogMutation.status.error
            : null
    let dialogError: ReactNode = null
    if (dialogFailure !== null && !isUnknownOutcome(dialogFailure)) {
        const code = dialogFailure.code ?? ""
        const text =
            dialogFailure.kind === "conflict" && code === "reveal_delegation_recipient_changed"
                ? "Their GM assignment changed while this was being saved. Nothing was changed; review and grant again."
                : dialogFailure.kind === "invalid"
                  ? "That could not be sent. Check the reason and try again."
                  : "That could not be done. Nothing was changed."
        dialogError = (
            <p role="alert" className="authoring-message authoring-message--warning">
                {text}
            </p>
        )
    }

    if (gone) {
        return (
            <PlaceholderPage title="Reveal authority unavailable" description="Reveal authority is not available to you." />
        )
    }
    return (
        <section aria-labelledby="reveal-authority-heading" className="reveal-authority">
            <h2 id="reveal-authority-heading" ref={headingRef} tabIndex={-1}>
                Reveal authority
            </h2>
            <p>
                Campaign owners can always reveal characters. A GM can also reveal characters when an owner delegates
                that to them here.
            </p>
            {view === null ? (
                state.kind === "error" ? (
                    <StaleReadNotice what="reveal authority" onRetry={() => void refetch()} />
                ) : (
                    <p role="status">Loading reveal authority…</p>
                )
            ) : (
                <>
                    {state.kind === "error" ? (
                        <StaleReadNotice what="reveal authority" onRetry={() => void refetch()} />
                    ) : null}
                    {grantRefresh.notice}
                    {revokeRefresh.notice}
                    {outcomeUnknown ? (
                        <div className="authoring-message authoring-message--warning" role="alert">
                            <AlertTriangle aria-hidden="true" className="authoring-message__icon" />
                            <div>
                                <p>
                                    We couldn't confirm whether your last change to reveal authority was applied. It may
                                    have been made. It won't be sent again from here.
                                </p>
                                {outcomeCheck === "read" ? (
                                    <p>
                                        The list shows current reveal authority. It doesn't show whether your last attempt
                                        made the change.
                                    </p>
                                ) : null}
                                {outcomeCheck === "failed" ? (
                                    <p>That says nothing about whether the change was applied.</p>
                                ) : null}
                                <button
                                    type="button"
                                    className="authoring-button"
                                    onClick={() => {
                                        void refetch().then((outcome) => setOutcomeCheck(outcome === "ok" ? "read" : "failed"))
                                    }}
                                >
                                    Check current reveal authority
                                </button>
                                <button
                                    type="button"
                                    className="authoring-button"
                                    onClick={() => {
                                        if (grantMutation.withdrawn) grantMutation.reset()
                                        if (revokeMutation.withdrawn) revokeMutation.reset()
                                    }}
                                >
                                    Dismiss
                                </button>
                            </div>
                        </div>
                    ) : null}
                    {refusal !== null ? (
                        <div className="authoring-message authoring-message--warning" role="alert">
                            <AlertTriangle aria-hidden="true" className="authoring-message__icon" />
                            <div>
                                <p>{refusal.message}</p>
                                {refusal.reason !== null ? (
                                    <section aria-label="Your unsent reason" className="authoring-your-changes">
                                        <h4>Your reason, not sent</h4>
                                        <p>{refusal.reason}</p>
                                    </section>
                                ) : null}
                                <button type="button" className="authoring-button" onClick={() => setRefusal(null)}>
                                    Dismiss
                                </button>
                            </div>
                        </div>
                    ) : null}
                    {/* What the caller may do is the server's `can_manage`, and only from a read that is current. */}
                    {stale ? null : (
                        <p>
                            {view.can_manage
                                ? "You can grant or revoke reveal authority."
                                : "Only a campaign owner can grant or revoke reveal authority."}
                        </p>
                    )}
                    {view.members.length === 0 ? (
                        <p>No member currently holds the GM role.</p>
                    ) : (
                        <ul className="op-list" aria-label="GMs">
                            {view.members.map((member) => (
                                <MemberRow
                                    key={member.campaign_membership_id}
                                    member={member}
                                    action={
                                        canManage ? (
                                            <button
                                                type="button"
                                                className="authoring-button"
                                                disabled={writesHeld || busy}
                                                data-reveal-member={member.campaign_membership_id}
                                                data-reveal-action={member.delegation === null ? "grant" : "revoke"}
                                                aria-label={
                                                    member.delegation === null
                                                        ? `Grant reveal authority to ${member.display_name}`
                                                        : `Revoke reveal authority from ${member.display_name}`
                                                }
                                                onClick={() =>
                                                    open({
                                                        kind: member.delegation === null ? "grant" : "revoke",
                                                        id: member.campaign_membership_id,
                                                        name: member.display_name,
                                                        lapsed: false,
                                                    })
                                                }
                                            >
                                                {member.delegation === null ? "Grant" : "Revoke"}
                                            </button>
                                        ) : null
                                    }
                                />
                            ))}
                        </ul>
                    )}
                    {view.lapsed_delegations.length > 0 ? (
                        <section aria-labelledby="reveal-lapsed-heading">
                            <h3 id="reveal-lapsed-heading">Delegations that no longer apply</h3>
                            <ul className="op-list">
                                {view.lapsed_delegations.map((entry) => (
                                    <LapsedRow
                                        key={entry.campaign_membership_id}
                                        entry={entry}
                                        action={
                                            canManage ? (
                                                <button
                                                    type="button"
                                                    className="authoring-button"
                                                    disabled={writesHeld || busy}
                                                    data-reveal-member={entry.campaign_membership_id}
                                                    data-reveal-action="revoke"
                                                    aria-label={`Revoke the delegation of ${entry.display_name}`}
                                                    onClick={() =>
                                                        open({
                                                            kind: "revoke",
                                                            id: entry.campaign_membership_id,
                                                            name: entry.display_name,
                                                            lapsed: true,
                                                        })
                                                    }
                                                >
                                                    Revoke
                                                </button>
                                            ) : null
                                        }
                                    />
                                ))}
                            </ul>
                        </section>
                    ) : null}
                    <ConfirmDialog
                        // Open while the server says the caller is an owner (a read in progress does not close it).
                        open={dialog !== null && view.can_manage}
                        title={
                            dialog === null
                                ? "Reveal authority"
                                : dialog.kind === "grant"
                                  ? `Grant reveal authority to ${dialog.name}?`
                                  : `Revoke reveal authority from ${dialog.name}?`
                        }
                        description={
                            dialog === null
                                ? ""
                                : dialog.kind === "grant"
                                  ? "They will be able to release and reveal character public profiles, as an owner can. It lasts only while they hold the GM role, and you can revoke it here. They see the change on their next request."
                                  : dialog.lapsed
                                    ? "They no longer hold the GM role, so this delegation already gives no authority. Revoking closes it."
                                    : "They will no longer be able to release or reveal character public profiles. They see the change on their next request."
                        }
                        confirmLabel={dialog?.kind === "revoke" ? "Revoke" : "Grant"}
                        cancelLabel="Cancel"
                        pending={busy}
                        confirmDisabled={writesHeld || reason.trim() === "" || reason.trim().length > REASON_MAX}
                        reason={{
                            label: dialog?.kind === "revoke" ? "Reason for revoking" : "Reason for granting",
                            required: true,
                            value: reason,
                            onChange: setReason,
                            error:
                                reason.trim().length > REASON_MAX
                                    ? `The reason must be ${REASON_MAX} characters or fewer.`
                                    : null,
                        }}
                        error={dialogError}
                        onConfirm={confirm}
                        onCancel={() => {
                            setDialog(null)
                            setReason("")
                        }}
                    />
                </>
            )}
        </section>
    )
}

function MemberRow({ member, action }: { member: RevealDelegationMember; action: ReactNode }) {
    return (
        <li>
            <p>
                <strong>{member.display_name}</strong>
            </p>
            {member.delegation !== null ? (
                <p>
                    Can reveal characters. Delegated on {when(member.delegation.granted_at)},{" "}
                    {grantedBy(member.delegation.granted_by_name)}.
                </p>
            ) : (
                <p>Cannot reveal characters.</p>
            )}
            {action}
        </li>
    )
}

function LapsedRow({ entry, action }: { entry: LapsedRevealDelegation; action: ReactNode }) {
    return (
        <li>
            <p>
                <strong>{entry.display_name}</strong>
            </p>
            <p>
                {entry.display_name} no longer holds the GM role, so this gives no authority. Delegated on{" "}
                {when(entry.granted_at)}, {grantedBy(entry.granted_by_name)}.
            </p>
            {action}
        </li>
    )
}
