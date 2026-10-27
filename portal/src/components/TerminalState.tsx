import { useEffect, useRef } from "react"
import type { ReactNode } from "react"
import { Link, useLocation } from "react-router"
import { useDocumentTitle } from "../hooks/useDocumentTitle"
import type { Recovery } from "./terminalRecovery"
import "./authoring/authoring.css"

// One presentation for a destination that ends in a message instead of a page: not found,
// access denied, or an action the record does not offer (docs/UI_DESIGN.md "Unavailable and
// unauthorized destinations"). It renders content only; the caller's frame owns the page's <main>.

// A terminal destination: its own <h1>, focused once per navigation (that move is the
// announcement, so there is no live region as well), a safe document title, an explanation, and
// links to somewhere the person can go.
export function TerminalContent({
    heading,
    children,
    recovery,
}: {
    heading: string
    children: ReactNode
    recovery: readonly Recovery[]
}) {
    const headingRef = useRef<HTMLHeadingElement>(null)
    const { key } = useLocation()
    useDocumentTitle(heading)
    useEffect(() => {
        headingRef.current?.focus()
    }, [key])
    return (
        <section className="placeholder-page terminal-state">
            <h1 ref={headingRef} tabIndex={-1}>
                {heading}
            </h1>
            {children}
            {recovery.length > 0 ? (
                // A list, not a <nav>: a terminal state in the public layout has no navigation landmark.
                <ul className="terminal-state__links" aria-label="Where to go next">
                    {recovery.map((link) => (
                        <li key={link.to}>
                            <Link to={link.to}>{link.label}</Link>
                        </li>
                    ))}
                </ul>
            ) : null}
        </section>
    )
}

// A known page the person's account has no capability for: it says so and mounts nothing.
export function AccessDeniedContent({
    what,
    recovery,
}: {
    what: string
    recovery: readonly Recovery[]
}) {
    return (
        <TerminalContent heading="Access denied" recovery={recovery}>
            <p>Your account does not have access to {what}.</p>
        </TerminalContent>
    )
}

// The same, as a whole page with its own <main>, for a route outside a workspace frame.
export function AccessDeniedPage({ what, recovery }: { what: string; recovery: readonly Recovery[] }) {
    return (
        <main className="app-main">
            <AccessDeniedContent what={what} recovery={recovery} />
        </main>
    )
}
