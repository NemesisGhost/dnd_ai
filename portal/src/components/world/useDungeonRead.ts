import { useState } from "react"
import { dungeonAuthoringPath, dungeonOptionsPath } from "../../api/dungeonAuthoring"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import type { AuthoringResourceState } from "../../hooks/useAuthoringResource"
import type { DungeonAuthoringView, DungeonOptions } from "../../types/dungeonAuthoring"

// What the dungeon's Areas and Connections sections share: one read of the dungeon (its areas and
// connections, with the actions the server offers) and the limits and choices its forms need. One
// read means both sections always name the same version.
export interface DungeonRead {
    view: DungeonAuthoringView | null
    options: DungeonOptions | null
    // "failed" is a read that did not succeed but may be tried again; "unavailable" is a denied or
    // missing answer, which fails closed.
    status: "loading" | "ready" | "failed" | "unavailable"
    // The latest read failed; `view` is the last one that succeeded, so unsent input survives.
    stale: boolean
    // Reads the dungeon again.
    reload: () => Promise<void>
}

// The last data a read returned, kept through a recoverable failure (a network or server error) and
// dropped on a denied or missing answer.
function useKept<T>(state: AuthoringResourceState<T>): T | null {
    const [kept, setKept] = useState<T | null>(null)
    if (state.kind === "ready" && kept !== state.data) setKept(state.data)
    if ((state.kind === "denied" || state.kind === "unavailable") && kept !== null) setKept(null)
    return state.kind === "ready" ? state.data : state.kind === "error" ? kept : null
}

// `enabled` is false for every record that is not a dungeon: nothing is requested.
export function useDungeonRead(campaignId: string, dungeonId: string, enabled: boolean): DungeonRead {
    const dungeon = useAuthoringResource<DungeonAuthoringView>(enabled ? dungeonAuthoringPath(campaignId, dungeonId) : null)
    const options = useAuthoringResource<DungeonOptions>(enabled ? dungeonOptionsPath(campaignId) : null)
    const view = useKept(dungeon.state)
    const choices = useKept(options.state)
    const closed =
        dungeon.state.kind === "denied" ||
        dungeon.state.kind === "unavailable" ||
        options.state.kind === "denied" ||
        options.state.kind === "unavailable"
    const status: DungeonRead["status"] = closed
        ? "unavailable"
        : view !== null && choices !== null
          ? "ready"
          : dungeon.state.kind === "error" || options.state.kind === "error"
            ? "failed"
            : "loading"
    return {
        view: closed ? null : view,
        options: closed ? null : choices,
        status,
        stale: dungeon.state.kind === "error" || options.state.kind === "error",
        reload: async () => {
            await Promise.all([dungeon.refetch(), options.state.kind === "ready" ? Promise.resolve() : options.refetch()])
        },
    }
}
