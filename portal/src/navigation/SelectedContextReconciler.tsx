import { useContext, useLayoutEffect, useRef, useState } from "react"
import { UNSAFE_DataRouterContext, useLocation, useMatch, useNavigate, useNavigationType } from "react-router"
import { worldPath } from "../api/worlds"
import { useSession } from "../context/SessionContext"
import { useWorkspaceHierarchy } from "../context/WorkspaceHierarchyContext"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { WorldDetail } from "../types/worldAuthoring"
import { entryContextStamp, readEntryContext, stampEquals } from "./contexts"
import { restorableSelection, selectionToRecord } from "./entryRestore"
import { asRecord, replaceOwnEntry } from "./replaceOwnEntry"
import { selectionOwner, useSelectedContextSnapshot, useSelectedContextStore } from "./selectedContextStore"

// The owner of the selected context outside the campaign layout (which owns it, and the stamps, on a
// campaign route; the two never act on the same route). One ordered pass per change:
//
//   1. Restore. On a reload or Back/Forward to an entry (and on the first location this shell sees), a
//      versioned stamp is validated against the bootstrap and replaces the selection. A stamp that is
//      absent, older (perspective-only), foreign or tampered restores nothing.
//   2. Reconcile. Sign-out, or a different user or browser session, drops the selection. A selected
//      campaign the *authenticated* session no longer lists is cleared with everything that depended on
//      it (a loading, refreshing or failed session never clears anything). A perspective no longer
//      authorized becomes an explicit none, so neither the server default nor a later re-authorization
//      brings it back. A confirmed World route commits its world (and timeline) and keeps a retained
//      campaign only if it belongs to them.
//      A World-only stamp (a World with no campaign) is a request, not a fact: history ids are not
//      authority and the bootstrap carries no World list to check them against. It is held as pending
//      while the session's own World read (the one a World route uses) confirms it. Until then it
//      governs nothing, nothing is mirrored over the entry's record of it, and no campaign, timeline or
//      perspective is inferred. A readable World is committed with its timeline only if that World lists
//      it; an unreadable one, or any answer that arrives after newer navigation, a newer selection or a
//      change of user or session, is dropped and the entry is repaired to record what the shell holds.
//   3. Mirror. When nothing above changed this pass, the validated selection is recorded on the current
//      entry by a same-entry REPLACE (replaceOwnEntry): no question, no remount, no new entry, no
//      session refresh, scroll kept, unrelated state and the task descriptor carried over, and dropped the
//      moment a newer location exists.
//
// It reads the store fresh, so it never acts on a snapshot an earlier step replaced. The selection is
// ids only, in memory and in each entry's history state; nothing is stored in the browser or a URL.
interface PendingWorld {
    worldId: string
    timelineId: string | null
    // The address the request was made on: newer navigation supersedes it.
    address: string
    owner: string
}

