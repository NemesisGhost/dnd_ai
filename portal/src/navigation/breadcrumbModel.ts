import { generatePath } from "react-router"
import { defaultAncestors, matchRouteMeta, patternParams, routeMetaById } from "./routeMeta"
import { isIdShaped } from "./contexts"
import type { NavRoot, RouteMatch, RouteRef } from "./routeMeta"
import { isValidListSearch } from "./listState"
import { hasTaskEvidence, resolveTask } from "./resolveTask"
import { continueTask, isSafeSearch, validateTask } from "./taskOrigin"
import type { TaskOriginV1, TrailEntry } from "./taskOrigin"

// The breadcrumb for a page, as data (docs/UI_DESIGN.md §4.8). It follows the VALIDATED task origin of
// the history entry (`resolveTask`: the entry's own task, else an adapted legacy key, else the route's
// defaults), never a guess from containment. It holds route references and generic nouns only: names
// come from the label registry at render time and never enter a link's state.

// Where a task root's own page is, and what the person calls it. Campaign-scoped tasks only; a World
// task over an unscoped world has the Worlds list as its root.
const CAMPAIGN_ROOT: Readonly<Record<NavRoot, { route: string; label: string }>> = {
    campaign: { route: "campaign.home", label: "Campaign Home" },
    world: { route: "campaign.world", label: "World" },
    characters: { route: "characters.browse", label: "Characters" },
    parties: { route: "parties.list", label: "Parties" },
    quests: { route: "quests.list", label: "Quests" },
    sessions: { route: "sessions.list", label: "Sessions" },
    knowledge: { route: "knowledge.list", label: "Knowledge" },
    items: { route: "items.list", label: "Items" },
    review: { route: "review.queue", label: "Review queue" },
    access: { route: "access.overview", label: "Access" },
}

export interface CrumbState {
    task: TaskOriginV1
    // Legacy return keys that readers not yet migrated still use (dual writing, see legacyKeys).
    charactersReturn?: string
    worldSearch?: string
    reviewSearch?: string
    itemsSearch?: string
    definitionsSearch?: string
}

export interface Crumb {
    ref: RouteRef
    // A generic noun from route metadata; the renderer replaces it with a registered name if one exists.
    generic: string
    // Whether a registered name may replace the generic noun (an entity page, not a list or a section).
    named: boolean
    to: string
    state: CrumbState
}

export interface BreadcrumbModel {
    ancestors: Crumb[]
    current: { ref: RouteRef; generic: string }
    source: "state" | "legacy" | "default" | "none"
}

function pathFor(ref: RouteRef): string | null {
    const meta = routeMetaById(ref.route)
    if (meta === undefined) return null
    try {
        return generatePath(meta.pattern, ref.params)
    } catch {
        return null
    }
}

/**
 * The older router-state keys that equal a task's list state, for destinations that have not migrated.
 * Written beside `task` while a family is migrating; removed with the last reader of each key.
 */
export function legacyKeys(task: TaskOriginV1): Omit<CrumbState, "task"> {
    const list = task.list
    if (list === undefined) return {}
    const campaignId = "campaignId" in task.scope ? task.scope.campaignId : null
    if (campaignId === null) return {}
    const meta = routeMetaById(list.route)
    if (meta === undefined) return {}
    if (task.root === "characters" && (list.route === "characters.browse" || list.route === "characters.index")) {
        const path = pathFor({ route: list.route, params: { campaignId } })
        return path === null ? {} : { charactersReturn: `${path}${list.search}` }
    }
    if (task.root === "world" && list.route === "campaign.world") return { worldSearch: list.search }
    if (task.root === "review" && list.route === "review.queue") return { reviewSearch: list.search }
    if (task.root === "items" && list.route === "items.list") return { itemsSearch: list.search }
    if (task.root === "items" && list.route === "itemDefinitions.list") return { definitionsSearch: list.search }
    return {}
}

function withState(task: TaskOriginV1): CrumbState {
    return { task, ...legacyKeys(task) }
}

function trailEntryRef(entry: TrailEntry): RouteRef {
    return { route: entry.route, params: entry.params }
}

function sameRef(left: RouteRef, right: RouteRef): boolean {
    const keys = Object.keys(left.params)
    return (
        left.route === right.route &&
        keys.length === Object.keys(right.params).length &&
        keys.every((key) => left.params[key] === right.params[key])
    )
}

// A list that is a page of its own inside a root, not the root's page with filters: the Items root
// is the item inventory, and the item definitions catalog is a different list of the same root.
// It is shown as its own crumb (with its recorded filters) after the root, never in the root's place,
// so item instances and item definitions stay distinct in labels and ancestry.
const DISTINCT_LISTS: ReadonlySet<string> = new Set(["itemDefinitions.list"])

