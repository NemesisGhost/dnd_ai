import { pickWorldReturnState } from "../../hooks/useWorldBackPath"
import type { EditNavigation } from "../authoring/ContentEditPage"
import { worldRecordPath } from "./worldPaths"

// Where an edit page's links lead for a World record. The workspace page it was opened from is
// named by `returnTo` in the router state, and only an address of this very record is honoured, so
// a crafted state cannot send the person anywhere else. Anything else returns to the record's
// World page. The World browser's and the Review queue's return state is carried along, so the
// workspace can still lead back to where the person started.
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
        state,
        params = {},
    }: {
        campaignId: string
        entityId: string
        state: unknown
        params?: Record<string, string | undefined>
    }): EditNavigation => {
        const carried = pickWorldReturnState(state)
        const own = worldRecordPath(campaignId, category, entityId)
        const requested = (state as { returnTo?: { pathname?: unknown; search?: unknown } } | null | undefined)?.returnTo
        const pathname = typeof requested?.pathname === "string" ? requested.pathname : null
        const search = typeof requested?.search === "string" && requested.search.startsWith("?") ? requested.search : ""
        return {
            listPath: `/app/${encodeURIComponent(campaignId)}/world${carried?.worldSearch ?? ""}`,
            detail: {
                to:
                    pathname !== null && (pathname === own || (alsoReturnTo?.({ campaignId, params }) ?? []).includes(pathname))
                        ? `${pathname}${search}`
                        : own,
                state: carried,
            },
        }
    }
}
