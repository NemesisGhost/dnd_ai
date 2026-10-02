import { AccountLifecycleActions } from "../components/AccountLifecycleActions"
import { CreateAccountPanel } from "../components/CreateAccountPanel"
import { usePlatformAccounts } from "../hooks/usePlatformAccounts"
import { NotFoundPage } from "./NotFoundPage"
import type { SessionBootstrap } from "../types/bootstrap"

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

// Gated on bootstrap.is_platform_administrator as presentation only —
// GET /admin/accounts and every mutation below remain the real,
// server-authoritative gate (PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md
// §9.1's non-negotiable rule 5: "portal code may hide or disable a
// control for presentation, but every capability decision stays
// server-side").
export function AdminAccountsPage({ bootstrap }: AdminAccountsPageProps) {
    const { state, query, setQuery, retry, loadMore } = usePlatformAccounts()

    if (!bootstrap.is_platform_administrator) {
        return <NotFoundPage />
    }

    return (
        <main className="app-main">
            <section aria-labelledby="admin-accounts-heading">
                <h1 id="admin-accounts-heading">Platform accounts</h1>

                <CreateAccountPanel onCreated={retry} />

                <label htmlFor="admin-accounts-search">Search by display name or login name</label>
                <input
                    id="admin-accounts-search"
                    type="text"
                    value={query}
                    onChange={(event) => setQuery(event.currentTarget.value)}
                />

                {state.status === "loading" && <p>Loading accounts…</p>}
                {state.status === "denied" && <p>You do not have permission to view this page.</p>}
                {state.status === "error" && (
                    <>
                        <p>Accounts could not be loaded.</p>
                        <button type="button" onClick={retry}>
                            Try again
                        </button>
                    </>
                )}

                {state.status === "success" && (
                    <>
                        <table>
                            <caption>Platform accounts</caption>
                            <thead>
                                <tr>
                                    <th scope="col">Display name</th>
                                    <th scope="col">Login name</th>
                                    <th scope="col">Status</th>
                                    <th scope="col">Last login</th>
                                    <th scope="col">Active sessions</th>
                                    <th scope="col">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {state.items.map((account) => (
                                    <tr key={account.user_id}>
                                        <td>
                                            {account.display_name}
                                            {account.is_platform_administrator && (
                                                <span
                                                    className="access-badge"
                                                    aria-label="Platform administrator"
                                                >
                                                    {" "}
                                                    Platform administrator
                                                </span>
                                            )}
                                        </td>
                                        <td>
                                            {account.login_name ?? "(pending activation)"}
                                        </td>
                                        <td>{account.lifecycle_status_code}</td>
                                        <td>{formatTimestamp(account.last_login_at)}</td>
                                        <td>{account.active_session_count}</td>
                                        <td>
                                            <AccountLifecycleActions account={account} onChanged={retry} />
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>

                        {state.nextCursor !== null && (
                            <button type="button" onClick={loadMore}>
                                Load more
                            </button>
                        )}
                    </>
                )}
            </section>
        </main>
    )
}
