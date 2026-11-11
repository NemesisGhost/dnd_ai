// The control a navigation was requested with, handed from the request that was accepted to the arrival
// it produced (docs/UI_DESIGN.md §4.8.4). The sidebar menu's request is a `NavigationAttempt` (P02-4:
// navigation/navigationAttempt.ts) that already decides, from the router's own notifications, which
// committed location is *its* arrival: the full destination, through Stay, supersession, redirects and
// failures. When it accepts, it binds its activated control to that location's key. An arrival reads the
// binding by the key of the location it was accepted at, so:
//   - it is the very request's control, not "an element for this pathname": an unrelated arrival (another
//     control, another query or hash, a later navigation to the same path) has another key and gets none;
//   - a request that was held and answered Stay, cancelled, superseded or failed never accepted, so it
//     never bound anything and there is nothing left to claim later.
// The map is bounded and in memory; nothing is stored in router or history state.

const MAX_BOUND = 4
const bound = new Map<string, HTMLElement>()

/** The attempt that was accepted at the location `locationKey` was made with `element`. */
export function bindActivation(locationKey: string, element: HTMLElement): void {
    bound.set(locationKey, element)
    for (const key of bound.keys()) {
        if (bound.size <= MAX_BOUND) break
        bound.delete(key)
    }
}

/** The control the request accepted at `locationKey` was made with; null when none was. */
export function activationFor(locationKey: string): HTMLElement | null {
    return bound.get(locationKey) ?? null
}

/** The arrival has used (or dropped) it. */
export function releaseActivation(locationKey: string): void {
    bound.delete(locationKey)
}
