import { isIdShaped } from "./contexts"
import { MAX_LIST_SEARCH, isValidListSearch } from "./listState"
import { NAV_ROOTS, defaultAncestors, executionScopeOf, patternParams, routeMetaById } from "./routeMeta"
import type { NavRoot, RouteMatch, RouteRef } from "./routeMeta"

// The task origin: which Navbar section a task started from, and a short chain of related records that
// led to the current page (docs/UI_DESIGN.md §4.8). It lives only in a history entry's `state.task`.
// It is navigation state: it never grants access, a trail entry is never an access hint, and following
// an ancestor the person cannot read gives the server's normal non-disclosing answer.
//
// It holds route ids and id-shaped parameters only. Never labels or names, free text, drafts, URLs,
// capabilities, authorization outcomes or receipts.

/** The longest trail a writer produces; a stored trail longer than this is treated as tampered. */
export const MAX_TRAIL = 4

export type TaskScope = { campaignId: string } | { worldId: string }

export interface TrailEntry {
    route: string
    params: Record<string, string>
    section?: string
}

export interface TaskOriginV1 {
    v: 1
    root: NavRoot
    scope: TaskScope
    trail: TrailEntry[]
    // A list the task came from, with its query, for restoring filters on return. Only list routes with a
    // declared contract (navigation/listState.ts), and only the keys and values that route produces.
    list?: { route: string; search: string }
    // A presentation hint for announcement wording. It is never consulted by any guard.
    transition?: "context"
}

const SECTION_PATTERN = /^[a-z][a-z0-9-]{0,31}$/
// A syntax bound only; the per-route contract (listState.ts) decides what a list route accepts.
const MAX_SEARCH = MAX_LIST_SEARCH

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value)
}

function own(record: Record<string, unknown>, key: string): unknown {
    return Object.prototype.hasOwnProperty.call(record, key) ? record[key] : undefined
}

/** A query string that is safe to carry: starts with `?`, bounded, and free of controls, spaces and fragments. */
export function isSafeSearch(value: unknown): value is string {
    if (typeof value !== "string" || value.length > MAX_SEARCH || !value.startsWith("?")) return false
    for (let index = 0; index < value.length; index++) {
        const code = value.charCodeAt(index)
        if (code <= 0x20 || code === 0x7f) return false
    }
    return !value.includes("#") && !value.includes("\\")
}

function scopeId(scope: TaskScope): string {
    return "campaignId" in scope ? scope.campaignId : scope.worldId
}

function parseScope(value: unknown): TaskScope | null {
    if (!isRecord(value)) return null
    const campaignId = own(value, "campaignId")
    const worldId = own(value, "worldId")
    if (isIdShaped(campaignId) && worldId === undefined) return { campaignId }
    if (isIdShaped(worldId) && campaignId === undefined) return { worldId }
    return null
}

function parseTrailEntry(value: unknown): TrailEntry | null {
    if (!isRecord(value)) return null
    const route = own(value, "route")
    const params = own(value, "params")
    const section = own(value, "section")
    if (typeof route !== "string" || !isRecord(params)) return null
    if (section !== undefined && (typeof section !== "string" || !SECTION_PATTERN.test(section))) return null
    const copy: Record<string, string> = {}
    for (const key of Object.keys(params)) {
        const item = params[key]
        if (!isIdShaped(item)) return null
        copy[key] = item
    }
    return section === undefined ? { route, params: copy } : { route, params: copy, section }
}

/**
 * Reads `state.task`. Shape and version only: it decides whether the value is a well-formed
 * `TaskOriginV1` and returns a fresh copy, but says nothing about whether it fits a route
 * (`validateTask` does that). Unknown keys are dropped; a trail longer than `MAX_TRAIL` is rejected.
 */
export function parseTask(state: unknown): TaskOriginV1 | null {
    if (!isRecord(state)) return null
    const task = own(state, "task")
    if (!isRecord(task) || own(task, "v") !== 1) return null
    const root = own(task, "root")
    if (typeof root !== "string" || !(NAV_ROOTS as readonly string[]).includes(root)) return null
    const scope = parseScope(own(task, "scope"))
    if (scope === null) return null
    const rawTrail = own(task, "trail")
    if (!Array.isArray(rawTrail) || rawTrail.length > MAX_TRAIL) return null
    const trail: TrailEntry[] = []
    for (const item of rawTrail) {
        const entry = parseTrailEntry(item)
        if (entry === null) return null
        trail.push(entry)
    }
    const result: TaskOriginV1 = { v: 1, root: root as NavRoot, scope, trail }
    const list = own(task, "list")
    if (list !== undefined) {
        if (!isRecord(list)) return null
        const route = own(list, "route")
        const search = own(list, "search")
        // Shape only here (a string that is empty or a safe query); which keys and values the route
        // accepts is checked against the route in validateTask.
        if (typeof route !== "string" || (search !== "" && !isSafeSearch(search))) return null
        result.list = { route, search }
    }
    if (own(task, "transition") === "context") result.transition = "context"
    return result
}

