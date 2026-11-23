import { useEffect, useRef, useState } from "react"
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
import { SystemRolesEditor } from "../components/SystemRolesEditor"
import { buildFragmentLink } from "../utils/oneTimeLink"
import { canGrantAdmin, canManageAccounts, canManageSystemRoles } from "../utils/systemAccess"

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

// Mounted only while a reset link is shown: that link is lost for good on a departure, so leaving the page asks
// (a search change keeps the path and is not a departure). Dismissing the link unmounts this and releases the guard.
function ResetLinkGuard() {
    const guard = useUnsavedChangesGuard(true)
    return (
        <ConfirmDialog
            open={guard.blocked}
            title="Leave without the password-reset link?"
            description="It is shown once and cannot be shown again."
            confirmLabel="Leave"
            cancelLabel="Stay"
            onConfirm={guard.discard}
            onCancel={guard.stay}
        />
    )
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
    const { state, retry, loadMore } = usePlatformAccounts(addressQuery)
    // Transient React memory only. Lives above the account-list loading
    // boundary so the refetch that follows issuance cannot unmount it.
    const [issuedReset, setIssuedReset] = useState<IssuedPasswordReset | null>(null)

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
                        <ResetLinkGuard />
                        <OneTimeSecretPanel
                            heading={`Copy the password-reset link for ${issuedReset.displayName} now`}
                            description={`This link is for ${issuedReset.displayName} only, is shown once, and cannot be recovered later. It expires ${formatTimestamp(issuedReset.expiresAt)}. No email is sent; send it to the account holder out of band.`}
                            secretLabel="Password-reset link"
                            secret={buildFragmentLink("/reset-password", issuedReset.rawToken)}
                            onDismiss={() => setIssuedReset(null)}
                        />
                    </>
                )}

                <label htmlFor="admin-accounts-search">Search by display name or login name</label>
                <input
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
                                            {canManageSystemRoles(bootstrap) && (
                                                <SystemRolesEditor
                                                    account={account}
                                                    canGrantAdmin={canGrantAdmin(bootstrap)}
                                                    onChanged={retry}
                                                />
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
            </section>
        </main>
    )
}