function rootCrumb(task: TaskOriginV1): { ref: RouteRef; label: string } | null {
    if (!("campaignId" in task.scope)) {
        return task.root === "world" ? { ref: { route: "worlds.list", params: {} }, label: "Worlds" } : null
    }
    const root = CAMPAIGN_ROOT[task.root]
    // A recorded list (with its filters) is the root's own page as the person left it; the labels stay
    // the root's noun, not the list route's.
    const route = task.list !== undefined && !DISTINCT_LISTS.has(task.list.route) ? task.list.route : root.route
    return { ref: { route, params: { campaignId: task.scope.campaignId } }, label: root.label }
}

/**
 * The breadcrumb model for a location: the task's root, then its trail, then the current page. Null
 * for a route that is not a task page; the caller then shows the current page alone.
 */
export function breadcrumbModel(pathname: string, state: unknown): BreadcrumbModel | null {
    const match = matchRouteMeta(pathname)
    if (match === null) return null
    const resolved = resolveTask(pathname, state)
    const current = { ref: { route: match.meta.id, params: match.params }, generic: match.meta.label }
    if (resolved === null) return { ancestors: [], current, source: "none" }
    return { ancestors: ancestorsOf(resolved.task, match), current, source: resolved.source }
}

function ancestorsOf(task: TaskOriginV1, match: RouteMatch): Crumb[] {
    const here: RouteRef = { route: match.meta.id, params: match.params }
    const crumbs: Crumb[] = []
    const seen: RouteRef[] = [here]
    const push = (ref: RouteRef, generic: string, named: boolean, upTo: TrailEntry[]) => {
        if (seen.some((other) => sameRef(other, ref))) return
        const to = pathFor(ref)
        if (to === null) return
        seen.push(ref)
        const truncated: TaskOriginV1 = {
            v: 1,
            root: task.root,
            scope: { ...task.scope },
            trail: upTo.map((entry) => ({ ...entry, params: { ...entry.params } })),
        }
        if (task.list !== undefined) truncated.list = { ...task.list }
        const target = ref.route === task.list?.route ? `${to}${task.list.search}` : to
        crumbs.push({ ref, generic, named, to: target, state: withState(truncated) })
    }

    const root = rootCrumb(task)
    if (root !== null) push(root.ref, root.label, false, [])
    if (root !== null && task.list !== undefined && DISTINCT_LISTS.has(task.list.route) && "campaignId" in task.scope) {
        const listMeta = routeMetaById(task.list.route)
        if (listMeta !== undefined) {
            push({ route: task.list.route, params: { campaignId: task.scope.campaignId } }, listMeta.label, false, [])
        }
    }
    task.trail.forEach((entry, index) => {
        const meta = routeMetaById(entry.route)
        if (meta === undefined) return
        // The root's own page is already the first crumb (possibly as a different list route with the
        // recorded filters); it is never shown twice.
        if (root !== null && "campaignId" in task.scope && entry.route === CAMPAIGN_ROOT[task.root].route) return
        push(trailEntryRef(entry), meta.label, meta.kind === "detail", task.trail.slice(0, index))
    })
    return crumbs
}

/**
 * The task state for a link from the current page to a related page within the same task: the same
 * root, list state and scope, with the current page added to the trail. Null when the current page has
 * no task (not a task page). Legacy keys are written beside it.
 */
export function continuedState(pathname: string, state: unknown): CrumbState | null {
    const match = matchRouteMeta(pathname)
    if (match === null) return null
    const resolved = resolveTask(pathname, state)
    if (resolved === null) return null
    const here: RouteRef = { route: match.meta.id, params: match.params }
    return withState(continueTask(resolved.task, here))
}

/**
 * `continuedState` for a link from a LIST page that has declared list state (the item definitions
 * catalog): the task also records the list as it is now (its route and the query it was left on), so
 * the list's crumb on a page opened from it reopens the same filters. The query is recorded only when
 * the list's contract accepts it (listState.ts); otherwise the task carries no list state, exactly
 * as for a list that declares none. Null for a page that is not a list page.
 */
export function continuedListState(pathname: string, state: unknown, search: string): CrumbState | null {
    const match = matchRouteMeta(pathname)
    if (match === null || match.meta.kind !== "list") return null
    const resolved = resolveTask(pathname, state)
    if (resolved === null) return null
    const here: RouteRef = { route: match.meta.id, params: match.params }
    const task = continueTask(resolved.task, here)
    if (isSafeSearch(search) && isValidListSearch(match.meta.id, search)) {
        task.list = { route: match.meta.id, search }
    }
    return withState(task)
}

