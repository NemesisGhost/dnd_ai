import { useEffect, useMemo, useRef } from "react"
import type { ReactNode } from "react"
import { useLocation, useMatch } from "react-router"
import { worldPath } from "../api/worlds"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { WorldDetail } from "../types/worldAuthoring"
import { useSession } from "./SessionContext"
import { WorkspaceHierarchyContext } from "./WorkspaceHierarchyContext"
import type { WorkspaceHierarchy } from "./WorkspaceHierarchyContext"

// Static route segments that share a position with an ID.
const RESERVED_SEGMENTS = new Set(["new"])

function routeId(value: string | undefined): string | null {
    return value === undefined || RESERVED_SEGMENTS.has(value) ? null : value
}

// Derives the selected world and timeline from the active route, confirming
// them against the server: a world route is trusted only once GET /worlds/{id}
// succeeds, a timeline only if it is in that world's authorized timelines, and
// a campaign route only if the campaign is in the session bootstrap. It makes
// no request unless the session is authenticated and the route names a world.
// Everything is route-derived — no selection is stored anywhere.
export function WorkspaceHierarchyProvider({ children }: { children: ReactNode }) {
    const { state } = useSession()
    const location = useLocation()
    const worldMatch = useMatch("/worlds/:worldId/*")
    const timelineMatch = useMatch("/worlds/:worldId/timelines/:timelineId/*")
    const campaignMatch = useMatch("/app/:campaignId/*")

    const bootstrap = state.status === "authenticated" ? state.bootstrap : null
    const routeWorldId = routeId(worldMatch?.params.worldId)
    const routeTimelineId = routeId(timelineMatch?.params.timelineId)
    const routeCampaign =
        bootstrap?.campaigns.find(
            (campaign) => campaign.campaign_id === campaignMatch?.params.campaignId,
        ) ?? null

    // A world route wins; otherwise the authorized route campaign's world.
    const requestedWorldId =
        bootstrap === null
            ? null
            : worldMatch !== null
                ? routeWorldId
                : (routeCampaign?.world_id ?? null)

    const { state: worldState, refetch } = useAuthoringResource<WorldDetail>(
        requestedWorldId === null ? null : worldPath(requestedWorldId),
    )

    // Timeline options change when a page writes (for example creating a
    // timeline). Refresh them when navigation moves to another route within the
    // same world; a first load or a world change is already fetched by the path.
    const pathname = location.pathname
    const previous = useRef<{ pathname: string; worldId: string | null }>({
        pathname,
        worldId: requestedWorldId,
    })
    useEffect(() => {
        const last = previous.current
        previous.current = { pathname, worldId: requestedWorldId }
        if (
            requestedWorldId !== null &&
            last.worldId === requestedWorldId &&
            last.pathname !== pathname
        ) {
            void refetch()
        }
    }, [pathname, requestedWorldId, refetch])

    const value = useMemo<WorkspaceHierarchy>(() => {
        const campaignRoute = worldMatch === null && routeCampaign !== null
        const worldReady = worldState.kind === "ready"

        let activeWorldId: string | null = null
        let activeTimelineId: string | null = null
        if (campaignRoute) {
            // Authorized by the bootstrap itself; no wait for the world read.
            activeWorldId = routeCampaign.world_id
            activeTimelineId = routeCampaign.timeline_id
        } else if (worldReady && requestedWorldId !== null) {
            activeWorldId = requestedWorldId
            activeTimelineId =
                routeTimelineId !== null &&
                worldState.data.timelines.some(
                    (timeline) => timeline.timeline_id === routeTimelineId,
                )
                    ? routeTimelineId
                    : null
        }

        return {
            activeWorldId,
            activeTimelineId,
            world: requestedWorldId === null ? null : worldState,
            refetchWorld: refetch,
        }
    }, [worldMatch, routeCampaign, worldState, requestedWorldId, routeTimelineId, refetch])

    return (
        <WorkspaceHierarchyContext.Provider value={value}>
            {children}
        </WorkspaceHierarchyContext.Provider>
    )
}
