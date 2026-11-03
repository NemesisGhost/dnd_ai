import { useEffect, useSyncExternalStore } from "react"
import { NavigationType } from "react-router"
import type { Location } from "react-router"
import { entryContextWithinScope, readEntryContext } from "../navigation/contexts"
import type { EntryContextRead } from "../navigation/contexts"

// Lets a component that owns state a transition would dispose (a world-time picker's open recording,
// say) take part in the page's one "leave this page?" question. react-router asks only the last
// registered blocker, so a second blocker would either be ignored or hide the page's own.
//
//   - A component with such state calls `useNavigationHold(active)`.
//   - `useUnsavedChangesGuard` (the page-level guard) counts itself here and also blocks while any
//     hold is active, so the page's existing question covers the held state.
//
// Scope: these registries are module-global, which assumes one router per document (as the app has). Two
// routers mounted at once would share holds and guard counts; isolating them is a separate limitation.
// Registration and cleanup are effect-based and balanced, so StrictMode's double mount and several
// holders at once leave the counts exact.
//
//   - When no page-level guard is mounted the holder installs a blocker of its own (`useHostGuard`
//     tells it whether to), so there is still exactly one blocker.

const holds = new Set<symbol>()
let pageGuards = 0
// Page-level guards that are asking "leave this page?" right now.
let questions = 0
const listeners = new Set<() => void>()

function notify() {
    listeners.forEach((listener) => listener())
}
function subscribe(listener: () => void) {
    listeners.add(listener)
    return () => {
        listeners.delete(listener)
    }
}

// For tests: how many holds and page-level guards are registered now.
export function navigationRegistryCounts(): { holds: number; pageGuards: number; questions: number } {
    return { holds: holds.size, pageGuards, questions }
}

export function anyNavigationHold(): boolean {
    return holds.size > 0
}

// Called by `useUnsavedChangesGuard` while it is mounted; returns what undoes it.
export function registerPageGuard(): () => void {
    pageGuards += 1
    notify()
    return () => {
        pageGuards -= 1
        notify()
    }
}

// Called by a page-level guard while its question is on screen; returns what ends it.
export function holdNavigationQuestion(): () => void {
    questions += 1
    notify()
    return () => {
        questions -= 1
        notify()
    }
}

// Whether a page-level guard is asking its question: a modal of a holder should step aside for it.
export function useNavigationQuestion(): boolean {
    return useSyncExternalStore(subscribe, () => questions > 0)
}

// Whether a page-level guard is mounted and so already owns the blocker.
export function useHostGuard(): boolean {
    return useSyncExternalStore(subscribe, () => pageGuards > 0)
}

export function useNavigationHold(active: boolean): void {
    useEffect(() => {
        if (!active) return
        const key = Symbol("navigation-hold")
        holds.add(key)
        return () => {
            holds.delete(key)
        }
    }, [active])
}

// The context the workspace is committed to, readable synchronously by both blockers. A change of
// context is a transition even when the pathname stays, so the departure guard compares what an entry
// records with what is committed (UI_DESIGN §4.8, §5.11).
//
// Today only the campaign layout writes it, and only the perspective: `campaignId`, `worldId` and
// `timelineId` are optional so that an owner which does not yet commit a level is never compared on it
// (`undefined` is "not committed", which is different from `null`, "nothing selected"). Written after a
// navigation is accepted or when authorization changes what is selected; null outside a campaign
// workspace, where there is nothing to compare.
export interface CommittedContext {
    characterId: string | null
    // What an entry with no valid stamp resolves to when it is returned to by Back/Forward.
    defaultCharacterId: string | null
    // Perspectives the bootstrap authorizes: a stamp naming any other is treated as no stamp.
    authorized: ReadonlySet<string>
    campaignId?: string | null
    worldId?: string | null
    timelineId?: string | null
    // The owner's route fixes campaign, world and timeline (a campaign route), so a versioned stamp that
    // names other ones was not made under this scope and counts as no stamp. Leave unset for an owner
    // whose levels are free to differ between entries of one path.
    routeScoped?: boolean
}
// P02-0a's name for the same thing, kept so the perspective-only owner and its tests read unchanged.
export type CommittedPerspective = CommittedContext
let committedContext: CommittedContext | null = null

export function setCommittedContext(next: CommittedContext | null): void {
    committedContext = next
}
export const setCommittedPerspective = setCommittedContext

// The perspective an entry's `state.ctx` records: `undefined` when the entry carries no valid stamp
// (direct entry, an older entry, tampered state), the id or `null` (explicitly none) otherwise. Reads
// the versioned stamp and the P02-0a `{ v: 1, characterId }` stamp alike (see readEntryContext).
export function readEntryPerspective(state: unknown, authorized?: ReadonlySet<string>): string | null | undefined {
    const read = readEntryContext(state, authorized)
    if (read.kind === "absent") return undefined
    return read.kind === "v1" ? read.context.characterId : read.characterId
}

