import { TableScroll } from "../components/TableScroll"
import { useEffect, useRef, useState } from "react"
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
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { RefetchOutcome } from "../hooks/useAuthoringResource"
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
    // The signed-in account keys the content below, with the world: nothing typed, shown or unresolved can be carried
    // to another account or world. (The loading branch below already unmounts it when either changes; the key keeps
    // that true if the read ever answers without it.)
    const { state: sessionState } = useSession()
    const userId = sessionState.status === "authenticated" ? sessionState.bootstrap.user.user_id : ""
    // A change saved without its read-back is announced when a read answers: with the list, or with
    // the denial that is the truth after a transfer.
    const announceWhenRead = useAnnounceWhenRead(
        (access.state.kind === "ready" && !access.state.refreshing) ||
            access.state.kind === "denied" ||
            access.state.kind === "unavailable",
        access.state,
    )
    // Once the page has shown the controls, a read that no longer allows them (a transfer that ended the
    // person's own Owner role) replaces the controls, the dialog and the button that had focus. Focus then
    // goes to the page heading, which is followed by the explanation, instead of falling to the page.
    const wasReady = useRef(false)
    const shown = view !== null
    useEffect(() => {
        if (shown) {
            wasReady.current = true
        } else if (wasReady.current && access.state.kind !== "loading") {
            wasReady.current = false
            headingRef.current?.focus()
        }
    }, [shown, access.state.kind, headingRef])

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
                {access.state.kind === "loading" ? (
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
                            view={view}
                            refetch={access.refetch}
                            pageStale={stale}
                            onUnread={announceWhenRead}
                        />
                    </>
                )}
            </div>
        </div>
    )
}

interface ContentProps {
    worldId: string
    view: WorldAccessView
    refetch: () => Promise<RefetchOutcome>
    // The page's latest read failed and `view` is the last list that loaded.
    pageStale: boolean
    // The page announces a change it could not read back when a read answers.
    onUnread: (message: string) => void
}

// Asked only while leaving would lose the only chance to see or safely retry a change: a write is in flight, or a
// give-role or hosting grant ended with an unknown outcome. Typed but unsent text is not guarded. One guard for the
// page: a later reason (S02) is added here, never as a second blocker.
function SharingDepartureGuard({ reason, login }: { reason: "saving" | "unknown"; login: string }) {
    const guard = useUnsavedChangesGuard(true)
    const dialog =
        reason === "saving"
            ? {
                  title: "Leave while this change is being saved?",
                  description: "It may still be applied. You will not see the result here.",
              }
            : {
                  title: "Leave without knowing whether the change was saved?",
                  description: `We could not confirm whether ${login} was given access. Check the list on this page later.`,
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

function SharingContent({ worldId, view, refetch, pageStale, onUnread }: ContentProps) {
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
        if (operation === null || operation.op === "transfer") return
        const kind = status.error.kind
        const refused = kind === "denied" || kind === "unavailable"
        if (!refused && kind !== "network" && kind !== "server") return
        const token = ++settlingSeq.current
        if (operation.op === "end-role" || operation.op === "revoke-use") {
            setSettling({ operation, mode: refused ? "refused" : "unknown", before: shownView.current })
        }
        void refetch().then((outcome) => {
            // A failed read says nothing about the row; a superseded one is answered by the newer read.
            if (outcome === "failed" && settlingSeq.current === token) setSettling(null)
        })
    }, [status, refetch])

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

    function confirmPending() {
        if (pending === null) return
        if (pending.kind === "end-role") {
            const a = pending.assignment
            submit({ op: "end-role", membershipId: a.world_membership_id, name: a.display_name, role: a.role_code })
        } else if (pending.kind === "revoke-use") {
            const g = pending.grant
            submit({ op: "revoke-use", grantId: g.world_use_grant_id, name: g.display_name })
        } else {
            submit({ op: "transfer", login: pending.loginName, retain: pending.retain })
        }
    }

    const unknownGrant =
        error !== null &&
        (error.kind === "network" || error.kind === "server") &&
        lastOperationState !== null &&
        (lastOperationState.op === "assign-role" || lastOperationState.op === "grant-use")
    const departure: "saving" | "unknown" | null = pendingWrite ? "saving" : unknownGrant ? "unknown" : null
    const departureLogin =
        lastOperationState !== null && (lastOperationState.op === "assign-role" || lastOperationState.op === "grant-use")
            ? lastOperationState.login
            : ""

    const dialog = describePending(pending)

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
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
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
                    error === null ? null : (
                        <>
                            <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                            {stillListed ? <p>It is still listed.</p> : null}
                        </>
                    )
                }
            />
        </>
    )
}

function describePending(pending: Pending | null): { title: string; description: string; confirm: string } {
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
                    "The new owner takes over sharing and settings for this world, and your own Owner role ends." +
                    (pending.retain === null ? "" : ` You keep the ${WORLD_ROLE_LABEL[pending.retain] ?? "chosen"} role.`),
                confirm: "Transfer ownership",
            }
    }
}
