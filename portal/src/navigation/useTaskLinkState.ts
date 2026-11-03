import { useLocation } from "react-router"
import { continuedState } from "./breadcrumbModel"
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
