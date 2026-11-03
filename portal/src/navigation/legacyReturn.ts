import { readCharactersReturn } from "../hooks/useCharactersBackPath"
import { readQueryState } from "../hooks/returnState"
import { isIdShaped } from "./contexts"
import { isValidListSearch } from "./listState"
import { defaultTask, isSafeSearch, validateTask } from "./taskOrigin"
import type { TaskOriginV1 } from "./taskOrigin"
import { executionScopeOf, matchRouteMeta } from "./routeMeta"
import type { RouteMatch } from "./routeMeta"

// Resolution steps 2 and 3 for a history entry with no valid `state.task` (docs/UI_DESIGN.md §4.8).
//
// Until each route family migrates, links still carry the older router-state keys. This adapter reads
// them, validates them with the validators that already guard them, and expresses them as a task, so
// a reader of the new contract sees one shape. It is read-only: nothing here writes state, and a key
// that fails validation is ignored, never repaired.
//
//   charactersReturn -> root characters, with the list (or the character page) it names
//   reviewSearch     -> root review, list = the Review queue
//   itemsSearch      -> root items, list = Items
//   definitionsSearch-> root items, list = Item definitions
//   worldSearch      -> root world, list = the World browser
//   returnTo         -> no task; the page's own Back target only
//
// When several are present the first in that order wins (a record opened from the Review queue carries
// `reviewSearch` and may also carry `worldSearch`; Back goes to the queue). Legacy writers stay until
// their last reader is migrated, so these keys keep working.

export interface LegacyReturn {
    task: TaskOriginV1 | null
    backTarget?: string
}

function campaignScope(match: RouteMatch): string | null {
    const scope = executionScopeOf(match)
    return scope.kind === "campaign" ? scope.campaignId : null
}

function splitAddress(address: string): { pathname: string; search: string } {
    const queryAt = address.indexOf("?")
    return queryAt === -1
        ? { pathname: address, search: "" }
        : { pathname: address.slice(0, queryAt), search: address.slice(queryAt) }
}

function listTask(campaignId: string, root: TaskOriginV1["root"], route: string, search: string): TaskOriginV1 {
    return { v: 1, root, scope: { campaignId }, trail: [], list: { route, search } }
}

function fromCharactersReturn(campaignId: string, state: unknown): TaskOriginV1 | null {
    const address = readCharactersReturn(campaignId, state)
    if (address === undefined) return null
    const { pathname, search } = splitAddress(address)
    const target = matchRouteMeta(pathname)
    if (target === null) return null
    if (target.meta.kind === "list") {
        // Rejected, not normalized: a browse query this route does not produce is not carried at all.
        return isValidListSearch(target.meta.id, search) ? listTask(campaignId, "characters", target.meta.id, search) : null
    }
    return {
        v: 1,
        root: "characters",
        scope: { campaignId },
        trail: [{ route: target.meta.id, params: { ...target.params } }],
    }
}

function fromReturnTo(campaignId: string, state: unknown): string | undefined {
    const requested = (state as { returnTo?: { pathname?: unknown; search?: unknown } } | null | undefined)?.returnTo
    if (typeof requested !== "object" || requested === null) return undefined
    const { pathname, search } = requested
    if (typeof pathname !== "string" || !pathname.startsWith("/") || pathname.startsWith("//")) return undefined
    const target = matchRouteMeta(pathname)
    if (target === null || target.meta.scope !== "campaign" || target.params.campaignId !== campaignId) return undefined
    if (target.meta.kind === "redirect" || target.meta.id === "campaign.notFound") return undefined
    if (pathname !== `/${pathname.split("/").filter(Boolean).join("/")}`) return undefined
    if (!Object.values(target.params).every(isIdShaped)) return undefined
    const query = search === undefined ? "" : isSafeSearch(search) ? search : undefined
    return query === undefined ? undefined : `${pathname}${query}`
}

export function adaptLegacyReturn(match: RouteMatch, state: unknown): LegacyReturn | null {
    const campaignId = campaignScope(match)
    if (campaignId === null) return null

    const characters = fromCharactersReturn(campaignId, state)
    if (characters !== null) return { task: characters }

    const queryKeys: Array<[string, TaskOriginV1["root"], string]> = [
        ["reviewSearch", "review", "review.queue"],
        ["itemsSearch", "items", "items.list"],
        ["definitionsSearch", "items", "itemDefinitions.list"],
        ["worldSearch", "world", "campaign.world"],
    ]
    for (const [key, root, route] of queryKeys) {
        const search = readQueryState(state, key)
        if (search !== undefined && isSafeSearch(search) && isValidListSearch(route, search)) {
            return { task: listTask(campaignId, root, route, search) }
        }
    }

    const backTarget = fromReturnTo(campaignId, state)
    return backTarget === undefined ? null : { task: null, backTarget }
}

export interface ResolvedTask {
    // Where the task came from: this entry's own descriptor (the caller passes it already validated),
    // a legacy router-state key, or the route's defaults.
    source: "state" | "legacy" | "default"
    task: TaskOriginV1
    // A page's own Back target carried by a legacy `returnTo`; it never becomes part of the task.
    backTarget?: string
}

/**
 * Steps 2 and 3 of origin resolution for a page whose own `state.task` did not validate: the legacy
 * adapter, then the route's default root and default ancestors. Returns null only for a route that is
 * not a task page (unscoped, public, a redirect or not-found).
 */
export function resolveWithoutTask(match: RouteMatch, state: unknown): ResolvedTask | null {
    const fallback = defaultTask(match)
    if (fallback === null) return null
    const legacy = adaptLegacyReturn(match, state)
    if (legacy === null) return { source: "default", task: fallback }
    const adapted = legacy.task === null ? null : validateTask(legacy.task, match)
    if (adapted !== null) {
        return legacy.backTarget === undefined
            ? { source: "legacy", task: adapted }
            : { source: "legacy", task: adapted, backTarget: legacy.backTarget }
    }
    return legacy.backTarget === undefined
        ? { source: "default", task: fallback }
        : { source: "legacy", task: fallback, backTarget: legacy.backTarget }
}