// Permission loss is not a departure the person chose, so it never waits for a decision and the
// disappearing page's dirty state cannot hold it. The exemption is as narrow as it can be: it exists
// only while `run` executes (the navigation it starts is evaluated synchronously, inside it), it covers
// only a REPLACE of the entry named by `entryKey` that keeps its path, and it is gone when `run` returns,
// so no other navigation, before or after, bypasses a guard. It approves nothing that was held: a
// blocked navigation is neither proceeded nor otherwise touched here.
let permissionLossEntry: string | null = null
export function runPermissionLossCleanup(entryKey: string, run: () => void): void {
    permissionLossEntry = entryKey
    try {
        run()
    } finally {
        permissionLossEntry = null
    }
}

// Whether the context an entry would run under differs from the committed one. Levels the stamp does
// not record (the P02-0a stamp records only the perspective) and levels the owner does not commit
// (`undefined`) are not compared.
function entryChangesContext(read: EntryContextRead, committed: CommittedContext, action: NavigationType): boolean {
    if (read.kind === "absent") {
        // A PUSH or REPLACE with no stamp (an ordinary link, a query-only change, the stamping replace
        // itself) keeps the committed context; only Back/Forward to an unstamped entry resolves to the default.
        return action === NavigationType.Pop && committed.defaultCharacterId !== committed.characterId
    }
    const characterId = read.kind === "v1" ? read.context.characterId : read.characterId
    if (characterId !== committed.characterId) return true
    if (read.kind === "legacy-perspective") return false
    const context = read.context
    return (["campaignId", "worldId", "timelineId"] as const).some((key) => {
        const recorded = committed[key]
        return recorded !== undefined && context[key] !== recorded
    })
}

export interface GuardedTransitionOptions {
    // A query-only change (same path, same context) is unguarded unless this says it disposes state: the
    // editor or dialog would unmount, the data scope or perspective changes, or an unresolved operation
    // would lose its owner. No option means never, which is the behavior before it existed (UI_DESIGN §5.11).
    disposingQuery?: (currentLocation: Location, nextLocation: Location) => boolean
}

// Whether a transition needs the departure guard's question (when the page is dirty or a hold is
// active): a pathname change, a change of committed context at the same path, or a query-only change
// the caller declares disposing. The comparison is of recorded context, never of a transient marker, so
// Back/Forward between same-path entries is guarded long after the transition that created them.
export function isGuardedTransition(
    args: {
        currentLocation: Location
        nextLocation: Location
        historyAction: NavigationType
    },
    options?: GuardedTransitionOptions,
): boolean {
    const { currentLocation, nextLocation, historyAction } = args
    // The one exemption: permission loss completing its own cleanup (see runPermissionLossCleanup).
    if (
        permissionLossEntry !== null &&
        currentLocation.key === permissionLossEntry &&
        nextLocation.pathname === currentLocation.pathname &&
        historyAction === NavigationType.Replace
    ) {
        return false
    }
    if (currentLocation.pathname !== nextLocation.pathname) return true
    if (committedContext !== null) {
        // A stamp that names another campaign, world or timeline than the committed scope is no stamp.
        const stamp = readEntryContext(nextLocation.state, committedContext.authorized)
        const read = committedContext.routeScoped
            ? entryContextWithinScope(stamp, {
                  campaignId: committedContext.campaignId,
                  worldId: committedContext.worldId,
                  timelineId: committedContext.timelineId,
              })
            : stamp
        if (entryChangesContext(read, committedContext, historyAction)) return true
    }
    return (
        currentLocation.search !== nextLocation.search &&
        options?.disposingQuery?.(currentLocation, nextLocation) === true
    )
}

// What a holder with its own blocker shows its question from.
export interface GuardView {
    blocked: boolean
    stay: () => void
    discard: () => void
}
export const NO_GUARD_VIEW: GuardView = { blocked: false, stay: () => {}, discard: () => {} }

export interface GuardViewStore {
    subscribe: (listener: () => void) => () => void
    get: () => GuardView
    set: (view: GuardView) => void
}

export function createGuardViewStore(): GuardViewStore {
    let view = NO_GUARD_VIEW
    const own = new Set<() => void>()
    return {
        subscribe(listener) {
            own.add(listener)
            return () => {
                own.delete(listener)
            }
        },
        get: () => view,
        set(next) {
            if (next.blocked === view.blocked && next.stay === view.stay && next.discard === view.discard) return
            view = next
            own.forEach((listener) => listener())
        },
    }
}

export function useGuardView(store: GuardViewStore): GuardView {
    return useSyncExternalStore(store.subscribe, store.get)
}
