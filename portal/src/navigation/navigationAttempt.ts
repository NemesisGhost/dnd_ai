import type { DataRouter } from "react-router"

// Ownership of one requested navigation (P02-4 correction). A sidebar click asks the router for one
// destination; the menu and the drawer may close only when *that* request arrives. A new history entry
// whose pathname matches is not evidence: Back, a REPLACE, a redirect or another action can produce one.
//
// What the router offers, and what this uses (react-router 8, `createRouter`):
//   - `navigate(to)` mints a fresh `Location` (with its own `key`) per request and either
//       * hands it to the registered blocker (`blockers`, state "blocked", `location`), or
//       * starts it (`navigation.location` while a loader runs), and commits that same object
//         (`state.location.key` equals the key it carried in flight);
//   - answering the question Leave calls `blocker.proceed()`: the blocker goes "proceeding" and the router
//     navigates again, with a *new* key but the same destination; Stay resets the blocker to idle;
//   - a loader redirect continues the navigation under a new key and marks that location with
//     `state._isRedirect` (only the router writes it);
//   - an interrupting navigation replaces the in-flight one; a failed loader commits the location with
//     route errors.
// Nothing is written to history or router state to track any of this, and the click's own state (task,
// context) is left as the link set it.
//
// The contract, per phase:
//   awaiting    The click was recorded; the router has shown nothing yet. The first thing seen decides:
//               blocked or in flight at the requested destination -> that request is ours (asked/loading);
//               a first commit of the requested destination by PUSH or REPLACE with nothing in between
//               (a navigation with nothing to wait for commits without being seen in flight) -> accepted;
//               a REPLACE of the entry we left, at the address we left (the stamp the selected-context owners
//               write) -> ignored; anything else -> cancelled.
//   asked       Our request is held by the unsaved-changes question. The same blocked request stays.
//               "proceeding" (Leave) -> proceeding. Idle again (Stay) or a different blocked request
//               -> cancelled. Any commit -> cancelled.
//   proceeding  The router is navigating again for the same destination: that navigation is ours.
//   loading     In flight. Committing the key we saw -> accepted (cancelled if the route failed).
//               A redirect (`_isRedirect`) continues it under its new key and destination. Any other
//               navigation or commit, or the navigation ending without a commit -> cancelled.
// A redirect made later by a component (`<Navigate>`) is a separate navigation after our arrival: the
// arrival already settled this request, so it neither re-closes nor leaves anything pending.

export interface AttemptLocation {
    key: string
    pathname: string
    search: string
    hash: string
    state?: unknown
}

export interface AttemptView {
    // The committed location and how it was reached.
    location: AttemptLocation
    action: "PUSH" | "REPLACE" | "POP"
    // The navigation the router has in flight, if any.
    navigating: AttemptLocation | null
    // The request held by a blocker's question, and the one a Leave sent on its way.
    blocked: AttemptLocation | null
    proceeding: AttemptLocation | null
    // The committed location carries a route error (a failed loader).
    failed: boolean
}

export type AttemptStatus = "pending" | "accepted" | "cancelled"

/** The full destination: path (without a trailing slash), query and hash. */
export function hrefOf(location: { pathname: string; search: string; hash: string }): string {
    const path = location.pathname.length > 1 ? location.pathname.replace(/\/+$/, "") : location.pathname
    return `${path}${location.search}${location.hash}`
}

function isRedirect(location: AttemptLocation): boolean {
    const state = location.state
    return typeof state === "object" && state !== null && (state as { _isRedirect?: unknown })._isRedirect === true
}

type Phase = "awaiting" | "asked" | "proceeding" | "loading"

export class NavigationAttempt {
    private requested: string
    private readonly leftHref: string
    private lastCommitKey: string
    private phase: Phase = "awaiting"
    // The key of the request that is ours while it is blocked or in flight.
    private ownedKey: string | null = null
    private status: AttemptStatus = "pending"

    constructor(requested: { pathname: string; search: string; hash: string }, left: { key: string; href: string }) {
        this.requested = hrefOf(requested)
        this.leftHref = left.href
        this.lastCommitKey = left.key
    }

    observe(view: AttemptView): AttemptStatus {
        if (this.status !== "pending") return this.status
        this.status = view.location.key !== this.lastCommitKey ? this.committed(view) : this.progressed(view)
        return this.status
    }

    private committed(view: AttemptView): AttemptStatus {
        const location = view.location
        this.lastCommitKey = location.key
        if (view.failed) return "cancelled"
        const arrived = hrefOf(location) === this.requested && view.action !== "POP"
        switch (this.phase) {
            case "loading":
                if (location.key === this.ownedKey && arrived) return "accepted"
                // Our request was redirected by a loader: the router continued it under a new location it
                // marked itself, and that location may commit without ever being seen in flight. Only a
                // PUSH or REPLACE counts (a POP back to such an entry carries the same mark), and any other
                // navigation, which does not carry it, still cancels.
                return isRedirect(location) && view.action !== "POP" ? "accepted" : "cancelled"
            case "asked":
                return "cancelled"
            case "proceeding":
                return arrived ? "accepted" : "cancelled"
            case "awaiting":
                if (arrived) return "accepted"
                // The stamp of the entry we left: same address, written by REPLACE, not a navigation.
                if (view.action === "REPLACE" && hrefOf(location) === this.leftHref) return "pending"
                return "cancelled"
        }
    }

    private progressed(view: AttemptView): AttemptStatus {
        const { blocked, proceeding, navigating } = view
        switch (this.phase) {
            case "awaiting":
                if (blocked !== null) {
                    if (hrefOf(blocked) !== this.requested) return "cancelled"
                    this.phase = "asked"
                    this.ownedKey = blocked.key
                } else if (navigating !== null) {
                    if (hrefOf(navigating) !== this.requested) return "cancelled"
                    this.phase = "loading"
                    this.ownedKey = navigating.key
                }
                return "pending"
            case "asked":
                if (blocked !== null) return blocked.key === this.ownedKey ? "pending" : "cancelled"
                if (proceeding !== null && proceeding.key === this.ownedKey) {
                    this.phase = "proceeding"
                    this.ownedKey = null
                    return "pending"
                }
                // Idle again with no commit: the question was answered Stay.
                return "cancelled"
            case "proceeding":
                if (blocked !== null) return "cancelled"
                if (navigating !== null) {
                    if (hrefOf(navigating) !== this.requested) return "cancelled"
                    this.phase = "loading"
                    this.ownedKey = navigating.key
                }
                return "pending"
            case "loading":
                if (navigating === null) return "cancelled"
                if (navigating.key === this.ownedKey) return "pending"
                if (isRedirect(navigating)) {
                    this.requested = hrefOf(navigating)
                    this.ownedKey = navigating.key
                    return "pending"
                }
                return "cancelled"
        }
    }
}

type RouterState = DataRouter["state"]

/** The attempt's view of the router's state. */
export function viewOfRouterState(state: RouterState): AttemptView {
    let blocked: AttemptLocation | null = null
    let proceeding: AttemptLocation | null = null
    for (const blocker of state.blockers.values()) {
        if (blocker.state === "blocked") blocked = blocker.location
        else if (blocker.state === "proceeding") proceeding = blocker.location
    }
    return {
        location: state.location,
        action: state.historyAction,
        navigating: state.navigation.state === "idle" ? null : (state.navigation.location ?? null),
        blocked,
        proceeding,
        failed: state.errors !== null && state.errors !== undefined,
    }
}
