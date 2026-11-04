import { useLocation } from "react-router"
import { breadcrumbModel, continuedState, continuedStateVia } from "./breadcrumbModel"
import type { RouteRef } from "./routeMeta"
import type { CrumbState } from "./breadcrumbModel"
import { resolveTask } from "./resolveTask"

/**
 * Whether the current history entry carries evidence of where the person came from: its own valid
 * task, or a legacy return key that validates. False after a direct entry, for state that fails
 * validation, and on a page that is not a task page; the route's defaults then apply.
 */
export function useHasTaskOrigin(): boolean {
    const { pathname, state } = useLocation()
    const resolved = resolveTask(pathname, state)
    return resolved !== null && resolved.source !== "default"
}

/**
 * The router state for a link from the current page to a related page inside the same task (list to
 * detail, detail to edit, a member to their record): same root and list state, the current page added
 * to the trail, and the legacy keys beside it while their readers are being migrated. Undefined on a
 * page that is not a task page, where a link simply carries no task.
 *
 * `requireOrigin` is for families that keep their existing fallback after a direct entry: without
 * evidence of an origin the link then carries nothing, exactly as before.
 */
export function useTaskLinkState(options: { requireOrigin?: boolean } = {}): CrumbState | undefined {
    const { pathname, state } = useLocation()
    if (options.requireOrigin === true) {
        const resolved = resolveTask(pathname, state)
        if (resolved === null || resolved.source === "default") return undefined
    }
    return continuedState(pathname, state) ?? undefined
}

/**
 * Like `useTaskLinkState`, for a link to a page whose declared parent (`parent`) the person has not
 * opened: the parent is added to the trail as well, so the destination keeps its documented hierarchy.
 */
export function useTaskLinkStateVia(parent: RouteRef): CrumbState | undefined {
    const { pathname, state } = useLocation()
    return continuedStateVia(pathname, state, parent) ?? undefined
}

/**
 * The link to an ancestor of the current page in its task (a created record's list, a form's Cancel),
 * with the task cut back to that ancestor, or null when the page's trail has no such route. Direct
 * entries give the route's default ancestors, so a destination exists there too.
 */
export function useAncestorLink(route: string): { to: string; state: CrumbState } | null {
    const { pathname, state } = useLocation()
    const crumb = breadcrumbModel(pathname, state)?.ancestors.find((candidate) => candidate.ref.route === route)
    return crumb === undefined ? null : { to: crumb.to, state: crumb.state }
}
