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
export function resolveTask(pathname: string, state: unknown): ResolvedTask | null {
    const match = matchRouteMeta(pathname)
    if (match === null) return null
    const parsed = parseTask(state)
    const own = parsed === null ? null : validateTask(parsed, match)
    if (own !== null) return { source: "state", task: own }
    return resolveWithoutTask(match, state)
}