// Whether a route reference names a real route of `scope` whose params are exactly its pattern's,
// id-shaped, and carry the task's own scope id.
function refBelongsToScope(ref: RouteRef, scope: TaskScope, root: NavRoot): boolean {
    const meta = routeMetaById(ref.route)
    if (meta === undefined) return false
    // The destination must itself be a place this task root may be in; the task is not forced to equal
    // containment (a Parties task may pass through a character page), only what the metadata supports.
    if (!meta.allowedRoots.includes(root)) return false
    // An unscoped list (the Worlds list) names no id, so it can be an ancestor of a scoped page.
    if (meta.scope === "none") return Object.keys(ref.params).length === 0 && meta.kind === "list"
    if (meta.scope !==("campaignId" in scope ? "campaign" : "world")) return false
    const names = patternParams(meta.pattern)
    const keys = Object.keys(ref.params)
    if (keys.length !== names.length || !names.every((name) => Object.prototype.hasOwnProperty.call(ref.params, name))) {
        return false
    }
    if (!keys.every((key) => isIdShaped(ref.params[key]))) return false
    return ref.params[meta.scope === "campaign" ? "campaignId" : "worldId"] === scopeId(scope)
}

function sameRef(left: RouteRef, right: RouteRef): boolean {
    if (left.route !== right.route) return false
    const keys = Object.keys(left.params)
    return keys.length === Object.keys(right.params).length && keys.every((key) => left.params[key] === right.params[key])
}

/**
 * Whether a parsed task fits the route being shown (resolution step 1). Returns the normalised task
 * (duplicates and the current page removed, newest kept) or null when any rule fails:
 *   - the route has an execution scope, and the task's scope id equals the route's;
 *   - the route's `allowedRoots` contains the task's root;
 *   - every trail entry names a known route in the same scope with exactly that pattern's id params, and
 *     that route allows the task's root;
 *   - `list` names a list route in the same scope that allows the root, and its query is exactly what
 *     that route's list contract produces (navigation/listState.ts). An invalid descriptor rejects the
 *     whole task (never normalized), so the entry falls back to a legacy key, then to the route default.
 */
export function validateTask(task: TaskOriginV1, current: RouteMatch): TaskOriginV1 | null {
    const scope = executionScopeOf(current)
    if (scope.kind === "none") return null
    if (scope.kind === "campaign" ? !("campaignId" in task.scope) || task.scope.campaignId !== scope.campaignId
        : !("worldId" in task.scope) || task.scope.worldId !== scope.worldId) {
        return null
    }
    if (!current.meta.allowedRoots.includes(task.root)) return null
    const here: RouteRef = { route: current.meta.id, params: current.params }
    const trail: TrailEntry[] = []
    for (const entry of task.trail) {
        if (!refBelongsToScope(entry, task.scope, task.root)) return null
        if (sameRef(entry, here) || trail.some((kept) => sameRef(kept, entry))) continue
        trail.push({ ...entry, params: { ...entry.params } })
    }
    const result: TaskOriginV1 = { v: 1, root: task.root, scope: { ...task.scope }, trail: trail.slice(-MAX_TRAIL) }
    if (task.list !== undefined) {
        const listMeta = routeMetaById(task.list.route)
        if (listMeta === undefined || listMeta.kind !== "list" || listMeta.scope === "none") return null
        if (!listMeta.allowedRoots.includes(task.root)) return null
        if (!isValidListSearch(task.list.route, task.list.search)) return null
        if (listMeta.scope !== (scope.kind === "campaign" ? "campaign" : "world")) return null
        result.list = { ...task.list }
    }
    if (task.transition === "context") result.transition = "context"
    return result
}

/** A new task rooted at a Navbar section; no trail and no list state. */
export function startTask(root: NavRoot, scope: TaskScope): TaskOriginV1 {
    return { v: 1, root, scope: { ...scope }, trail: [] }
}

/**
 * The task for a link within the task: same root and list state, with the page being left added to
 * the trail (duplicates collapse, newest `MAX_TRAIL` kept). The `transition` hint is not carried.
 * `section` is the `?section=` the page being left was showing, recorded on its trail entry so a return to
 * that page reopens the same section; a value that is not a section token is not recorded.
 */
export function continueTask(task: TaskOriginV1, leaving: RouteRef, section?: string): TaskOriginV1 {
    const trail = task.trail.filter((entry) => !sameRef(entry, leaving))
    const left: TrailEntry = { route: leaving.route, params: { ...leaving.params } }
    if (section !== undefined && SECTION_PATTERN.test(section)) left.section = section
    trail.push(left)
    const next: TaskOriginV1 = {
        v: 1,
        root: task.root,
        scope: { ...task.scope },
        trail: trail.slice(-MAX_TRAIL).map((entry) => ({ ...entry, params: { ...entry.params } })),
    }
    if (task.list !== undefined) next.list = { ...task.list }
    return next
}

/** The task a page starts with when nothing else names one: its default root and default ancestors. */
export function defaultTask(match: RouteMatch): TaskOriginV1 | null {
    const scope = executionScopeOf(match)
    if (scope.kind === "none" || match.meta.defaultRoot === null) return null
    const task = startTask(match.meta.defaultRoot, scope.kind === "campaign" ? { campaignId: scope.campaignId } : { worldId: scope.worldId })
    task.trail = defaultAncestors(match)
        .slice(-MAX_TRAIL)
        .map((ref) => ({ route: ref.route, params: { ...ref.params } }))
    return task
}
