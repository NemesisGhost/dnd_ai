import { useContext, useEffect, useMemo, useState, useSyncExternalStore } from "react"
import type { PropsWithChildren } from "react"
import { UNSAFE_DataRouterContext, useLocation } from "react-router"
import { useAnnounce } from "../components/authoring/announcer"
import { useSession } from "../context/SessionContext"
import { useWorkspaceHierarchy } from "../context/WorkspaceHierarchyContext"
import type { WorkspaceHierarchy } from "../context/WorkspaceHierarchyContext"
import type { SessionBootstrap } from "../types/bootstrap"
import { SelectionArrivalContext } from "./selectionArrival"
import type { SelectionArrival } from "./selectionArrival"
import { createArrivalTracker } from "./selectionArrivalTracker"
import type { ArrivalTracker } from "./selectionArrivalTracker"
import { selectionFor, useSelectedContextSnapshot, useSelectedContextStore } from "./selectedContextStore"
import type { SelectedContextState } from "./selectedContextStore"

// The one owner of what follows an accepted Infobox selection (docs/UI_DESIGN.md §4.8.4): the polite
// announcement here, the heading focus in the destination (navigation/ArrivalHeadingFocus.tsx), both
// from the same arrival, each at most once. What counts as an arrival (and what ends one) is decided from
// the router's committed locations (navigation/selectionArrivalTracker.ts).
//
// The announcement waits for the selection itself to be committed (the store names what was chosen) and
// is worded from what the person may read at that moment: a name that is not readable is left out and the
// wording stays generic. The arrival keeps ids only, so no label outlives the person's access.

function campaignName(bootstrap: SessionBootstrap, campaignId: string): string | null {
    return bootstrap.campaigns.find((campaign) => campaign.campaign_id === campaignId)?.campaign_name ?? null
}

function worldName(bootstrap: SessionBootstrap, hierarchy: WorkspaceHierarchy, worldId: string): string | null {
    const fromCampaign = bootstrap.campaigns.find((campaign) => campaign.world_id === worldId)?.world_name
    if (fromCampaign !== undefined) return fromCampaign
    const read = hierarchy.world
    return read?.kind === "ready" && read.data.world_id === worldId ? read.data.name : null
}

function timelineName(bootstrap: SessionBootstrap, hierarchy: WorkspaceHierarchy, timelineId: string): string | null {
    const fromCampaign = bootstrap.campaigns.find((campaign) => campaign.timeline_id === timelineId)?.timeline_name
    if (fromCampaign !== undefined) return fromCampaign
    const read = hierarchy.world
    return read?.kind === "ready" ? (read.data.timelines.find((timeline) => timeline.timeline_id === timelineId)?.name ?? null) : null
}

const CLEARED = "Campaign selection cleared."

/** What to announce, or null while the chosen selection is not yet committed. */
function messageFor(
    arrival: SelectionArrival,
    selection: SelectedContextState,
    bootstrap: SessionBootstrap,
    hierarchy: WorkspaceHierarchy,
): string | null {
    const { change } = arrival
    const clearedCampaign = arrival.campaignBefore !== null && selection.campaignId === null ? ` ${CLEARED}` : ""
    switch (change.level) {
        case "campaign": {
            if (selection.campaignId !== change.id) return null
            const name = campaignName(bootstrap, change.id as string)
            return name === null ? "Campaign changed." : `Campaign changed to ${name}.`
        }
        case "world": {
            if (selection.worldId !== change.id) return null
            const name = worldName(bootstrap, hierarchy, change.id as string)
            return `${name === null ? "World changed." : `World changed to ${name}.`}${clearedCampaign}`
        }
        case "timeline": {
            if (selection.timelineId !== change.id) return null
            const name = timelineName(bootstrap, hierarchy, change.id as string)
            return `${name === null ? "Timeline changed." : `Timeline changed to ${name}.`}${clearedCampaign}`
        }
        case "character": {
            if (selection.campaignId !== change.campaignId || selection.characterId !== change.id) return null
            if (change.id === null) return "No character perspective selected."
            const name = bootstrap.campaigns
                .find((campaign) => campaign.campaign_id === change.campaignId)
                ?.character_perspectives.find((character) => character.character_id === change.id)?.character_name
            return name === undefined ? "Character perspective changed." : `Viewing as ${name}.`
        }
    }
}

const NO_ARRIVALS: ArrivalTracker = { getSnapshot: () => null, subscribe: () => () => undefined }

export function SelectionArrivalProvider({ children }: PropsWithChildren) {
    const router = useContext(UNSAFE_DataRouterContext)?.router ?? null
    const store = useSelectedContextStore()
    const { key: locationKey } = useLocation()
    const announce = useAnnounce()
    const { state } = useSession()
    const snapshot = useSelectedContextSnapshot()
    const hierarchy = useWorkspaceHierarchy()
    const bootstrap = state.status === "authenticated" ? state.bootstrap : null

    // Without a data router there is no accepted-navigation stream, hence no arrivals.
    const [tracker] = useState(() =>
        router === null ? NO_ARRIVALS : createArrivalTracker(router, () => store.getSnapshot().campaignId),
    )
    const arrival = useSyncExternalStore(tracker.subscribe, tracker.getSnapshot)

    const selection = bootstrap === null ? null : selectionFor(snapshot, bootstrap)
    useEffect(() => {
        if (arrival === null || bootstrap === null || selection === null) return
        const message = messageFor(arrival, selection, bootstrap, hierarchy)
        if (message !== null && arrival.claimAnnouncement()) announce(message)
    }, [announce, arrival, bootstrap, hierarchy, selection])

    const current = useMemo(() => (arrival === null ? null : { arrival, locationKey }), [arrival, locationKey])
    return <SelectionArrivalContext.Provider value={current}>{children}</SelectionArrivalContext.Provider>
}
