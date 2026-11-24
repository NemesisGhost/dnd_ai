import { useEffect, useId, useRef, useState } from "react"
import { Link, NavigationType, useLocation, useNavigationType, useSearchParams } from "react-router"
import {
    AccountLifecycleActions,
    type IssuedPasswordReset,
} from "../components/AccountLifecycleActions"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { TableScroll } from "../components/TableScroll"
import { OneTimeSecretPanel } from "../components/OneTimeSecretPanel"
import { usePlatformAccounts } from "../hooks/usePlatformAccounts"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import {
    ACCOUNTS_NEW_PATH,
    accountsReturnState,
    isValidAccountsQuery,
    readAccountsFocus,
    readAccountsQuery,
} from "../navigation/platformAccountsReturn"
import { AccessDeniedPage } from "../components/TerminalState"
import { HOME_RECOVERY } from "../components/terminalRecovery"
import type { SessionBootstrap } from "../types/bootstrap"
import type { PlatformAccount } from "../types/platformAccounts"
import { SystemRolesPanel, SystemRolesReceipt } from "../components/SystemRolesPanel"
import { useSession } from "../context/SessionContext"
import { useSystemRoleSave } from "../hooks/useSystemRoleSave"
import { bootstrapRefreshOutcome } from "../utils/refreshOutcome"
import { buildFragmentLink } from "../utils/oneTimeLink"
import { canGrantAdmin, canManageAccounts, canManageSystemRoles } from "../utils/systemAccess"
import type { SystemRoleCode } from "../utils/systemAccess"
import { isDirty, knownRoles, mayHaveBeenSent, stagedChanges } from "../utils/systemRoleStaging"

interface AdminAccountsPageProps {
    bootstrap: SessionBootstrap
}

function formatTimestamp(timestamp: string | null): string {
    if (timestamp === null) {
        return "Never"
    }
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
        new Date(timestamp),
    )
}

// Gated on the server-computed `accounts.manage` capability as presentation only —
// GET /admin/accounts and every mutation below remain the real,
// server-authoritative gate (PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md
// §9.1's non-negotiable rule 5: "portal code may hide or disable a
// control for presentation, but every capability decision stays
// server-side").
export function AdminAccountsPage({ bootstrap }: AdminAccountsPageProps) {
    if (!canManageAccounts(bootstrap)) {
        return <AccessDeniedPage what="platform accounts" recovery={[HOME_RECOVERY]} />
    }
    return <AuthorizedAccountsPage bootstrap={bootstrap} />
}

// The page's one departure guard (react-router supports a single blocker per page). It is mounted only while
// something would be lost by leaving: a shown reset link (never shown again) or unsaved role changes; a search
// change keeps the path and is not a departure. Both reasons share this one question.
type DepartureReason = "saving" | "partial" | "dirty"

