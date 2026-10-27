import { TerminalContent } from "../components/TerminalState"
import { HOME_RECOVERY } from "../components/terminalRecovery"

// The not-found content itself, for a route already inside a frame that owns the page's <main>.
// It is for destinations that do not exist, and for records that are missing or hidden, which are
// deliberately indistinguishable. A known page the account lacks a capability for says so instead
// (AccessDeniedContent).
export function NotFoundContent() {
    return (
        <TerminalContent heading="Page not found" recovery={[HOME_RECOVERY]}>
            <p>The requested portal page does not exist.</p>
        </TerminalContent>
    )
}

// The not-found presentation for unknown routes, with its own <main> (navigation plan §3.1, §6
// non-disclosure).
export function NotFoundPage() {
    return (
        <main className="app-main">
            <NotFoundContent />
        </main>
    )
}
