import { TableScroll } from "../components/TableScroll"
import { useContext, useEffect, useRef, useState } from "react"
import { Link, useParams } from "react-router"
import {
    assignWorldRole,
    endWorldRole,
    grantWorldUse,
    revokeWorldUse,
    transferWorldOwnership,
    worldAccessPath,
} from "../api/worldSharing"
import { worldPath } from "../api/worlds"
import { useAnnounce } from "../components/authoring/announcer"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { SelectField, TextField } from "../components/authoring/fields"
import { MutationStatusMessage } from "../components/authoring/feedback"
import { StaleReadNotice } from "../components/StaleReadNotice"
import { useSession } from "../context/SessionContext"
import { WorkspaceHierarchyContext } from "../context/WorkspaceHierarchyContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { AuthoringResourceState, RefetchOutcome } from "../hooks/useAuthoringResource"
import { useAnnounceWhenRead, useConfirmedRefresh } from "../hooks/useConfirmedRefresh"
import { useKept } from "../hooks/useKeptResource"
import { usePageArrival } from "../hooks/usePageArrival"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import type {
    RetainedWorldRoleCode,
    WorldAccessView,
    WorldRoleAssignment,
    WorldRoleCode,
    WorldSharingChange,
    WorldTransferResult,
    WorldUseGrant,
} from "../types/worldSharing"
import { WORLD_ROLE_LABEL } from "../types/worldSharing"
import type { WorldDetail } from "../types/worldAuthoring"
import { ReadTerminal } from "../components/authoring/ReadState"
import { bootstrapRefreshOutcome } from "../utils/refreshOutcome"
import "../components/authoring/authoring.css"

const ROLE_OPTIONS = [
    { value: "world_editor", label: "Editor — creates and edits definitions and timelines" },
    { value: "world_reviewer", label: "Reviewer — approves and publishes canon" },
    { value: "world_reader", label: "Reader — reads published canon" },
    { value: "world_viewer", label: "Viewer — sees the world, its timelines and calendars" },
    { value: "world_owner", label: "Owner — full control, including sharing and transfer" },
] as const

const RETAIN_OPTIONS = [
    { value: "", label: "No role" },
    { value: "world_editor", label: "Editor" },
    { value: "world_reviewer", label: "Reviewer" },
    { value: "world_reader", label: "Reader" },
    { value: "world_viewer", label: "Viewer" },
] as const

type Pending =
    | { kind: "end-role"; assignment: WorldRoleAssignment }
    | { kind: "revoke-use"; grant: WorldUseGrant }
    | { kind: "transfer"; loginName: string; retain: RetainedWorldRoleCode | null }

// What one write is, as plain data: the operation and its target. The mutation fingerprints it, so the same
// descriptor is the same request (and key) and a different login, role or row is a new request with a new key. An
// earlier unresolved attempt can therefore only ever be re-sent for the very operation it was.
type Operation =
    | { op: "assign-role"; login: string; role: WorldRoleCode }
    | { op: "grant-use"; login: string }
    | { op: "end-role"; membershipId: string; name: string; role: string }
    | { op: "revoke-use"; grantId: string; name: string }
    | { op: "transfer"; login: string; retain: RetainedWorldRoleCode | null }

type OperationResult = WorldSharingChange | WorldTransferResult

function roleLabel(code: string): string {
    return WORLD_ROLE_LABEL[code] ?? "role"
}

// What the server did, in the person's words. `changed:false` is a no-op and says so. The login is exactly what was
// typed (never looked up); the name and role come from the row that was acted on.
function confirmationText(operation: Operation, changed: boolean): string {
    switch (operation.op) {
        case "assign-role":
            return changed
                ? `${operation.login} now has the ${roleLabel(operation.role)} role on this world.`
                : `${operation.login} already had the ${roleLabel(operation.role)} role on this world. Nothing changed.`
        case "grant-use":
            return changed
                ? `${operation.login} may now host campaigns on this world.`
                : `${operation.login} could already host campaigns on this world. Nothing changed.`
        case "end-role":
            return `${operation.name}'s ${roleLabel(operation.role)} role on this world has ended.`
        case "revoke-use":
            return `${operation.name} can no longer start new campaigns on this world.`
        case "transfer":
            return "Ownership transferred"
    }
}

// An end-role or revoke-use whose row the access list no longer holds, said as what is now true.
function goneText(operation: Operation, alreadyBefore: boolean): string {
    if (operation.op === "end-role") {
        return alreadyBefore
            ? `${operation.name}'s ${roleLabel(operation.role)} role had already ended. The list has been updated.`
            : `${operation.name}'s ${roleLabel(operation.role)} role has ended.`
    }
    if (operation.op === "revoke-use") {
        return alreadyBefore
            ? `${operation.name}'s permission had already been revoked. The list has been updated.`
            : `${operation.name} can no longer start new campaigns on this world.`
    }
    return ""
}

