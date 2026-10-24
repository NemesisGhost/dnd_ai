import { areaAuthoringPath, dungeonAuthoringPath, dungeonOptionsPath } from "../../api/dungeonAuthoring"
import { usePairedRead } from "../../hooks/usePairedRead"
import type { PairedRead } from "../../hooks/usePairedRead"
import type { AreaAuthoringView, DungeonAuthoringView, DungeonOptions } from "../../types/dungeonAuthoring"

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
