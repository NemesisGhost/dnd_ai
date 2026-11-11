import { executionScopeOf, matchRouteMeta } from "./routeMeta"
import type { NavRoot } from "./routeMeta"
import { startTask, validateTask } from "./taskOrigin"
import type { TaskOriginV1 } from "./taskOrigin"

// A Navbar destination starts a task (docs/UI_DESIGN.md §4.8): root = the Navbar item, scope = the
// destination's own execution scope, no trail and no list state. The state rides on the link, so it
// is applied by the router only when the navigation is accepted. A navigation the departure guard
// holds and the person answers Stay to never commits it: the existing entry, its task and its drafts
// are untouched.
//
// Returns undefined where there is nothing valid to start: a destination outside any campaign or
// world (the campaign list, the worlds list), an address that is not a task page, or a root the
// destination does not allow. The page then resolves its origin exactly as after a direct entry.
export function navTaskState(to: string, root: NavRoot): { task: TaskOriginV1 } | undefined {
    const queryAt = to.search(/[?#]/)
    const match = matchRouteMeta(queryAt === -1 ? to : to.slice(0, queryAt))
    if (match === null) return undefined
    const scope = executionScopeOf(match)
    if (scope.kind === "none") return undefined
    const task = validateTask(
        startTask(root, scope.kind === "campaign" ? { campaignId: scope.campaignId } : { worldId: scope.worldId }),
        match,
    )
    return task === null ? undefined : { task }
}
