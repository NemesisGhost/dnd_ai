import { useState } from "react"
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
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import type {
    RetainedWorldRoleCode,
    WorldAccessView,
    WorldRoleAssignment,
    WorldRoleCode,
    WorldUseGrant,
} from "../types/worldSharing"
import { WORLD_ROLE_LABEL } from "../types/worldSharing"
import type { WorldDetail } from "../types/worldAuthoring"
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

interface Action {
    run: (ctx: { csrfToken: string; idempotencyKey: string; signal?: AbortSignal }) => Promise<unknown>
    announce: string
}

// The world's Sharing page: who holds a role on it and who may host campaigns on it. Reached
// only with `world.share` (an Owner who is also a system GM); anyone else gets the server's
// 404 or 403, shown as "not available". Every change is a confirmed or explicit action whose
// outcome is re-read from the server; nothing is optimistic. Sharing grants a *world* role or
// a permission to host a campaign: it never makes anyone a member of any campaign.
export function WorldSharingPage() {
    const { worldId = "" } = useParams()
    const world = useAuthoringResource<WorldDetail>(worldPath(worldId))
    const access = useAuthoringResource<WorldAccessView>(worldAccessPath(worldId))
    const headingRef = usePageArrival(access.state.kind !== "loading")
    const worldName = world.state.kind === "ready" ? world.state.data.name : "World"

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
                ) : access.state.kind !== "ready" ? (
                    <p role="alert">
                        Sharing is not available for this world with your account.{" "}
                        <Link to={`/worlds/${worldId}`}>Back to the world</Link>
                    </p>
                ) : (
                    <SharingContent
                        worldId={worldId}
                        view={access.state.data}
                        refetch={access.refetch}
                    />
                )}
            </div>
        </div>
    )
}

interface ContentProps {
    worldId: string
    view: WorldAccessView
    refetch: () => Promise<void>
}

function SharingContent({ worldId, view, refetch }: ContentProps) {
    const announce = useAnnounce()
    const { reload } = useSession()
    const [login, setLogin] = useState("")
    const [role, setRole] = useState<string>("world_editor")
    const [useLogin, setUseLogin] = useState("")
    const [pending, setPending] = useState<Pending | null>(null)
    const [transferLogin, setTransferLogin] = useState("")
    const [retain, setRetain] = useState("")
    const [lastAnnounce, setLastAnnounce] = useState("")

    const mutation = useAuthoringMutation<Action, unknown>({
        scopeKey: `world-sharing:${worldId}`,
        request: (action, ctx) => action.run(ctx),
        onSuccess: async () => {
            await refetch()
            setPending(null)
            announce(lastAnnounce)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const busy = mutation.status.kind === "pending"

    function submit(action: Action) {
        setLastAnnounce(action.announce)
        mutation.submit(action)
    }

    function addRole() {
        if (login.trim() === "") return
        const loginName = login.trim()
        submit({
            run: (ctx) => assignWorldRole(worldId, { login_name: loginName, role_code: role as WorldRoleCode }, ctx),
            announce: "Role assigned",
        })
        setLogin("")
    }

    function addUse() {
        if (useLogin.trim() === "") return
        const loginName = useLogin.trim()
        submit({ run: (ctx) => grantWorldUse(worldId, loginName, ctx), announce: "Permission to host campaigns granted" })
        setUseLogin("")
    }

    function confirmPending() {
        if (pending === null) return
        if (pending.kind === "end-role") {
            const id = pending.assignment.world_membership_id
            submit({ run: (ctx) => endWorldRole(worldId, id, ctx), announce: "Role ended" })
        } else if (pending.kind === "revoke-use") {
            const id = pending.grant.world_use_grant_id
            submit({ run: (ctx) => revokeWorldUse(worldId, id, ctx), announce: "Permission revoked" })
        } else {
            const { loginName, retain: keep } = pending
            submit({
                run: (ctx) =>
                    transferWorldOwnership(
                        worldId,
                        { login_name: loginName, retain_previous_owner_as: keep },
                        ctx,
                    ),
                announce: "Ownership transferred",
            })
        }
    }

    const dialog = describePending(pending)

    return (
        <>
            <p className="authoring-page__lead">
                Share this world with other accounts. A role on the world never makes anyone a
                member of a campaign, and a campaign role never confers a role on the world.
            </p>
            {error !== null && pending === null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}

            <section className="authoring-section" aria-labelledby="sharing-roles-heading">
                <h2 id="sharing-roles-heading">People with a role</h2>
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
                        onChange={setLogin}
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
                    <TextField label="Login name of a game master" value={useLogin} onChange={setUseLogin} />
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
                pending={busy}
                error={
                    error === null ? null : (
                        <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
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