// A read of the access list that is still to say whether a row is there: started after a refusal or an unknown
// outcome of an end-role or revoke-use. It is settled only by the data of a later successful read of the whole list
// (a read that failed, was denied or was superseded establishes nothing), and dropped when anything newer starts.
interface Settling {
    operation: Operation
    mode: "refused" | "unknown"
    before: WorldAccessView
}

// What the page keeps about a transfer after the sharing list is gone (the person no longer has the access that
// showed it). Held above the keyed content and matched by account and world, so it can never show under another.
type TransferRecord =
    // The server answered 200: `retainedRoleCode` is what the server says the person kept.
    | { kind: "confirmed"; userId: string; worldId: string; login: string; retainedRoleCode: string | null }
    // The answer was lost, and the person's own access read now says they are no longer an Owner: consistent with a
    // completed transfer, which the page cannot confirm.
    | { kind: "unconfirmed"; userId: string; worldId: string; login: string }

// A read of the person's own access after an unknown or refused transfer. Only the read's own answer decides: a read
// that failed (or was superseded) establishes nothing.
interface TransferCheck {
    userId: string
    worldId: string
    login: string
    // "unknown": the answer to the transfer (or to a retry of it) was lost or refused after being lost, so the read
    // decides. "first-refused": a first attempt was refused, so nothing was transferred by it.
    mode: "unknown" | "first-refused"
    // The state of the access read when this check began; the answer is the first settled state after it.
    before: AuthoringResourceState<WorldAccessView> | null
    stage: "checking" | "still-owner" | "check-failed"
}