/**
 * The task state for a link from the current page to `destination`, a page whose declared parent
 * (`parent`) the person has not opened (a list's "Run" link goes to the Run session, whose parent is the
 * session): the current page and then `parent` are added to the trail, so the destination shows its
 * documented hierarchy instead of skipping a level.
 *
 * Nothing is trusted: `destination` must be a known route with exactly its pattern's id-shaped params,
 * `parent` must be one of that destination's declared ancestors (the `parent` chain of its metadata),
 * and the resulting task must pass the same validation a stored task does for the destination (scope,
 * allowed root, every trail entry a known route of that scope that allows the root). Anything else
 * yields null, so no invalid task is ever emitted; the caller's link then carries nothing.
 */
export function continuedStateVia(
    pathname: string,
    state: unknown,
    parent: RouteRef,
    destination: RouteRef,
): CrumbState | null {
    const match = matchRouteMeta(pathname)
    if (match === null) return null
    const destinationMeta = routeMetaById(destination.route)
    if (destinationMeta === undefined) return null
    const names = patternParams(destinationMeta.pattern)
    const keys = Object.keys(destination.params)
    if (
        keys.length !== names.length ||
        !names.every((name) => Object.prototype.hasOwnProperty.call(destination.params, name)) ||
        !keys.every((key) => isIdShaped(destination.params[key]))
    ) {
        return null
    }
    const target: RouteMatch = { meta: destinationMeta, params: { ...destination.params } }
    if (!defaultAncestors(target).some((ancestor) => sameRef(ancestor, parent))) return null
    const resolved = resolveTask(pathname, state)
    if (resolved === null) return null
    const here: RouteRef = { route: match.meta.id, params: match.params }
    const valid = validateTask(continueTask(continueTask(resolved.task, here), parent), target)
    return valid === null ? null : withState(valid)
}

/**
 * The task state for a link that stays on the same record inside the same task (a section of a record,
 * the same record on its other route): the entry's validated task as it is, without the one-shot
 * `transition` hint, plus the legacy keys beside it. Null for a page that is not a task page and after a
 * direct entry, where a link carries nothing and the destination's defaults apply (a link must not turn
 * "no evidence of an origin" into one).
 */
export function retainedState(pathname: string, state: unknown): CrumbState | null {
    const resolved = resolveTask(pathname, state)
    if (!hasTaskEvidence(resolved)) return null
    const task: TaskOriginV1 = {
        v: 1,
        root: resolved.task.root,
        scope: { ...resolved.task.scope },
        trail: resolved.task.trail.map((entry) => ({ ...entry, params: { ...entry.params } })),
    }
    if (resolved.task.list !== undefined) task.list = { ...resolved.task.list }
    return withState(task)
}

/**
 * For a record page opened inside a task whose root is neither World nor the Review queue (Characters,
 * Parties, a session, Quests) and has an origin on evidence: the state that keeps that task for the
 * page's own links, and the nearest ancestor (what "back" means there). Null after a direct entry and
 * inside World's or the Review queue's own tasks, where the page keeps its existing navigation.
 */
export function outsideTaskOf(pathname: string, state: unknown): { state: CrumbState; nearest: Crumb } | null {
    const resolved = resolveTask(pathname, state)
    if (!hasTaskEvidence(resolved)) return null
    if (resolved.task.root === "world" || resolved.task.root === "review") return null
    return taskOf(pathname, state)
}

/**
 * `outsideTaskOf` for any root: a record page opened inside a task on evidence (its own task, or a legacy
 * return key that validates) of ANY root, World's and the Review queue's included, with the state that keeps
 * the task for the page's own links and the nearest ancestor. Null after a direct entry, where the page
 * keeps the link it has always had (a link must not turn "no evidence of an origin" into one).
 */
export function taskOf(pathname: string, state: unknown): { state: CrumbState; nearest: Crumb } | null {
    const resolved = resolveTask(pathname, state)
    if (!hasTaskEvidence(resolved)) return null
    const kept = retainedState(pathname, state)
    const nearest = breadcrumbModel(pathname, state)?.ancestors.at(-1)
    return kept === null || nearest === undefined ? null : { state: kept, nearest }
}

/**
 * Whether an edit page of a World record was opened inside World's own task by a link that carried it:
 * the entry's own validated task, of World's root (the edit routes allow no other). A legacy return key
 * alone (an older entry, a link that only knew where to come back to) and a direct entry keep the page's
 * single back link, because the trail would not contain the record. Containment is never consulted.
 */
export function inWorldTask(pathname: string, state: unknown): boolean {
    const resolved = resolveTask(pathname, state)
    return resolved !== null && resolved.source === "state" && resolved.task.root === "world"
}
