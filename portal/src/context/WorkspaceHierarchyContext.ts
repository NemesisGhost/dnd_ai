import { createContext, useContext } from "react"
import type { AuthoringResourceState } from "../hooks/useAuthoringResource"
import type { WorldDetail } from "../types/worldAuthoring"

// The World → Timeline selection the active route establishes, resolved from
// server-authoritative data only. Shared by the sidebar and the hierarchy
// context panel so both read one set of requests.
export interface WorkspaceHierarchy {
    // The world the route (or the route's authorized campaign) selects, or null
    // while an unverified, unauthorized, or absent world is in the URL. Never a
    // raw route ID that the server has not confirmed.
    activeWorldId: string | null
    // The timeline the route selects, confirmed against the world's
    // authorized timelines (or the authorized route campaign's timeline).
    activeTimelineId: string | null
    // The world / timeline World-authoring navigation may link to: set only
    // after GET /worlds/{id} succeeds (and, for the timeline, lists it). A
    // campaign's bootstrap membership never confers World authority (ADR 0014),
    // so on a campaign route these stay null until the world read confirms.
    authoringWorldId: string | null
    authoringTimelineId: string | null
    // GET /worlds/{id} for the route's world, keyed by that path so a previous
    // world's response is never shown for the next one. `null` when the route
    // names no world.
    world: AuthoringResourceState<WorldDetail> | null
    // Re-reads the world after a write that changes its timelines.
    refetchWorld: () => Promise<void>
}

export const WorkspaceHierarchyContext = createContext<WorkspaceHierarchy | undefined>(
    undefined,
)

export function useWorkspaceHierarchy(): WorkspaceHierarchy {
    const value = useContext(WorkspaceHierarchyContext)
    if (value === undefined) {
        throw new Error("useWorkspaceHierarchy must be used inside WorkspaceHierarchyProvider")
    }
    return value
}
