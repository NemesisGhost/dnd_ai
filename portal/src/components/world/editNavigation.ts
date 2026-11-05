import { resolveReturnTo } from "../../hooks/returnState"
import { breadcrumbModel, inWorldTask } from "../../navigation/breadcrumbModel"
import { carriedListSearch, carriedState } from "../../navigation/taskReturn"
import type { EditNavigation } from "../authoring/ContentEditPage"
import { worldRecordPath } from "./worldPaths"

// Where an edit page's links lead for a World record. The workspace page it was opened from is
// named by `returnTo` in the router state, and only an address of this very record is honoured, so
// a crafted state cannot send the person anywhere else. Anything else returns to the record's
// World page. The task the page was opened in (the World browser with its filters, the Review queue) is
// carried along even where this route does not accept its root, so the workspace can still lead back to
// where the person started; the record validates it for its own route.
//
// Inside World's own task (the page was opened from a record that was opened from the World browser)
// the record it returns to also keeps that task: the record's crumb in the edit page's breadcrumb,
// which is the task cut back to before the record. Containment is never consulted.
//
// `alsoReturnTo` names other addresses of the same campaign that an edit page may also return to,
// computed from the page's own route (an area returns to its dungeon's Areas list, which the
// address names), so it is never taken from the state.
export function worldEditNavigation(
    category: "location" | "organization" | "religion" | "character",
    alsoReturnTo?: (context: { campaignId: string; params: Record<string, string | undefined> }) => string[],
) {
    return ({
        campaignId,
        entityId,
        pathname,
        state,
        params = {},
    }: {
        campaignId: string
        entityId: string
        pathname?: string
        state: unknown
        params?: Record<string, string | undefined>
    }): EditNavigation => {
        const carried = pathname === undefined ? undefined : carriedState(pathname, state)
        const browserSearch =
            pathname === undefined ? undefined : carriedListSearch(pathname, state, "world", "campaign.world")
        const own = worldRecordPath(campaignId, category, entityId)
        const recordCrumb =
            pathname !== undefined && inWorldTask(pathname, state)
                ? breadcrumbModel(pathname, state)?.ancestors.find(
                      (crumb) => crumb.ref.route === "world.record" && crumb.ref.params.entityId === entityId,
                  )
                : undefined
        return {
            listPath: `/app/${encodeURIComponent(campaignId)}/world${browserSearch ?? ""}`,
            detail: {
                to: resolveReturnTo(state, [own, ...(alsoReturnTo?.({ campaignId, params }) ?? [])], own),
                state: recordCrumb === undefined ? carried : recordCrumb.state,
            },
        }
    }
}
