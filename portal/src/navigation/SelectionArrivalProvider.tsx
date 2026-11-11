import { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react"
import type { PropsWithChildren } from "react"
import { NavigationType, UNSAFE_DataRouterContext, useLocation, useNavigationType } from "react-router"
import { useAnnounceOwned } from "../components/authoring/announcer"
import { useSession } from "../context/SessionContext"
import { useWorkspaceHierarchy } from "../context/WorkspaceHierarchyContext"
import type { WorkspaceHierarchy } from "../context/WorkspaceHierarchyContext"
import type { SessionBootstrap } from "../types/bootstrap"
import { LinkArrivalContext, SelectionArrivalContext, notePoppedEntry, notePushedEntry } from "./selectionArrival"
import type { SelectionArrival } from "./selectionArrival"
import { createArrivalTracker } from "./selectionArrivalTracker"
import type { ArrivalTracker } from "./selectionArrivalTracker"
import { contextEligible } from "./selectionEligibility"
import { selectionFor, selectionOwner, useSelectedContextSnapshot, useSelectedContextStore } from "./selectedContextStore"
import type { SelectedContextState } from "./selectedContextStore"

// The one owner of what follows an accepted Infobox selection (docs/UI_DESIGN.md §4.8.4): the polite
// announcement here, the heading focus in the destination (navigation/ArrivalHeadingFocus.tsx), both
// from the same arrival, each at most once. What counts as an arrival (and what ends one) is decided from
// the router's committed locations (navigation/selectionArrivalTracker.ts).
//
// What was announced is withdrawn again when the authority it was worded under is lost (the announcer
// owns the message; withdrawing it never touches a newer one): the person or browser session is replaced
// or gone, or a name it spoke is no longer readable (a revoked character, a world the person can no
// longer read). It is a clear, not a rewrite: nothing private is re-spoken. Only what the live region
// still holds is withdrawn; speech already given cannot be recalled.
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

/** The name the announcement would speak, from what the person may read now; null when not readable. */
function nameFor(
    arrival: SelectionArrival,
    bootstrap: SessionBootstrap,
    hierarchy: WorkspaceHierarchy,
): string | null {
    const { change } = arrival
    switch (change.level) {
        case "campaign":
            return campaignName(bootstrap, change.id as string)
        case "world":
            return worldName(bootstrap, hierarchy, change.id as string)
        case "timeline":
            return timelineName(bootstrap, hierarchy, change.id as string)
        case "character":
            return (
                bootstrap.campaigns
                    .find((campaign) => campaign.campaign_id === change.campaignId)
                    ?.character_perspectives.find((character) => character.character_id === change.id)?.character_name ?? null
            )
    }
}

/**
 * What to announce, or null while the arrival is not eligible (the chosen selection is not yet the
 * committed one, or does not fit the destination's route scope: navigation/selectionEligibility.ts).
 */
function messageFor(
    arrival: SelectionArrival,
    selection: SelectedContextState,
    bootstrap: SessionBootstrap,
    hierarchy: WorkspaceHierarchy,
): string | null {
    if (!contextEligible(arrival, selection, bootstrap)) return null
    const { change } = arrival
    const name = nameFor(arrival, bootstrap, hierarchy)
    const clearedCampaign = arrival.campaignBefore !== null && selection.campaignId === null ? ` ${CLEARED}` : ""
    switch (change.level) {
        case "campaign":
            return name === null ? "Campaign changed." : `Campaign changed to ${name}.`
        case "world":
            return `${name === null ? "World changed." : `World changed to ${name}.`}${clearedCampaign}`
        case "timeline":
            return `${name === null ? "Timeline changed." : `Timeline changed to ${name}.`}${clearedCampaign}`
        case "character":
            if (change.id === null) return "No character perspective selected."
            return name === null ? "Character perspective changed." : `Viewing as ${name}.`
    }
}

const NO_ARRIVALS: ArrivalTracker = { getSnapshot: () => null, subscribe: () => () => undefined }

// What is currently in the live region on this owner's behalf.
interface Announced {
    withdraw: () => void
    // The name it spoke (null when the wording was generic: nothing private to withdraw).
    name: string | null
    // The same lookup, made again against what the person may read now.
    nameNow: (bootstrap: SessionBootstrap, hierarchy: WorkspaceHierarchy) => string | null
    // The authority generation it was made under.
    generation: number
}

export function SelectionArrivalProvider({ children }: PropsWithChildren) {
    const router = useContext(UNSAFE_DataRouterContext)?.router ?? null
    const store = useSelectedContextStore()
    const { key: locationKey, state: locationState } = useLocation()
    const navigationType = useNavigationType()
    // Layout effects run before any destination's effect, so a page that settles in the same commit as the
    // PUSH already finds it noted (navigation/selectionArrival.ts, link arrivals).
    useLayoutEffect(() => {
        if (navigationType === NavigationType.Push) notePushedEntry(locationKey)
        else if (navigationType === NavigationType.Pop) notePoppedEntry({ key: locationKey, state: locationState })
    }, [locationKey, locationState, navigationType])
    const announceOwned = useAnnounceOwned()
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
    const owner = bootstrap === null ? null : selectionOwner(bootstrap)

    // The authority generation: a new one whenever the person or browser session behind the bootstrap
    // changes, so an announcement made under an earlier one is never kept, even if the same person or
    // session later returns (A, B, A).
    const authority = useRef<{ owner: string | null; generation: number }>({ owner, generation: 0 })
    const announced = useRef<Announced | null>(null)

    useEffect(() => {
        if (authority.current.owner !== owner) {
            authority.current = { owner, generation: authority.current.generation + 1 }
        }
        const live = announced.current
        if (live !== null) {
            const lost =
                live.generation !== authority.current.generation ||
                bootstrap === null ||
                (live.name !== null && live.name !== live.nameNow(bootstrap, hierarchy))
            if (lost) {
                announced.current = null
                live.withdraw()
            }
        }
        if (arrival === null || bootstrap === null || selection === null) return
        const message = messageFor(arrival, selection, bootstrap, hierarchy)
        if (message !== null && arrival.claimAnnouncement()) {
            announced.current = {
                withdraw: announceOwned(message),
                name: nameFor(arrival, bootstrap, hierarchy),
                nameNow: (nextBootstrap, nextHierarchy) => nameFor(arrival, nextBootstrap, nextHierarchy),
                generation: authority.current.generation,
            }
        }
    }, [announceOwned, arrival, bootstrap, hierarchy, owner, selection])

    // The destination sees the arrival only once it is eligible, the same condition the announcement waits
    // for; a legitimate arrival whose context has not settled yet stays pending (nothing is discarded).
    const eligible = arrival !== null && bootstrap !== null && selection !== null && contextEligible(arrival, selection, bootstrap)
    const current = useMemo(
        () => (arrival === null || !eligible ? null : { arrival, locationKey }),
        [arrival, eligible, locationKey],
    )
    const linkEntry = useMemo(
        () => (arrival === null ? { key: locationKey, state: locationState } : null),
        [arrival, locationKey, locationState],
    )
    return (
        <SelectionArrivalContext.Provider value={current}>
            <LinkArrivalContext.Provider value={linkEntry}>{children}</LinkArrivalContext.Provider>
        </SelectionArrivalContext.Provider>
    )
}
