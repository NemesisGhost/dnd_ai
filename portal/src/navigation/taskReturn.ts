import { useLocation } from "react-router"
import type { CrumbState } from "./breadcrumbModel"
import { adaptLegacyReturn } from "./legacyReturn"
import { isValidListSearch } from "./listState"
import { executionScopeOf, matchRouteMeta } from "./routeMeta"
import type { NavRoot, RouteMatch } from "./routeMeta"
import { parseTask, validateCarriedTask, validateTask } from "./taskOrigin"
import type { TaskOriginV1 } from "./taskOrigin"

// The task an entry carries, read for the pages that only pass an origin through or ask it where a list
// was left (docs/UI_DESIGN.md §4.8). Unlike `resolveTask` it is NOT judged against this page's allowed
// roots: an edit page that does not accept a Review task still has to hand it back to the record it
// came from, which does. Nothing here grants anything. The task is parsed structurally (unknown keys
// dropped, the trail bounded), must name this page's own campaign, and every list state read from it is
// checked against that list's contract; the page it is handed to validates it again for its own route.
// The older router-state keys are read only through the same adapter that resolution uses, so an entry
// written before the task existed still carries its origin.

function campaignOf(pathname: string): string | null {
    const match = matchRouteMeta(pathname)
    if (match === null) return null
    const scope = executionScopeOf(match)
    return scope.kind === "campaign" ? scope.campaignId : null
}

// The route a link goes to, for the task to be judged against: the address without its query or fragment.
function destinationMatch(destination: string | undefined): RouteMatch | null | undefined {
    if (destination === undefined) return undefined
    return matchRouteMeta(destination.split(/[?#]/)[0] ?? "")
}

function carriedTask(pathname: string, state: unknown, destination?: string): TaskOriginV1 | null {
    const campaignId = campaignOf(pathname)
    if (campaignId === null) return null
    const match = matchRouteMeta(pathname)
    if (match === null) return null
    const target = destinationMatch(destination)
    // Two separate questions. This page: is the task one it may hand on (scope, trail, list contract;
    // not this page's allowed roots, since it only passes the task through). The destination, when the
    // caller knows it: would the page it leads to accept the task, by the same validator it will use. A
    // candidate that fails either is passed over, so it cannot hide a usable fallback.
    const acceptable = (candidate: TaskOriginV1 | null | undefined): TaskOriginV1 | null => {
        if (candidate === null || candidate === undefined) return null
        const passed = validateCarriedTask(candidate, match)
        if (passed === null) return null
        if (target === undefined) return passed
        return target !== null && validateTask(passed, target) !== null ? passed : null
    }
    // Same precedence as `resolveTask`: the entry's own task if it holds up, otherwise the legacy adapter.
    const own = acceptable(parseTask(state))
    return own ?? acceptable(adaptLegacyReturn(match, state)?.task)
}

/**
 * The task to hand to a link out of a page that does not itself adopt it: the entry's task, without its
 * one-shot `transition` hint. Undefined after a direct entry and wherever the entry carries no task.
 * Pass the address the link leads to as `destination` where it is known: the task chosen is then the
 * first candidate (the entry's own, else the adapted legacy origin) that the destination also accepts.
 */
export function carriedState(pathname: string, state: unknown, destination?: string): CrumbState | undefined {
    const task = carriedTask(pathname, state, destination)
    if (task === null) return undefined
    const kept: TaskOriginV1 = {
        v: 1,
        root: task.root,
        scope: { ...task.scope },
        trail: task.trail.map((entry) => ({ ...entry, params: { ...entry.params } })),
    }
    if (task.list !== undefined) kept.list = { ...task.list }
    return { task: kept }
}

/**
 * The query a list was left on, when the entry's task has that root and list and the list's contract
 * accepts the query; undefined otherwise (a direct entry, another root, a rejected query).
 */
export function carriedListSearch(pathname: string, state: unknown, root: NavRoot, listRoute: string): string | undefined {
    const task = carriedTask(pathname, state)
    if (task === null || task.root !== root || task.list === undefined || task.list.route !== listRoute) return undefined
    return isValidListSearch(listRoute, task.list.search) ? task.list.search : undefined
}

export function useCarriedState(): CrumbState | undefined {
    const { pathname, state } = useLocation()
    return carriedState(pathname, state)
}

export function useCarriedListSearch(root: NavRoot, listRoute: string): string | undefined {
    const { pathname, state } = useLocation()
    return carriedListSearch(pathname, state, root, listRoute)
}
