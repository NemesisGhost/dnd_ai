// The control a person activated to ask for a navigation, held only while that request is the one in
// flight (components/useSidebarMenu: useAcceptedNavigation). When the router accepts a selection arrival at
// the address that request named, the arrival takes the control over as the owner of focus at that
// moment, so the destination's heading may take focus from it and from nowhere else: not from some other
// menu link a person happens to have focused. The slot is cleared as soon as the request ends (Stay, a
// supersession, a failure, or acceptance), so nothing is left to act later. A pure in-memory hand-off:
// no name, no state in history.

interface Activation {
    element: HTMLElement
    pathname: string
}

let current: Activation | null = null

/** A navigation request was begun from `element`, for the address `pathname`. A newer one replaces it. */
export function recordActivation(element: HTMLElement, pathname: string): void {
    current = { element, pathname }
}

/** The request made from `element` ended (decided, cancelled, superseded or failed). */
export function releaseActivation(element: HTMLElement): void {
    if (current?.element === element) current = null
}

/** Takes the activated control for an arrival accepted at `pathname`, once; null when none was recorded for it. */
export function claimActivation(pathname: string): HTMLElement | null {
    if (current === null || current.pathname !== pathname) return null
    const { element } = current
    current = null
    return element
}
