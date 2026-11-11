import { resolveWithoutTask } from "./legacyReturn"
import type { ResolvedTask } from "./legacyReturn"
import { matchRouteMeta } from "./routeMeta"
import { parseTask, validateTask } from "./taskOrigin"

export type { ResolvedTask } from "./legacyReturn"

/**
 * Origin resolution for the page at `pathname` with history-entry state `state` (docs/UI_DESIGN.md §4.8):
 *   1. a valid `state.task` for this route and scope;
 *   2. otherwise a legacy return key, adapted;
 *   3. otherwise the route's default root and default ancestors.
 * Pure and total over any input: tampered state falls through to the next step. Returns null only for a
 * route that is not a task page. Evaluating it grants nothing and writes nothing.
 */
/**
 * Whether a resolution is evidence of where the person came from: the entry's own valid task, or a legacy
 * key that adapted into one (worldSearch, reviewSearch, a characters return...). A lone `returnTo` is the
 * page's own Back address, resolved onto the route's default task with a `backTarget`; it names no task,
 * so it is no evidence, exactly like a direct entry.
 */
export function hasTaskEvidence(resolved: ResolvedTask | null): resolved is ResolvedTask {
    if (resolved === null || resolved.source === "default") return false
    return !(resolved.source === "legacy" && resolved.backTarget !== undefined)
}

export function resolveTask(pathname: string, state: unknown): ResolvedTask | null {
    const match = matchRouteMeta(pathname)
    if (match === null) return null
    const parsed = parseTask(state)
    const own = parsed === null ? null : validateTask(parsed, match)
    if (own !== null) return { source: "state", task: own }
    return resolveWithoutTask(match, state)
}
