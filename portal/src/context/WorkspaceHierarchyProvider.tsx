import { useEffect, useMemo, useRef, useState } from "react"
import type { ReactNode } from "react"
import { useLocation, useMatch } from "react-router"
import { worldPath } from "../api/worlds"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { WorldEvidenceMap, WorldReadEvidence } from "../navigation/contextOptions"
import { selectionOwner } from "../navigation/selectedContextStore"
import type { WorldDetail } from "../types/worldAuthoring"
import { worldAccess } from "../utils/worldAccess"
import { useSession } from "./SessionContext"
import { WorkspaceHierarchyContext } from "./WorkspaceHierarchyContext"
import type { WorkspaceHierarchy } from "./WorkspaceHierarchyContext"

interface EvidenceRecord {
    owner: string | null
    entries: WorldEvidenceMap
}

const NO_EVIDENCE: WorldEvidenceMap = new Map()

// A read replaces what is known about its world only when it STARTED later; an older answer, however late
// it arrives, changes nothing.
function mergeEvidence(
    entries: WorldEvidenceMap,
    worldId: string,
    evidence: WorldReadEvidence,
): WorldEvidenceMap {
    const known = entries.get(worldId)
    if (known !== undefined && known.startedSeq >= evidence.startedSeq) return entries
    return new Map(entries).set(worldId, evidence)
}

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

    // GET /worlds/{id} answers only a caller with `world.view` on that world (a non-disclosing 404
    // otherwise). A campaign route whose bootstrap already lists the caller's world capabilities
    // without it (a campaign-only GM) would only be refused, so the read is not sent; the campaign's
    // own context still comes from the bootstrap. A world route, and a bootstrap with no list,
    // still ask the server.
    const worldReadable =
        worldMatch !== null ||
        routeCampaign?.world_capabilities === undefined ||
        routeCampaign.world_capabilities.includes("world.view")
    const fetchedWorldId = worldReadable ? requestedWorldId : null
    const {
        state: worldState,
        refetch,
        startedSeq: worldStartedSeq,
        startedOwner: worldStartedOwner,
    } = useAuthoringResource<WorldDetail>(fetchedWorldId === null ? null : worldPath(fetchedWorldId))

    // What authoritative world reads have said, per world, so the Infobox can withdraw an explicit World
    // option a newer read refused (UI_DESIGN §4.8.12). Ordered by when each read STARTED, never when it
    // answered; a transient failure, an abort or a read in flight records nothing. It belongs to one user
    // and browser session and is dropped with it; it never writes the selection store.
    const owner = bootstrap === null ? null : selectionOwner(bootstrap)
    const [recorded, setRecorded] = useState<EvidenceRecord>({ owner, entries: NO_EVIDENCE })
    const settledEvidence = ((): { worldId: string; evidence: WorldReadEvidence } | null => {
        if (fetchedWorldId === null || worldStartedSeq === null) return null
        // Bound to the owner the read STARTED under: a result that settled before the owner changed is
        // the previous owner's and is never recorded for this one, however long it stays on screen.
        if (worldStartedOwner !== owner) return null
        if (worldState.kind === "ready") {
            return { worldId: fetchedWorldId, evidence: { verdict: "readable", startedSeq: worldStartedSeq } }
        }
        if (worldState.kind === "unavailable" || worldState.kind === "denied") {
            return { worldId: fetchedWorldId, evidence: { verdict: "refused", startedSeq: worldStartedSeq } }
        }
        return null
    })()
    // Derived while rendering, not in an effect: the read behind the current state counts the moment it
    // settles, with no extra commit and no frame where a stale list entry outlives a newer refusal. The
    // stored record only changes when the evidence does, so the exposed map keeps its identity otherwise.
    let current: EvidenceRecord = recorded.owner === owner ? recorded : { owner, entries: NO_EVIDENCE }
    if (settledEvidence !== null) {
        const merged = mergeEvidence(current.entries, settledEvidence.worldId, settledEvidence.evidence)
        if (merged !== current.entries) current = { owner, entries: merged }
    }
    if (current !== recorded) setRecorded(current)
    const worldEvidence = current.entries

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
            // Structured campaign context from the bootstrap itself.
            activeWorldId = routeCampaign.world_id
            activeTimelineId = routeCampaign.timeline_id
        } else if (worldReady && requestedWorldId !== null) {
            activeWorldId = requestedWorldId
            activeTimelineId = routeTimelineId
        }

        // World-authoring navigation needs the world read to have succeeded.
        const authoringWorldId =
            worldState.kind === "ready" &&
            activeWorldId !== null &&
            activeWorldId === requestedWorldId
                ? activeWorldId
                : null
        const authoringTimelineId =
            worldState.kind === "ready" &&
            authoringWorldId !== null &&
            activeTimelineId !== null &&
            worldState.data.timelines.some(
                (timeline) => timeline.timeline_id === activeTimelineId,
            )
                ? activeTimelineId
                : null
        if (!campaignRoute) {
            activeTimelineId = authoringTimelineId
        }
        const authoringWorldAccess =
            worldState.kind === "ready" && authoringWorldId !== null
                ? worldAccess(worldState.data)
                : null

        return {
            activeWorldId,
            activeTimelineId,
            authoringWorldId,
            authoringTimelineId,
            authoringWorldAccess,
            routeNamesWorld: worldMatch !== null && routeWorldId !== null,
            routeNamesTimeline:
                worldMatch !== null && timelineMatch !== null && routeTimelineId !== null,
            world: fetchedWorldId === null ? null : worldState,
            worldEvidence,
            refetchWorld: refetch,
        }
    }, [
        worldMatch,
        timelineMatch,
        routeWorldId,
        routeCampaign,
        worldState,
        requestedWorldId,
        fetchedWorldId,
        routeTimelineId,
        worldEvidence,
        refetch,
    ])

    return (
        <WorkspaceHierarchyContext.Provider value={value}>
            {children}
        </WorkspaceHierarchyContext.Provider>
    )
}