export function SelectedContextReconciler() {
    const { state } = useSession()
    const store = useSelectedContextStore()
    const snapshot = useSelectedContextSnapshot()
    const location = useLocation()
    const navigationType = useNavigationType()
    const navigate = useNavigate()
    const dataRouter = useContext(UNSAFE_DataRouterContext)?.router ?? null
    const campaignMatch = useMatch("/app/:campaignId/*")
    const worldMatch = useMatch("/worlds/:worldId/*")
    const { routeNamesWorld, routeNamesTimeline, activeWorldId, activeTimelineId } = useWorkspaceHierarchy()
    const routeCampaignId = campaignMatch?.params.campaignId ?? null
    const routeWorldId = worldMatch?.params.worldId ?? null
    const address = `${location.pathname}${location.search}`

    // The World a history entry asked for, while the session's own read of it is outstanding.
    const [pending, setPending] = useState<PendingWorld | null>(null)
    const worldRead = useAuthoringResource<WorldDetail>(pending === null ? null : worldPath(pending.worldId))
    const bootstrap = state.status === "authenticated" ? state.bootstrap : null
    const unauthenticated = state.status === "unauthenticated"

    // The location whose stamp was last considered for restoration, and whether this shell has seen one.
    const restoredFor = useRef<string | null>(null)
    const seenFirst = useRef(false)

    useLayoutEffect(() => {
        if (unauthenticated) {
            store.reset()
            return
        }
        if (bootstrap === null) return
        const owner = selectionOwner(bootstrap)
        let current = store.getSnapshot()
        let changed = false
        if (current.owner !== null && current.owner !== owner) {
            store.reset()
            current = store.getSnapshot()
            changed = true
        }
        // A request made on another address, or under another user or session, is superseded.
        if (pending !== null && (pending.address !== address || pending.owner !== owner)) {
            // The request belongs to a state that no longer exists; this is its end, not a derivation.
            // eslint-disable-next-line react-hooks/set-state-in-effect
            setPending(null)
            return undefined
        }

        const onCampaignRoute = routeCampaignId !== null

        // 1. Restore.
        if (restoredFor.current !== location.key) {
            const firstHere = !seenFirst.current
            restoredFor.current = location.key
            seenFirst.current = true
            if (!onCampaignRoute && (navigationType === "POP" || firstHere)) {
                const restored = restorableSelection(location.state, bootstrap)
                if (restored?.kind === "selection") {
                    store.commit(restored.selection)
                    current = store.getSnapshot()
                    changed = true
                } else if (restored?.kind === "world" && restored.worldId !== routeWorldId) {
                    // (A World route confirms its own World; asking again would only repeat that read.)
                     
                    setPending({ worldId: restored.worldId, timelineId: restored.timelineId, address, owner })
                    changed = true
                }
            }
        }

        // 2. Reconcile.
        // An empty selection has no owner yet; the world step below may still commit the route's world.
        if (current.owner === owner || current.owner === null) {
            const campaign =
                current.campaignId === null
                    ? null
                    : (bootstrap.campaigns.find((candidate) => candidate.campaign_id === current.campaignId) ?? null)
            if (current.campaignId !== null && campaign === null) {
                store.commit({ owner, campaignId: null, worldId: null, timelineId: null, characterId: undefined })
                changed = true
            } else if (
                campaign !== null &&
                typeof current.characterId === "string" &&
                current.campaignId !== routeCampaignId &&
                !campaign.character_perspectives.some((character) => character.character_id === current.characterId)
            ) {
                store.commit({ ...current, characterId: null })
                changed = true
            } else if (routeNamesWorld && activeWorldId !== null && !(routeNamesTimeline && activeTimelineId === null)) {
                const keeps =
                    campaign !== null &&
                    campaign.world_id === activeWorldId &&
                    (activeTimelineId === null || campaign.timeline_id === activeTimelineId)
                const next = {
                    owner,
                    campaignId: keeps ? current.campaignId : null,
                    worldId: activeWorldId,
                    timelineId: activeTimelineId,
                    characterId: keeps ? current.characterId : undefined,
                }
                const before = store.getSnapshot()
                store.commit(next)
                if (store.getSnapshot() !== before) changed = true
            }
        }

        // The outstanding World request, once the session has answered it.
        if (pending !== null && !changed) {
            const empty = current.campaignId === null && current.worldId === null
            if (worldRead.state.kind === "loading") return undefined
            if (worldRead.state.kind === "ready" && worldRead.state.data.world_id === pending.worldId && empty && !onCampaignRoute) {
                const timelines = worldRead.state.data.timelines
                store.commit({
                    owner,
                    campaignId: null,
                    worldId: pending.worldId,
                    timelineId: timelines.some((timeline) => timeline.timeline_id === pending.timelineId) ? pending.timelineId : null,
                    characterId: undefined,
                })
            }
            // Confirmed, refused, failed or superseded: the request is over either way.
             
            setPending(null)
            return undefined
        }

        // 3. Mirror. A change above re-runs this pass with the settled selection; an outstanding request
        // leaves the entry's record of it alone.
        if (onCampaignRoute || changed || pending !== null) return undefined
        // The router's own copy of the entry, not the rendered one: a render can lag a replacement that has
        // already landed, and stamping from the stale copy would repeat or contradict it.
        const entryNow = dataRouter?.state.location ?? location
        const recorded = selectionToRecord(store.getSnapshot(), bootstrap)
        if (stampEquals(readEntryContext(entryNow.state), recorded)) return undefined
        return replaceOwnEntry({
            router: dataRouter,
            navigate,
            location: entryNow,
            entryKey: entryNow.key,
            next: (entry) => ({
                search: entry.search,
                state: { ...asRecord(entry.state), ctx: entryContextStamp(recorded) },
            }),
        })
    }, [
        activeTimelineId,
        activeWorldId,
        bootstrap,
        dataRouter,
        location,
        navigate,
        navigationType,
        address,
        pending,
        routeCampaignId,
        routeWorldId,
        worldRead.state,
        routeNamesTimeline,
        routeNamesWorld,
        snapshot,
        store,
        unauthenticated,
    ])

    return null
}
