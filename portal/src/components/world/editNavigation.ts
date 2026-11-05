import { resolveReturnTo } from "../../hooks/returnState"
import { pickWorldReturnState } from "../../hooks/useWorldBackPath"
import { breadcrumbModel, inWorldTask } from "../../navigation/breadcrumbModel"
import type { EditNavigation } from "../authoring/ContentEditPage"
import { worldRecordPath } from "./worldPaths"

// Where an edit page's links lead for a World record. The workspace page it was opened from is
// named by `returnTo` in the router state, and only an address of this very record is honoured, so
// a crafted state cannot send the person anywhere else. Anything else returns to the record's
// World page. The World browser's and the Review queue's return state is carried along, so the
// workspace can still lead back to where the person started.
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
        const carried = pickWorldReturnState(state)
        const own = worldRecordPath(campaignId, category, entityId)
        const recordCrumb =
            pathname !== undefined && inWorldTask(pathname, state)
                ? breadcrumbModel(pathname, state)?.ancestors.find(
                      (crumb) => crumb.ref.route === "world.record" && crumb.ref.params.entityId === entityId,
                  )
                : undefined
        return {
            listPath: `/app/${encodeURIComponent(campaignId)}/world${carried?.worldSearch ?? ""}`,
            detail: {
                to: resolveReturnTo(state, [own, ...(alsoReturnTo?.({ campaignId, params }) ?? [])], own),
                state: recordCrumb === undefined ? carried : { ...carried, ...recordCrumb.state },
            },
        }
    }
}