function AccountsDepartureGuard({
    resetShown,
    rolesFor,
    reason,
}: {
    resetShown: boolean
    rolesFor: string | null
    reason: DepartureReason | null
}) {
    const guard = useUnsavedChangesGuard(true)
    const resetSentence = resetShown ? " The password-reset link shown on this page will also be lost." : ""
    let dialog: { title: string; description: string }
    if (rolesFor !== null && reason === "saving") {
        // Requests are on their way: they may still be applied, and this page will not be here to say so.
        dialog = {
            title: "Leave while role changes are being saved?",
            description: `Changes already sent may still be saved. You will not see their result.${resetSentence}`,
        }
    } else if (rolesFor !== null && reason === "partial") {
        // Something was sent and may be applied, so "not saved" would not be true.
        dialog = {
            title: "Leave with role changes not fully saved?",
            description: `Some changes to ${rolesFor}'s system roles may already be saved. Leaving discards the changes still staged here and the record of what happened. Check the account's roles in the list afterwards.${resetSentence}`,
        }
    } else if (rolesFor !== null) {
        dialog = {
            title: "Discard unsaved role changes?",
            description: `Your changes to ${rolesFor}'s system roles have not been saved.${resetSentence}`,
        }
    } else {
        dialog = {
            title: "Leave without the password-reset link?",
            description: "It is shown once and cannot be shown again.",
        }
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

// One account's roles being edited. Held by the page, above the list's loading boundary, so a reload of the
// list cannot drop it. `snapshot` is the account as it was when the first change was made.
interface RoleEdit {
    userId: string
    snapshot: PlatformAccount
    draft: readonly SystemRoleCode[]
    focusSignal: number
}

function AuthorizedAccountsPage({ bootstrap }: AdminAccountsPageProps) {
    const [params, setParams] = useSearchParams()
    const location = useLocation()
    const navigationType = useNavigationType()
    // The search lives in the address (?q=), so it survives a reload, Back and the trip to the creation page.
    const addressQuery = readAccountsQuery(params)
    // The field keeps its own text while typing; an address that changed from outside (Back) replaces it.
    const [text, setText] = useState(addressQuery)
    const [textFor, setTextFor] = useState(addressQuery)
    if (textFor !== addressQuery) {
        setTextFor(addressQuery)
        setText(addressQuery)
    }
    const { state, retry, loadMore, replaceAccount } = usePlatformAccounts(addressQuery)
    const { refresh, reload } = useSession()
    // Transient React memory only. Lives above the account-list loading
    // boundary so the refetch that follows issuance cannot unmount it.
    const [issuedReset, setIssuedReset] = useState<IssuedPasswordReset | null>(null)

    // The roles panel (system_roles.manage only). While it is clean it follows the latest list item for its
    // account; once changes are staged its baseline stays as it was.
    const canManageRoles = canManageSystemRoles(bootstrap)
    const [roleEdit, setRoleEdit] = useState<RoleEdit | null>(null)
    const reasonId = useId()
    const editIdPrefix = useId()
    const searchRef = useRef<HTMLInputElement>(null)
    const closedFor = useRef<string | null>(null)
    // Losing system_roles.manage drops the panel and its draft for good; regaining it does not bring them back.
    if (!canManageRoles && roleEdit !== null) {
        setRoleEdit(null)
    }
    const active = canManageRoles ? roleEdit : null
    const [confirmSelf, setConfirmSelf] = useState(false)
    const rolesDirty = active !== null && isDirty(active.snapshot.system_roles, active.draft)
    const listed =
        active !== null && state.status === "success"
            ? state.items.find((item) => item.user_id === active.userId)
            : undefined
    const editing = active === null ? null : rolesDirty ? active.snapshot : (listed ?? active.snapshot)
    const editingDraft =
        active === null || editing === null ? [] : rolesDirty ? active.draft : knownRoles(editing.system_roles)

    // Saving: one request per change, one at a time, then the account's roles are read again (never the whole list).
    const save = useSystemRoleSave({
        csrfToken: bootstrap.csrf_token,
        selfUserId: bootstrap.user.user_id,
        onReconciled: (account, draft) => {
            replaceAccount(account)
            setRoleEdit((current) =>
                current !== null && current.userId === account.user_id
                    ? { ...current, snapshot: account, draft }
                    : current,
            )
        },
    })
    const { clear: clearSave } = save
    // Losing system_roles.manage stops anything outstanding: no later step is sent and no result is kept.
    useEffect(() => {
        if (!canManageRoles) {
            clearSave()
        }
    }, [canManageRoles, clearSave])
    const mine = active !== null && save.state.userId === active.userId
    const savePhase = mine ? save.state.phase : "idle"
    const ledger = mine ? save.state.ledger : []
    const saving = savePhase === "saving" || savePhase === "reconciling"
    const busy = saving || savePhase === "check_failed"
    const locked = rolesDirty || busy
    const receipt = mine ? (save.ownAdminRemoved ? "removed" : savePhase === "access_unknown" ? "unknown" : null) : null
    const ownAccount = editing !== null && editing.user_id === bootstrap.user.user_id
    const departure: DepartureReason | null = saving
        ? "saving"
        : (rolesDirty || savePhase === "check_failed") && mayHaveBeenSent(ledger)
          ? "partial"
          : rolesDirty
            ? "dirty"
            : null

    function startSave() {
        if (active === null || editing === null) {
            return
        }
        save.save(editing, stagedChanges(editing.system_roles, editingDraft, ownAccount))
    }

    function requestSave() {
        if (editing === null) {
            return
        }
        const changes = stagedChanges(editing.system_roles, editingDraft, ownAccount)
        if (ownAccount && changes.some((change) => change.code === "admin" && change.action === "remove")) {
            setConfirmSelf(true)
            return
        }
        startSave()
    }

    async function continueAfterReceipt() {
        if ((await bootstrapRefreshOutcome(refresh)) === "failed") {
            reload()
        }
    }

    function openRoles(account: PlatformAccount) {
        if (active !== null && active.userId === account.user_id) {
            setRoleEdit({ ...active, focusSignal: active.focusSignal + 1 })
            return
        }
        if (locked) {
            return
        }
        clearSave()
        setRoleEdit({
            userId: account.user_id,
            snapshot: account,
            draft: knownRoles(account.system_roles),
            focusSignal: (active?.focusSignal ?? 0) + 1,
        })
    }

    function toggleRole(code: SystemRoleCode, checked: boolean) {
        if (active === null || editing === null) {
            return
        }
        const rest = editingDraft.filter((held) => held !== code)
        setRoleEdit({
            userId: active.userId,
            snapshot: editing,
            draft: checked ? [...rest, code] : rest,
            focusSignal: active.focusSignal,
        })
    }

    function closeRoles() {
        closedFor.current = active?.userId ?? null
        clearSave()
        setRoleEdit(null)
    }

    // After the panel closes, focus returns to that account's Edit roles button, or to the search field when the
    // row is gone. Focus the person moved to a control of their own meanwhile is left where it is.
    useEffect(() => {
        if (roleEdit !== null || closedFor.current === null) {
            return
        }
        const userId = closedFor.current
        closedFor.current = null
        const current = document.activeElement
        if (current !== null && current !== document.body && current.isConnected) {
            return
        }
        const button = document.getElementById(`${editIdPrefix}${userId}`)
        ;(button ?? searchRef.current)?.focus()
    }, [roleEdit, editIdPrefix])

    // Back from the creation page (a PUSH carrying the marker) lands on the Create account link; Back/Forward,
    // a reload and every other arrival move nothing, and a control the person already chose keeps focus.
    const createLinkRef = useRef<HTMLAnchorElement>(null)
    const arrivedFor = useRef<string | null>(null)
    useEffect(() => {
        if (arrivedFor.current === location.key) {
            return
        }
        arrivedFor.current = location.key
        if (navigationType !== NavigationType.Push || !readAccountsFocus(location.state)) {
            return
        }
        const active = document.activeElement
        if (active === null || active === document.body) {
            createLinkRef.current?.focus()
        }
    }, [location.key, location.state, navigationType])

    function changeText(next: string) {
        if (!isValidAccountsQuery(next)) {
            return
        }
        setText(next)
        setTextFor(next)
        setParams(next === "" ? {} : { q: next }, { replace: true })
    }

    return (
        <main className="app-main">
            <section aria-labelledby="admin-accounts-heading">
                <h1 id="admin-accounts-heading">Platform accounts</h1>

                {(issuedReset !== null || (departure !== null && receipt === null)) && (
                    <AccountsDepartureGuard
                        resetShown={issuedReset !== null}
                        rolesFor={departure !== null && receipt === null && editing !== null ? editing.display_name : null}
                        reason={receipt === null ? departure : null}
                    />
                )}

                <ConfirmDialog
                    open={confirmSelf && active !== null}
                    title="Remove your own Administrator role?"
                    description="You will lose Platform accounts and system-role management as soon as it is saved. Another administrator would have to give it back."
                    confirmLabel="Remove my role"
                    cancelLabel="Keep editing"
                    onConfirm={() => {
                        setConfirmSelf(false)
                        startSave()
                    }}
                    onCancel={() => setConfirmSelf(false)}
                />

                {receipt !== null ? (
                    <SystemRolesReceipt kind={receipt} ledger={ledger} onContinue={() => void continueAfterReceipt()} />
                ) : (
                <>

                <p>
                    <Link
                        ref={createLinkRef}
                        to={ACCOUNTS_NEW_PATH}
                        state={accountsReturnState(addressQuery)}
                    >
                        Create account
                    </Link>
                </p>

                {issuedReset !== null && (
                    <>
                        <OneTimeSecretPanel
                            heading={`Copy the password-reset link for ${issuedReset.displayName} now`}
                            description={`This link is for ${issuedReset.displayName} only, is shown once, and cannot be recovered later. It expires ${formatTimestamp(issuedReset.expiresAt)}. No email is sent; send it to the account holder out of band.`}
                            secretLabel="Password-reset link"
                            secret={buildFragmentLink("/reset-password", issuedReset.rawToken)}
                            onDismiss={() => setIssuedReset(null)}
                        />
                    </>
                )}

                {active !== null && editing !== null && (
                    <SystemRolesPanel
                        key={active.userId}
                        account={editing}
                        draft={editingDraft}
                        ownAccount={editing.user_id === bootstrap.user.user_id}
                        canGrantAdmin={canGrantAdmin(bootstrap)}
                        reasonId={reasonId}
                        focusSignal={active.focusSignal}
                        phase={savePhase}
                        checking={mine && save.state.checking}
                        ledger={ledger}
                        onToggle={toggleRole}
                        onSave={requestSave}
                        onCheck={save.checkAgain}
                        onCancel={closeRoles}
                        onClose={closeRoles}
                    />
                )}

                <label htmlFor="admin-accounts-search">Search by display name or login name</label>
                <input
                    ref={searchRef}
                    id="admin-accounts-search"
                    type="text"
                    maxLength={200}
                    value={text}
                    onChange={(event) => changeText(event.currentTarget.value)}
                />

                {state.status === "loading" && <p>Loading accounts…</p>}
                {state.status === "denied" && <p>You do not have permission to view this page.</p>}
                {state.status === "error" && (
                    <>
                        <p>Accounts could not be loaded.</p>
                        <button type="button" className="authoring-button" onClick={retry}>
                            Try again
                        </button>
                    </>
                )}

                {state.status === "success" && (
                    <>
                        <TableScroll label="Platform accounts">
                        <table className="admin-accounts__table">
                            <caption>Platform accounts</caption>
                            <thead>
                                <tr>
                                    <th scope="col">Display name</th>
                                    <th scope="col">Login name</th>
                                    <th scope="col">System roles</th>
                                    <th scope="col">Status</th>
                                    <th scope="col">Last login</th>
                                    <th scope="col" className="admin-accounts__numeric">
                                        Active sessions
                                    </th>
                                    <th scope="col">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {state.items.map((account) => (
                                    <tr key={account.user_id}>
                                        <td>
                                            <span className="admin-accounts__name">
                                                {account.display_name}
                                            </span>
                                            {(account.stranded_world_count ?? 0) > 0 && (
                                                <span className="access-badge" role="note">
                                                    Owns {account.stranded_world_count} world
                                                    {account.stranded_world_count === 1 ? "" : "s"} no
                                                    one can currently manage
                                                </span>
                                            )}
                                            {account.is_platform_administrator && (
                                                <span
                                                    className="access-badge admin-accounts__admin-badge"
                                                    aria-label="Platform administrator"
                                                >
                                                    Platform administrator
                                                </span>
                                            )}
                                        </td>
                                        <td>
                                            {account.login_name ?? "(pending activation)"}
                                        </td>
                                        <td>
                                            {account.system_roles.length === 0
                                                ? "None"
                                                : account.system_roles.join(", ")}
                                            {canManageRoles && (
                                                <button
                                                    type="button"
                                                    id={`${editIdPrefix}${account.user_id}`}
                                                    className="authoring-button"
                                                    aria-label={`Edit roles for ${account.display_name}`}
                                                    disabled={locked && active?.userId !== account.user_id}
                                                    aria-describedby={
                                                        locked && active?.userId !== account.user_id
                                                            ? reasonId
                                                            : undefined
                                                    }
                                                    onClick={() => openRoles(account)}
                                                >
                                                    Edit roles
                                                </button>
                                            )}
                                        </td>
                                        <td>
                                            <span
                                                className={
                                                    account.lifecycle_status_code === "active"
                                                        ? "admin-accounts__status admin-accounts__status--active"
                                                        : "admin-accounts__status"
                                                }
                                            >
                                                {account.lifecycle_status_code}
                                            </span>
                                        </td>
                                        <td>{formatTimestamp(account.last_login_at)}</td>
                                        <td className="admin-accounts__numeric">
                                            {account.active_session_count}
                                        </td>
                                        <td>
                                            <AccountLifecycleActions
                                                account={account}
                                                onChanged={retry}
                                                onResetStarted={() => setIssuedReset(null)}
                                                onResetIssued={setIssuedReset}
                                            />
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                        </TableScroll>

                        {state.nextCursor !== null && (
                            <button type="button" className="authoring-button" onClick={loadMore}>
                                Load more
                            </button>
                        )}
                    </>
                )}
                </>
                )}
            </section>
        </main>
    )
}
