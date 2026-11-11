import { useContext, useLayoutEffect, useRef, useState } from "react"
import { UNSAFE_DataRouterContext, useLocation, useMatch, useNavigate, useNavigationType } from "react-router"
import { fetchWorld } from "../api/worlds"
import { useSession } from "../context/SessionContext"
import { useWorkspaceHierarchy } from "../context/WorkspaceHierarchyContext"
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
//      authority and the bootstrap carries no World list to check them against. Each such restoration is
//      one *attempt* with its own request and its own result (`fetchWorld`, the read a World route uses;
//      never a shared or retained read). An attempt records the history entry it was made for (key and
//      state), the selection revision it was made against, and the user and session; its result is
//      applied only while all of that still holds, judged by one predicate (`owns`). Same address, same
//      World id and an empty selection prove none of it. Until it answers the attempt governs nothing,
//      nothing is mirrored over the entry's record of it, and no campaign, timeline or perspective is
//      inferred. A readable World is committed, with its timeline only if that World lists it; a refused
//      or failed read drops the attempt and, as it still owns the revision, clears a World-only selection
//      of that World (fail closed). Abort assists cleanup but is never the freshness check.
//   3. Mirror. When nothing above changed this pass, the validated selection is recorded on the current
//      entry by a same-entry REPLACE (replaceOwnEntry): no question, no remount, no new entry, no
//      session refresh, scroll kept, unrelated state and the task descriptor carried over, and dropped the
//      moment a newer location exists.
//
// It reads the store fresh, so it never acts on a snapshot an earlier step replaced. The selection is
// ids only, in memory and in each entry's history state; nothing is stored in the browser or a URL.
// One restoration of a World-only stamp: its identity is the object itself.
interface Attempt {
    worldId: string
    timelineId: string | null
    entryKey: string
    entryState: unknown
    revision: number
    owner: string
    controller: AbortController
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

    // The outstanding restoration attempt, if any, and what it is judged against right now.
    const attempt = useRef<Attempt | null>(null)
    const live = useRef<{ mounted: boolean; owner: string | null; location: typeof location }>({
        mounted: false,
        owner: null,
        location,
    })
    // Lets the pass run again once an attempt settles, to mirror what the shell now holds.
    const [settled, setSettled] = useState(0)
    const bootstrap = state.status === "authenticated" ? state.bootstrap : null
    const unauthenticated = state.status === "unauthenticated"

    useLayoutEffect(() => {
        const current = live.current
        current.mounted = true
        return () => {
            current.mounted = false
        }
    }, [])
    useLayoutEffect(() => {
        live.current.owner = bootstrap === null ? null : selectionOwner(bootstrap)
        live.current.location = location
    })

    // Whether `a` may still act: the same history entry (key and state, so a newer entry on the same
    // address, or an unrelated REPLACE, never inherits it), the same selection revision (a deliberate
    // change invalidates it even if the values later return), the same user and session, and a mounted
    // shell. The router's own copy of the entry is used because a render can lag it.
    const owns = (a: Attempt): boolean => {
        const entry = dataRouter?.state.location ?? live.current.location
        return (
            live.current.mounted &&
            entry.key === a.entryKey &&
            entry.state === a.entryState &&
            store.getSnapshot().revision === a.revision &&
            live.current.owner === a.owner
        )
    }

    // The one place an attempt's result is applied.
    const settle = (a: Attempt, data: WorldDetail | null): void => {
        if (attempt.current !== a) return
        attempt.current = null
        if (owns(a)) {
            if (data !== null && data.world_id === a.worldId) {
                store.commit({
                    owner: a.owner,
                    campaignId: null,
                    worldId: a.worldId,
                    timelineId: data.timelines.some((timeline) => timeline.timeline_id === a.timelineId) ? a.timelineId : null,
                    characterId: undefined,
                })
            } else {
                const held = store.getSnapshot()
                if (held.campaignId === null && held.worldId === a.worldId) {
                    store.commit({ owner: a.owner, campaignId: null, worldId: null, timelineId: null, characterId: undefined })
                }
            }
        }
        setSettled((count) => count + 1)
    }

    // The location whose stamp was last considered for restoration, and whether this shell has seen one.
    const restoredFor = useRef<string | null>(null)
    const seenFirst = useRef(false)

    useLayoutEffect(() => {
        // An attempt that no longer owns its entry, revision, user or session is over.
        if (attempt.current !== null && (unauthenticated || !owns(attempt.current))) {
            attempt.current.controller.abort()
            attempt.current = null
        }
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
                    const entryNow = dataRouter?.state.location ?? location
                    attempt.current?.controller.abort()
                    const made: Attempt = {
                        worldId: restored.worldId,
                        timelineId: restored.timelineId,
                        entryKey: entryNow.key,
                        entryState: entryNow.state,
                        revision: store.getSnapshot().revision,
                        owner,
                        controller: new AbortController(),
                    }
                    attempt.current = made
                    fetchWorld(made.worldId, made.controller.signal).then(
                        (data) => settle(made, data),
                        () => settle(made, null),
                    )
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

        // 3. Mirror. A change above re-runs this pass with the settled selection; an outstanding request
        // leaves the entry's record of it alone.
        if (onCampaignRoute || changed || attempt.current !== null) return undefined
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
    // `owns` and `settle` read refs and the store at call time; they are not inputs of the pass.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [
        activeTimelineId,
        activeWorldId,
        bootstrap,
        dataRouter,
        location,
        navigate,
        navigationType,
        routeCampaignId,
        routeWorldId,
        settled,
        routeNamesTimeline,
        routeNamesWorld,
        snapshot,
        store,
        unauthenticated,
    ])

    return null
}
