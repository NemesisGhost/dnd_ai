import { pickWorldReturnState } from "../../hooks/useWorldBackPath"
import type { EditNavigation } from "../authoring/ContentEditPage"
import { worldRecordPath } from "./worldPaths"

// Where an edit page's links lead for a World record. The workspace page it was opened from is
// named by `returnTo` in the router state, and only an address of this very record is honoured, so
// a crafted state cannot send the person anywhere else. Anything else returns to the record's
// World page. The World browser's and the Review queue's return state is carried along, so the
// workspace can still lead back to where the person started.
export function worldEditNavigation(category: "location" | "organization" | "religion" | "character") {
    return ({ campaignId, entityId, state }: { campaignId: string; entityId: string; state: unknown }): EditNavigation => {
        const carried = pickWorldReturnState(state)
        const own = worldRecordPath(campaignId, category, entityId)
        const requested = (state as { returnTo?: { pathname?: unknown; search?: unknown } } | null | undefined)?.returnTo
        const pathname = typeof requested?.pathname === "string" ? requested.pathname : null
        const search = typeof requested?.search === "string" && requested.search.startsWith("?") ? requested.search : ""
        return {
            listPath: `/app/${encodeURIComponent(campaignId)}/world${carried?.worldSearch ?? ""}`,
            detail: {
                to: pathname === own ? `${pathname}${search}` : own,
                state: carried,
            },
        }
    }
}
