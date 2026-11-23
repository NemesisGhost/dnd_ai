import { Link, NavigationType, useLocation, useNavigationType } from "react-router"
import { CreateAccountPanel } from "../components/CreateAccountPanel"
import { AccessDeniedPage } from "../components/TerminalState"
import { HOME_RECOVERY } from "../components/terminalRecovery"
import { usePageArrival } from "../hooks/usePageArrival"
import {
    ACCOUNTS_FOCUS_STATE,
    ACCOUNTS_LIST_PATH,
    readAccountsReturn,
} from "../navigation/platformAccountsReturn"
import type { SessionBootstrap } from "../types/bootstrap"
import { canGrantAdmin, canManageAccounts } from "../utils/systemAccess"

interface CreateAccountPageProps {
    bootstrap: SessionBootstrap
}

// Gated on the server-computed `accounts.manage` capability as presentation only; POST /admin/accounts stays the
// real gate. The route adapter in App.tsx applies the same check before this mounts, and keys the page by the
// signed-in account so no value, message or one-time link crosses an account change.
export function CreateAccountPage({ bootstrap }: CreateAccountPageProps) {
    if (!canManageAccounts(bootstrap)) {
        return <AccessDeniedPage what="platform accounts" recovery={[HOME_RECOVERY]} />
    }
    return <AuthorizedCreateAccountPage canGrantAdmin={canGrantAdmin(bootstrap)} />
}

function AuthorizedCreateAccountPage({ canGrantAdmin }: { canGrantAdmin: boolean }) {
    const location = useLocation()
    const navigationType = useNavigationType()
    // Focus moves to the heading when this page is opened by a link (PUSH). Back, Forward and a reload leave
    // focus where the browser put it.
    const headingRef = usePageArrival(navigationType === NavigationType.Push)
    // Only the list's pathname and a validated search can come back: never an address taken from state.
    const returnTo = { pathname: ACCOUNTS_LIST_PATH, search: readAccountsReturn(location.state) }

    return (
        <main className="app-main">
            <section aria-labelledby="create-account-heading">
                <p className="authoring-page__breadcrumb">
                    <Link to={returnTo} state={ACCOUNTS_FOCUS_STATE}>
                        Platform accounts
                    </Link>
                </p>
                <h1 id="create-account-heading" ref={headingRef} tabIndex={-1}>
                    Create account
                </h1>
                <CreateAccountPanel returnTo={returnTo} canGrantAdmin={canGrantAdmin} />
            </section>
        </main>
    )
}