// The world's Sharing page: who holds a role on it and who may host campaigns on it. Reached
// only with `world.share` (an Owner who is also a system GM); anyone else gets the server's
// 404 or 403, shown as "not available". Every change is a confirmed or explicit action whose
// outcome is re-read from the server; nothing is optimistic. Sharing grants a *world* role or
// a permission to host a campaign: it never makes anyone a member of any campaign.
export function WorldSharingPage() {
    const { worldId = "" } = useParams()
    const world = useAuthoringResource<WorldDetail>(worldPath(worldId))
    const accessPath = worldAccessPath(worldId)
    const access = useAuthoringResource<WorldAccessView>(accessPath)
    // The last access list that loaded stays through a failed re-read, so a change that was saved is
    // not hidden behind "not available"; a denied or missing answer (a transfer that ended the
    // person's own Owner role, say) drops it and the controls with it.
    const view = useKept(access.state, accessPath)
    const stale = access.state.kind === "error" && view !== null
    const headingRef = usePageArrival(access.state.kind !== "loading")
    const worldName = world.state.kind === "ready" ? world.state.data.name : "World"
    const announce = useAnnounce()
    // The signed-in account keys the content below, with the world: nothing typed, shown or unresolved can be carried
    // to another account or world. (The loading branch below already unmounts it when either changes; the key keeps
    // that true if the read ever answers without it.)
    const { state: sessionState, refresh } = useSession()
    const userId = sessionState.status === "authenticated" ? sessionState.bootstrap.user.user_id : ""
    // Read with useContext, not useWorkspaceHierarchy: that throws outside its provider, and this page also renders without one.
    const refetchWorld = useContext(WorkspaceHierarchyContext)?.refetchWorld
    // A change saved without its read-back is announced when a read answers: with the list, or with
    // the denial that is the truth after a transfer.
    const announceWhenRead = useAnnounceWhenRead(
        (access.state.kind === "ready" && !access.state.refreshing) ||
            access.state.kind === "denied" ||
            access.state.kind === "unavailable",
        access.state,
    )

    // The transfer's record and the read that settles an uncertain one live here, above the content, because the
    // content unmounts the moment the person loses access. Both belong to one account and one world: when either
    // changes (or the session ends) they are dropped, in the render that sees it. Losing sharing authority alone
    // changes neither, so a receipt survives it.
    const [record, setRecord] = useState<TransferRecord | null>(null)
    const [check, setCheck] = useState<TransferCheck | null>(null)
    const checkSeq = useRef(0)
    const latestAccess = useRef(access.state)
    useEffect(() => {
        latestAccess.current = access.state
    })
    if (record !== null && (record.userId !== userId || record.worldId !== worldId)) setRecord(null)
    if (check !== null && (check.userId !== userId || check.worldId !== worldId)) setCheck(null)
    const shownRecord = record !== null && record.userId === userId && record.worldId === worldId ? record : null
    const shownCheck = check !== null && check.userId === userId && check.worldId === worldId ? check : null

    // Capabilities a transfer changes are also held in the sidebar's world read and the session's per-campaign world
    // capabilities. Both are re-read once, in place (never a reload, never a write); a failure changes nothing here.
    function refreshAccess() {
        if (refetchWorld !== undefined) {
            void Promise.resolve()
                .then(() => refetchWorld())
                .catch(() => undefined)
        }
        void bootstrapRefreshOutcome(refresh)
    }

    function transferConfirmed(login: string, result: WorldTransferResult) {
        const kept = result.retained_role_code
        setRecord({ kind: "confirmed", userId, worldId, login, retainedRoleCode: kept })
        setCheck(null)
        announce(
            `Ownership transferred to ${login}. ${
                kept === null ? "No role was kept for you." : `You keep the ${roleLabel(kept)} role on this world.`
            }`,
        )
        refreshAccess()
    }

    function startCheck(login: string, mode: TransferCheck["mode"]) {
        checkSeq.current += 1
        setCheck({ userId, worldId, login, mode, before: latestAccess.current, stage: "checking" })
        void access.refetch()
    }

    // The first settled access state after the check began is that read's own answer. A read that failed says nothing
    // about the transfer; a denied or unavailable one, or one that no longer allows transferring, shows the person
    // is no longer an Owner (consistent with a completed transfer, not proof of who received it); a list that still
    // allows transferring shows they still are one (the transfer had not completed when it was read).
    // This reacts to data arriving from outside (a completed read) and also announces and refreshes, which belong to an effect.
    /* eslint-disable react-hooks/set-state-in-effect */
    useEffect(() => {
        if (shownCheck === null || shownCheck.stage !== "checking" || shownCheck.before === null) return
        const state = access.state
        if (state === shownCheck.before || state.kind === "loading" || (state.kind === "ready" && state.refreshing)) return
        if (shownCheck.mode === "first-refused") {
            setCheck(null)
            return
        }
        if (state.kind === "error") {
            setCheck({ ...shownCheck, before: null, stage: "check-failed" })
            return
        }
        if (state.kind === "ready" && state.data.may_transfer) {
            setCheck({ ...shownCheck, before: null, stage: "still-owner" })
            return
        }
        setCheck(null)
        setRecord({ kind: "unconfirmed", userId, worldId, login: shownCheck.login })
        announce("Transfer not confirmed.")
        refreshAccess()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [access.state, shownCheck])
    /* eslint-enable react-hooks/set-state-in-effect */

    // Once the page has shown the controls, a read that no longer allows them (a transfer that ended the
    // person's own Owner role) replaces the controls, the dialog and the button that had focus. Focus then
    // goes to the page heading, which is followed by the explanation, instead of falling to the page. A receipt
    // takes focus itself, so the heading is left alone while one is shown.
    const wasReady = useRef(false)
    const shown = view !== null
    const receiptShown = shownRecord !== null
    useEffect(() => {
        if (receiptShown) {
            wasReady.current = false
        } else if (shown) {
            wasReady.current = true
        } else if (wasReady.current && access.state.kind !== "loading") {
            wasReady.current = false
            headingRef.current?.focus()
        }
    }, [shown, receiptShown, access.state.kind, headingRef])

    return (
        <div className="world-page">
            <div className="authoring-page">
                <p className="authoring-page__breadcrumb">
                    <Link to="/worlds">Worlds</Link>
                    {" / "}
                    <Link to={`/worlds/${worldId}`}>{worldName}</Link>
                </p>
                <h1 ref={headingRef} tabIndex={-1}>
                    Sharing
                </h1>
                {shownRecord !== null ? (
                    <>
                        <TransferReceipt
                            record={shownRecord}
                            worldId={worldId}
                            worldName={world.state.kind === "ready" ? world.state.data.name : "this world"}
                        />
                        {access.state.kind !== "loading" && view === null ? (
                            <ReadTerminal
                                states={[access.state]}
                                what="sharing list"
                                onRetry={access.refetch}
                                back={{ to: `/worlds/${worldId}`, label: "Back to the world" }}
                            />
                        ) : null}
                    </>
                ) : access.state.kind === "loading" ? (
                    <p role="status">Loading…</p>
                ) : view === null ? (
                    <ReadTerminal
                        states={[access.state]}
                        what="sharing list"
                        onRetry={access.refetch}
                        back={{ to: `/worlds/${worldId}`, label: "Back to the world" }}
                    />
                ) : (
                    <>
                        {stale ? <StaleReadNotice what="sharing list" onRetry={() => void access.refetch()} /> : null}
                        <SharingContent
                            key={`${userId}:${worldId}`}
                            worldId={worldId}
                            userId={userId}
                            view={view}
                            refetch={access.refetch}
                            pageStale={stale}
                            onUnread={announceWhenRead}
                            check={shownCheck}
                            onTransferStart={() => setCheck(null)}
                            onTransferConfirmed={transferConfirmed}
                            onTransferUncertain={startCheck}
                            onCheckAgain={() => {
                                if (shownCheck !== null) startCheck(shownCheck.login, "unknown")
                            }}
                        />
                    </>
                )}
            </div>
        </div>
    )
}

// What the person is left with once a transfer is confirmed, or once their own access shows it probably happened.
// It names only the login they typed and the role the server says they kept; nothing is looked up.
function TransferReceipt({
    record,
    worldId,
    worldName,
}: {
    record: TransferRecord
    worldId: string
    worldName: string
}) {
    const headingRef = useRef<HTMLHeadingElement>(null)
    // The receipt replaces the sharing content, so focus that was on it is gone: take it then. A control the person
    // moved to while the request was pending (or a link they chose) keeps it.
    useEffect(() => {
        const active = document.activeElement
        if (active === null || active === document.body || !active.isConnected) headingRef.current?.focus()
    }, [])
    return (
        <section className="authoring-section" aria-labelledby="sharing-receipt-heading">
            <h2 id="sharing-receipt-heading" ref={headingRef} tabIndex={-1}>
                {record.kind === "confirmed" ? "Ownership transferred" : "Transfer not confirmed"}
            </h2>
            {record.kind === "confirmed" ? (
                <>
                    <p>
                        {record.login} is now an owner of {worldName}.
                    </p>
                    <p>
                        {record.retainedRoleCode === null
                            ? "No role was kept for you."
                            : `You keep the ${roleLabel(record.retainedRoleCode)} role on this world.`}
                    </p>
                </>
            ) : (
                <p>
                    We could not confirm that ownership was transferred to {record.login}. You no longer have owner access
                    to this world, which is what a completed transfer does. This does not show whether {record.login}{" "}
                    received ownership.
                </p>
            )}
            <p>
                <Link to={`/worlds/${worldId}`}>Back to the world</Link>
                {" · "}
                <Link to="/worlds">Worlds</Link>
            </p>
        </section>
    )
}

interface ContentProps {
    worldId: string
    userId: string
    view: WorldAccessView
    refetch: () => Promise<RefetchOutcome>
    // The page's latest read failed and `view` is the last list that loaded.
    pageStale: boolean
    // The page announces a change it could not read back when a read answers.
    onUnread: (message: string) => void
    // The read of the person's own access after an unknown or refused transfer, held by the page, and what the page
    // does with a transfer: forget a check, record a confirmed transfer, start a check, check again.
    check: TransferCheck | null
    onTransferStart: () => void
    onTransferConfirmed: (login: string, result: WorldTransferResult) => void
    onTransferUncertain: (login: string, mode: TransferCheck["mode"]) => void
    onCheckAgain: () => void
}

// Asked only while leaving would lose the only chance to see or safely retry a change: a write is in flight, or a
// give-role or hosting grant ended with an unknown outcome. Typed but unsent text is not guarded. One guard for the
// page: a later reason (S02) is added here, never as a second blocker.
type DepartureReason = "saving" | "unknown" | "transfer-saving" | "transfer-unknown"

function SharingDepartureGuard({ reason, login }: { reason: DepartureReason; login: string }) {
    const guard = useUnsavedChangesGuard(true)
    const dialog =
        reason === "saving"
            ? {
                  title: "Leave while this change is being saved?",
                  description: "It may still be applied. You will not see the result here.",
              }
            : reason === "unknown"
              ? {
                    title: "Leave without knowing whether the change was saved?",
                    description: `We could not confirm whether ${login} was given access. Check the list on this page later.`,
                }
              : reason === "transfer-saving"
                ? {
                      title: "Leave while ownership is being transferred?",
                      description: "It may still be completed. You will not see the result here.",
                  }
                : {
                      title: "Leave without knowing whether ownership was transferred?",
                      description: `We could not confirm the transfer to ${login}. Come back to this page to check.`,
                  }
    return (
        <ConfirmDialog
            open={guard.blocked}
            title={dialog.title}
            description={dialog.description}
            confirmLabel="Leave"
            cancelLabel="Stay"
            onConfirm={guard.discard}
            onCancel={guard.stay}
        />
    )
}

function SharingContent({
    worldId,
    userId,
    view,
    refetch,
    pageStale,
    onUnread,
    check,
    onTransferStart,
    onTransferConfirmed,
    onTransferUncertain,
    onCheckAgain,
}: ContentProps) {
    const announce = useAnnounce()
    const { reload } = useSession()
    const [login, setLogin] = useState("")
    const [role, setRole] = useState<string>("world_editor")
    const [useLogin, setUseLogin] = useState("")
    const [pending, setPending] = useState<Pending | null>(null)
    const [transferLogin, setTransferLogin] = useState("")
    const [retain, setRetain] = useState("")
    // What the last confirmed change said, for the saved-but-not-read-back notice.
    const [confirmedText, setConfirmedText] = useState("")
    // The operation the last send was for (a retry re-sends exactly this one), and what a re-read has said since.
    const lastOperation = useRef<Operation | null>(null)
    const [lastOperationState, setLastOperationState] = useState<Operation | null>(null)
    const [settling, setSettling] = useState<Settling | null>(null)
    const settlingSeq = useRef(0)
    const [stillListed, setStillListed] = useState(false)
    const [settledNote, setSettledNote] = useState<string | null>(null)
    // The fingerprint of the transfer whose answer was lost, so a later refusal of its retry is read as what it is (a
    // committed transfer refuses a same-key retry) and never shown as a permission problem.
    const [unknownTransfer, setUnknownTransfer] = useState<string | null>(null)
    // How many times each login field has been edited, and the count each submitted operation saw. A confirmation
    // clears a field only when it was not edited at all since that submit: an edit that happens to read the same
    // after trimming ("dana" then "dana "), or one made away from and back to the submitted text, is the person's own
    // newer input and is kept. (Plain events write these refs; they are never read while rendering.)
    const edits = useRef({ login: 0, use: 0 })
    const submitted = useRef<{ operation: Operation; edits: number } | null>(null)
    const shownView = useRef(view)
    useEffect(() => {
        shownView.current = view
    })

    const mutation = useAuthoringMutation<Operation, OperationResult>({
        scopeKey: `world-sharing:${worldId}`,
        request: (operation, ctx) => {
            switch (operation.op) {
                case "assign-role":
                    return assignWorldRole(worldId, { login_name: operation.login, role_code: operation.role }, ctx)
                case "grant-use":
                    return grantWorldUse(worldId, operation.login, ctx)
                case "end-role":
                    return endWorldRole(worldId, operation.membershipId, ctx)
                case "revoke-use":
                    return revokeWorldUse(worldId, operation.grantId, ctx)
                case "transfer":
                    return transferWorldOwnership(
                        worldId,
                        { login_name: operation.login, retain_previous_owner_as: operation.retain },
                        ctx,
                    )
            }
        },
        onSuccess: async (result, operation) => {
            if (operation.op === "transfer") {
                // The page holds the receipt (this content unmounts when the person loses access) and announces it once,
                // so nothing here announces, and nothing is saved for a read-back notice.
                onTransferConfirmed(operation.login, result as WorldTransferResult)
                // The page owns this read-back (a denial is the expected answer and is explained below the receipt), so the
                // mutation is not told it failed: it would announce "Saved, but the latest data could not be loaded." as a
                // second announcement of the same outcome.
                await refetch()
                setPending(null)
                return
            }
            const text = confirmationText(operation, "changed" in result ? result.changed : true)
            setConfirmedText(text)
            // Cleared only when this very submit is the confirmed one and the field has not been edited since: anything the
            // person typed meanwhile, whatever it reads like, is theirs. An attempt that is not the latest submit clears nothing.
            const sent = submitted.current
            const own = sent !== null && JSON.stringify(sent.operation) === JSON.stringify(operation)
            if (own && operation.op === "assign-role" && edits.current.login === sent.edits) setLogin("")
            if (own && operation.op === "grant-use" && edits.current.use === sent.edits) setUseLogin("")
            const outcome = await refetch()
            setPending(null)
            if (outcome === "ok") announce(text)
            else onUnread(text)
            return outcome
        },
    })
    const refreshed = useConfirmedRefresh({
        status: mutation.status,
        reset: mutation.reset,
        what: "sharing list",
        message: confirmedText === "" ? null : confirmedText,
        read: refetch,
        pageStale,
        quietRecovery: true,
    })
    // When the dialog closes, the dialog returns focus to the control that opened it. If that control is
    // gone (the ended role's row), nothing holds focus: land on the roles heading, not on the page. The
    // dialog is a child, so its own return of focus has already run when this effect does.
    const dialogWasOpen = useRef(false)
    useEffect(() => {
        if (pending !== null) {
            dialogWasOpen.current = true
        } else if (dialogWasOpen.current) {
            dialogWasOpen.current = false
            const active = document.activeElement
            if (active === null || active === document.body) document.getElementById("sharing-roles-heading")?.focus()
        }
    }, [pending])
    const resetMutation = mutation.reset
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const pendingWrite = mutation.status.kind === "pending"
    // The lists on screen are behind the saved change, so another change waits for the read.
    const busy = pendingWrite || refreshed.held || pageStale

    // A refusal (403 or 404: the write was not applied) or a lost answer (network or 5xx: it may have been): the list
    // is read once, read only, so the page shows what the server holds now. For a row's end or revoke the data of that
    // read then settles what happened (below); for a typed login nothing can be matched without a lookup, so the
    // outcome stays unknown. The transfer keeps its own feedback (S02).
    const handledError = useRef<unknown>(null)
    const status = mutation.status
    useEffect(() => {
        if (status.kind !== "error") {
            handledError.current = null
            return
        }
        if (handledError.current === status) return
        handledError.current = status
        const operation = lastOperation.current
        if (operation === null) return
        const kind = status.error.kind
        const refused = kind === "denied" || kind === "unavailable"
        if (operation.op === "transfer") {
            // A lost answer, or a refusal of a retry of one, is settled by reading the person's own access (the page does
            // it); a first refusal re-reads too but decides nothing about a transfer. Conflicts keep their sentences.
            if (kind === "network" || kind === "server") onTransferUncertain(operation.login, "unknown")
            else if (refused)
                onTransferUncertain(operation.login, unknownTransfer === JSON.stringify(operation) ? "unknown" : "first-refused")
            return
        }
        if (!refused && kind !== "network" && kind !== "server") return
        const token = ++settlingSeq.current
        if (operation.op === "end-role" || operation.op === "revoke-use") {
            setSettling({ operation, mode: refused ? "refused" : "unknown", before: shownView.current })
        }
        void refetch().then((outcome) => {
            // A failed read says nothing about the row; a superseded one is answered by the newer read.
            if (outcome === "failed" && settlingSeq.current === token) setSettling(null)
        })
    }, [status, refetch, onTransferUncertain, unknownTransfer])

    // The first list applied after that read started is its own successful, complete answer (the list is every open
    // role and grant of the world, not a filtered or paged view), so a row id missing from it has ended.
    // This reacts to data arriving from outside (a completed read), the one case where the state it sets cannot be derived
    // while rendering: it also announces and closes a dialog, which belong to an effect.
    /* eslint-disable react-hooks/set-state-in-effect */
    useEffect(() => {
        if (settling === null || view === settling.before) return
        const { operation, mode } = settling
        setSettling(null)
        const gone =
            operation.op === "end-role"
                ? !view.assignments.some((a) => a.world_membership_id === operation.membershipId)
                : operation.op === "revoke-use"
                  ? !view.use_grants.some((g) => g.world_use_grant_id === operation.grantId)
                  : false
        if (gone) {
            const text = goneText(operation, mode === "refused")
            setSettledNote(text)
            announce(text)
            setPending(null)
            resetMutation()
        } else if (mode === "unknown") {
            setStillListed(true)
        }
    }, [view, settling, announce, resetMutation])
    /* eslint-enable react-hooks/set-state-in-effect */

    function submit(operation: Operation) {
        // Anything a re-read of an earlier operation could still say is no longer this person's question.
        settlingSeq.current += 1
        setSettling(null)
        setStillListed(false)
        setSettledNote(null)
        const outcome = mutation.submit(operation)
        if (outcome !== "ignored") {
            submitted.current = {
                operation,
                edits: operation.op === "grant-use" ? edits.current.use : edits.current.login,
            }
            lastOperation.current = operation
            setLastOperationState(operation)
        }
    }

    function changeLogin(value: string) {
        edits.current.login += 1
        setLogin(value)
    }

    function changeUseLogin(value: string) {
        edits.current.use += 1
        setUseLogin(value)
    }

    function addRole() {
        if (login.trim() === "") return
        submit({ op: "assign-role", login: login.trim(), role: role as WorldRoleCode })
    }

    function addUse() {
        if (useLogin.trim() === "") return
        submit({ op: "grant-use", login: useLogin.trim() })
    }

    // Retry re-sends the same descriptor under the same key. For a transfer that is a deliberate send again (the
    // earlier attempt may have been refused after a lost answer, which the hook does not keep as retryable).
    function retryWrite() {
        const operation = lastOperation.current
        if (operation !== null && operation.op === "transfer") {
            onTransferStart()
            submit(operation)
            return
        }
        mutation.retry()
    }

    function confirmPending() {
        if (pending === null) return
        if (pending.kind === "end-role") {
            const a = pending.assignment
            submit({ op: "end-role", membershipId: a.world_membership_id, name: a.display_name, role: a.role_code })
        } else if (pending.kind === "revoke-use") {
            const g = pending.grant
            submit({ op: "revoke-use", grantId: g.world_use_grant_id, name: g.display_name })
        } else {
            onTransferStart()
            submit({ op: "transfer", login: pending.loginName, retain: pending.retain })
        }
    }

    const transferOperation = lastOperationState !== null && lastOperationState.op === "transfer" ? lastOperationState : null
    const transferFingerprint = transferOperation === null ? null : JSON.stringify(transferOperation)
    const lostAnswer = error !== null && (error.kind === "network" || error.kind === "server")
    // Derived while rendering, so a refusal of the retry is never shown for a frame as a permission problem.
    if (lostAnswer && transferFingerprint !== null && unknownTransfer !== transferFingerprint) {
        setUnknownTransfer(transferFingerprint)
    } else if (transferFingerprint === null && unknownTransfer !== null) {
        setUnknownTransfer(null)
    } else if (transferFingerprint !== null && unknownTransfer !== null && unknownTransfer !== transferFingerprint) {
        setUnknownTransfer(null)
    }
    const refusedAfterUnknown =
        error !== null &&
        (error.kind === "denied" || error.kind === "unavailable") &&
        transferFingerprint !== null &&
        unknownTransfer === transferFingerprint
    const transferUnknown = transferOperation !== null && (lostAnswer || refusedAfterUnknown)

    const unknownGrant =
        error !== null &&
        (error.kind === "network" || error.kind === "server") &&
        lastOperationState !== null &&
        (lastOperationState.op === "assign-role" || lastOperationState.op === "grant-use")
    const departure: DepartureReason | null = pendingWrite
        ? transferOperation !== null
            ? "transfer-saving"
            : "saving"
        : transferUnknown
          ? "transfer-unknown"
          : unknownGrant
            ? "unknown"
            : null
    const departureLogin =
        lastOperationState !== null &&
        (lastOperationState.op === "assign-role" ||
            lastOperationState.op === "grant-use" ||
            lastOperationState.op === "transfer")
            ? lastOperationState.login
            : ""

    const dialog = describePending(pending, view, userId)

    return (
        <>
            {departure !== null ? <SharingDepartureGuard reason={departure} login={departureLogin} /> : null}
            <p className="authoring-page__lead">
                Share this world with other accounts. A role on the world never makes anyone a
                member of a campaign, and a campaign role never confers a role on the world.
            </p>
            {refreshed.notice}
            {settledNote !== null ? <p className="authoring-message">{settledNote}</p> : null}
            {error !== null && pending === null ? (
                <MutationStatusMessage error={error} onRetry={retryWrite} onCheckSession={reload} />
            ) : null}

            <section className="authoring-section" aria-labelledby="sharing-roles-heading">
                <h2 id="sharing-roles-heading" tabIndex={-1}>
                    People with a role
                </h2>
                <TableScroll label="World roles">
                <table className="authoring-table">
                    <caption className="visually-hidden">World roles</caption>
                    <thead>
                        <tr>
                            <th scope="col">Name</th>
                            <th scope="col">Role</th>
                            <th scope="col">Granted by</th>
                            <th scope="col">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {view.assignments.map((a) => (
                            <tr key={a.world_membership_id}>
                                <td>
                                    {a.display_name}
                                    {a.account_active ? "" : " (account disabled)"}
                                </td>
                                <td>{WORLD_ROLE_LABEL[a.role_code] ?? a.role_display_name}</td>
                                <td>{a.granted_by_display_name ?? "—"}</td>
                                <td>
                                    {a.role_code === "world_owner" && !view.may_transfer ? null : (
                                        <button
                                            type="button"
                                            className="authoring-button"
                                            disabled={busy}
                                            aria-label={`End role for ${a.display_name}, ${
                                                WORLD_ROLE_LABEL[a.role_code] ?? a.role_display_name
                                            }`}
                                            onClick={() => {
                                                mutation.reset()
                                                setStillListed(false)
                                                setSettledNote(null)
                                                setPending({ kind: "end-role", assignment: a })
                                            }}
                                        >
                                            End role
                                        </button>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                </TableScroll>

                <form
                    className="authoring-form"
                    aria-label="Give someone a role"
                    onSubmit={(event) => {
                        event.preventDefault()
                        addRole()
                    }}
                >
                    <TextField
                        label="Login name"
                        value={login}
                        onChange={changeLogin}
                        hint="The exact login name of an active account."
                    />
                    <SelectField
                        label="Role"
                        value={role}
                        options={ROLE_OPTIONS.filter((o) => view.may_transfer || o.value !== "world_owner")}
                        onChange={setRole}
                    />
                    <button type="submit" className="authoring-button authoring-button--primary" disabled={busy}>
                        Give role
                    </button>
                </form>
            </section>

            <section className="authoring-section" aria-labelledby="sharing-use-heading">
                <h2 id="sharing-use-heading">Allowed to host campaigns</h2>
                <p className="authoring-field__hint">
                    Lets a game master start a campaign on this world and nothing else: no reading
                    of drafts, no editing, no timelines. Revoking it stops new campaigns only.
                </p>
                {view.use_grants.length === 0 ? (
                    <p>No one has been given this permission.</p>
                ) : (
                    <ul className="authoring-list">
                        {view.use_grants.map((g) => (
                            <li className="authoring-list__item" key={g.world_use_grant_id}>
                                <span>
                                    {g.display_name}
                                    {g.account_active ? "" : " (account disabled)"}
                                </span>
                                <button
                                    type="button"
                                    className="authoring-button"
                                    disabled={busy}
                                    aria-label={`Revoke permission for ${g.display_name}`}
                                    onClick={() => {
                                        mutation.reset()
                                        setStillListed(false)
                                        setSettledNote(null)
                                        setPending({ kind: "revoke-use", grant: g })
                                    }}
                                >
                                    Revoke
                                </button>
                            </li>
                        ))}
                    </ul>
                )}
                <form
                    className="authoring-form"
                    aria-label="Allow someone to host campaigns"
                    onSubmit={(event) => {
                        event.preventDefault()
                        addUse()
                    }}
                >
                    <TextField
                        label="Login name"
                        value={useLogin}
                        onChange={changeUseLogin}
                        hint="Only an account with the game master system role can use it to start a campaign."
                    />
                    <button type="submit" className="authoring-button authoring-button--primary" disabled={busy}>
                        Allow hosting
                    </button>
                </form>
            </section>

            {view.may_transfer ? (
                <section className="authoring-section" aria-labelledby="sharing-transfer-heading">
                    <h2 id="sharing-transfer-heading">Transfer ownership</h2>
                    <p className="authoring-field__hint">
                        Makes another game master an Owner and ends your own Owner role. What you
                        created stays credited to you.
                    </p>
                    <form
                        className="authoring-form"
                        aria-label="Transfer ownership"
                        onSubmit={(event) => {
                            event.preventDefault()
                            if (transferLogin.trim() === "") return
                            mutation.reset()
                            onTransferStart()
                            setPending({
                                kind: "transfer",
                                loginName: transferLogin.trim(),
                                retain: retain === "" ? null : (retain as RetainedWorldRoleCode),
                            })
                        }}
                    >
                        <TextField label="New owner's login name" value={transferLogin} onChange={setTransferLogin} />
                        <SelectField
                            label="Keep me on the world as"
                            value={retain}
                            options={RETAIN_OPTIONS}
                            onChange={setRetain}
                        />
                        <button type="submit" className="authoring-button" disabled={busy}>
                            Transfer ownership…
                        </button>
                    </form>
                </section>
            ) : null}

            <ConfirmDialog
                open={pending !== null}
                title={dialog.title}
                description={dialog.description}
                confirmLabel={dialog.confirm}
                onConfirm={confirmPending}
                onCancel={() => setPending(null)}
                pending={pendingWrite}
                error={
                    error === null ? null : refusedAfterUnknown ? (
                        <TransferCheckNote check={check} onRetry={retryWrite} onCheckAgain={onCheckAgain} offerRetry />
                    ) : (
                        <>
                            <MutationStatusMessage error={error} onRetry={retryWrite} onCheckSession={reload} />
                            {stillListed ? <p>It is still listed.</p> : null}
                            {transferOperation !== null && lostAnswer ? (
                                <TransferCheckNote check={check} onRetry={retryWrite} onCheckAgain={onCheckAgain} />
                            ) : null}
                        </>
                    )
                }
            />
        </>
    )
}

// What the read of the person's own access said about an unknown transfer, in the words that read can support: still
// being an Owner is what the list said when it was read (not proof the transfer will not complete), and a read that failed
// establishes nothing.
function TransferCheckNote({
    check,
    onRetry,
    onCheckAgain,
    offerRetry = false,
}: {
    check: TransferCheck | null
    onRetry: () => void
    onCheckAgain: () => void
    offerRetry?: boolean
}) {
    if (check === null) return null
    if (check.stage === "checking") return <p role="status">Checking whether the transfer went through…</p>
    if (check.stage === "still-owner") {
        return (
            <>
                <p>
                    You are still an owner of this world, so the transfer does not appear to have been completed. That is what
                    the list said when it was read; it does not rule out a transfer still in progress.
                </p>
                {offerRetry ? (
                    <button type="button" className="authoring-button" onClick={onRetry}>
                        Retry
                    </button>
                ) : null}
            </>
        )
    }
    return (
        <>
            <p>We could not check your access, so we cannot tell whether the transfer went through.</p>
            <button type="button" className="authoring-button" onClick={onCheckAgain}>
                Check again
            </button>
        </>
    )
}

// What the person is left with, from the role they chose to keep and the other open roles the list shows for their own
// account. Those other roles are not removed by a transfer, so they are named, and a person left with none is told
// they will lose the sharing page.
function keptSentence(retain: RetainedWorldRoleCode | null, view: WorldAccessView, userId: string): string {
    if (retain !== null) return `You keep the ${roleLabel(retain)} role on this world.`
    const others = view.assignments
        .filter((a) => a.user_id === userId && a.role_code !== "world_owner")
        .map((a) => roleLabel(a.role_code))
    if (others.length === 0) {
        return "You will have no role on this world and will lose access to its sharing page."
    }
    return `You keep your ${others.join(", ")} role on this world.`
}

function describePending(
    pending: Pending | null,
    view: WorldAccessView,
    userId: string,
): { title: string; description: string; confirm: string } {
    if (pending === null) return { title: "", description: "", confirm: "Confirm" }
    switch (pending.kind) {
        case "end-role":
            return {
                title: "End this role?",
                description: `${pending.assignment.display_name} loses the ${
                    WORLD_ROLE_LABEL[pending.assignment.role_code] ?? "role"
                } role on this world immediately. What they created stays credited to them.`,
                confirm: "End role",
            }
        case "revoke-use":
            return {
                title: "Revoke this permission?",
                description: `${pending.grant.display_name} can no longer start new campaigns on this world. Campaigns they already created are not affected.`,
                confirm: "Revoke permission",
            }
        case "transfer":
            return {
                title: "Transfer ownership?",
                description:
                    "The new owner takes over sharing and settings for this world, and your own Owner role ends. " +
                    keptSentence(pending.retain, view, userId),
                confirm: "Transfer ownership",
            }
    }
}
