import {
    areaAuthoringPath,
    areaRuntimePath,
    dungeonAuthoringPath,
    dungeonOptionsPath,
} from "../../api/dungeonAuthoring"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import { useKept } from "../../hooks/useKeptResource"
import { usePairedRead } from "../../hooks/usePairedRead"
import type { PairedRead } from "../../hooks/usePairedRead"
import type {
    AreaAuthoringView,
    AreaRuntimeView,
    DungeonAuthoringView,
    DungeonOptions,
} from "../../types/dungeonAuthoring"

// What the dungeon's Areas and Connections sections share: one read of the dungeon (its areas and
// connections, with the actions the server offers) and the limits and choices its forms need. One
// read means both sections always name the same version.
export type DungeonRead = PairedRead<DungeonAuthoringView, DungeonOptions>

// `enabled` is false for every record that is not a dungeon: nothing is requested.
export function useDungeonRead(campaignId: string, dungeonId: string, enabled: boolean): DungeonRead {
    return usePairedRead(
        enabled ? dungeonAuthoringPath(campaignId, dungeonId) : null,
        enabled ? dungeonOptionsPath(campaignId) : null,
    )
}

// The same for a dungeon area: its contents and current state, shared by Contents and Area now.
export type AreaRead = PairedRead<AreaAuthoringView, DungeonOptions>

export function useAreaRead(campaignId: string, areaId: string, enabled: boolean): AreaRead {
    return usePairedRead(
        enabled ? areaAuthoringPath(campaignId, areaId) : null,
        enabled ? dungeonOptionsPath(campaignId) : null,
    )
}

// The campaign's own read of an area for the "Area now" panel. It is the runtime projection, not
// the authoring view: a campaign GM with no world role uses it, and no private-authoring request
// is made to render the panel. A recoverable failure keeps the last good read on screen; a denied
// or missing answer fails closed and drops it.
export interface AreaRuntimeRead {
    view: AreaRuntimeView | null
    status: "loading" | "ready" | "failed" | "unavailable"
    stale: boolean
    reload: () => Promise<void>
}

export function useAreaRuntimeRead(campaignId: string, areaId: string, enabled: boolean): AreaRuntimeRead {
    const path = enabled ? areaRuntimePath(campaignId, areaId) : null
    const record = useAuthoringResource<AreaRuntimeView>(path)
    const view = useKept(record.state, path ?? "")
    const closed = record.state.kind === "denied" || record.state.kind === "unavailable"
    return {
        view: closed ? null : view,
        status: closed
            ? "unavailable"
            : view !== null
              ? "ready"
              : record.state.kind === "error"
                ? "failed"
                : "loading",
        stale: record.state.kind === "error",
        reload: async () => {
            await record.refetch()
        },
    }
}
