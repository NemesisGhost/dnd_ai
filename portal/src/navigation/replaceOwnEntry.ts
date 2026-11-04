import type { Location, NavigateFunction } from "react-router"
import type { DataRouter } from "react-router"
import { runPermissionLossCleanup } from "../hooks/navigationHolds"
import { markStamp } from "./entryStamp"

// A replacement that belongs to one history entry (the one place stamps and clean-ups are written).
// It runs only while that entry is still the router's current location and nothing is pending or
// waiting on a decision, and is dropped the moment a newer location exists (which stamps itself), so
// it can never overwrite a newer PUSH, REPLACE or POP, or cut across a blocked one. State and the
// rest of the address are carried over from the router's own copy of the entry. It is a same-path,
// same-context REPLACE: no question, no remount, no new entry, no session refresh, scroll kept.
//
// Permission loss is the one case that does not wait for a blocked transition: the page whose
// question that is has just been removed, nothing will say so, and the loss may not wait for an
// answer. Its replacement runs under the narrow exemption in `runPermissionLossCleanup`, which
// covers exactly this entry and this call; the held navigation is cancelled by its owner as it
// goes away, never approved.
//
// The state it hands the router is declared a stamp of the entry it replaces (navigation/entryStamp.ts)
// before the router can see it, so observers tell this write from any other navigation that merely looks
// like it. The declaration is the state object itself: a replacement that is blocked, superseded or
// abandoned leaves nothing behind but an object that is never committed.
//
// Returns what abandons it.
export function replaceOwnEntry({
    router,
    navigate,
    location,
    entryKey,
    next,
    permissionLoss = false,
}: {
    router: DataRouter | null
    navigate: NavigateFunction
    location: Location
    entryKey: string
    next: (current: Location) => { search: string; state: unknown }
    permissionLoss?: boolean
}): (() => void) | undefined {
    if (router === null) {
        const { search, state } = next(location)
        if (typeof state === "object" && state !== null) markStamp(location, state)
        navigate({ pathname: location.pathname, search, hash: location.hash }, { replace: true, state })
        return undefined
    }
    let finished = false
    const finish = () => {
        finished = true
        unsubscribe()
    }
    const attempt = () => {
        if (finished) return
        const current = router.state
        if (current.location.key !== entryKey) {
            finish()
            return
        }
        const waiting =
            current.navigation.state !== "idle" ||
            (!permissionLoss && [...current.blockers.values()].some((blocker) => blocker.state === "blocked"))
        if (waiting) return
        finish()
        const { search, state } = next(current.location)
        if (typeof state === "object" && state !== null) markStamp(current.location, state)
        const apply = () =>
            void router.navigate(
                { pathname: current.location.pathname, search, hash: current.location.hash },
                { replace: true, state, preventScrollReset: true },
            )
        if (permissionLoss) runPermissionLossCleanup(entryKey, apply)
        else apply()
    }
    const unsubscribe = router.subscribe(attempt)
    attempt()
    return finish
}

export function asRecord(state: unknown): Record<string, unknown> {
    return typeof state === "object" && state !== null ? (state as Record<string, unknown>) : {}
}
