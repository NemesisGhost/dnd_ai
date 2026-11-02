import { useEffect, useSyncExternalStore } from "react"
import { NavigationType } from "react-router"
import type { Location } from "react-router"

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

// The character perspective the campaign workspace is committed to, readable synchronously by both
// blockers. A perspective change is a context transition: it keeps the pathname, so the departure
// guard has to compare the perspective an entry runs under with the committed one (UI_DESIGN §5.11).
// Written only by the campaign layout (after a navigation is accepted, or when authorization changes
// what is selected); null outside a campaign workspace, where there is no perspective to compare.
export interface CommittedPerspective {
    characterId: string | null
    // What an entry with no valid stamp resolves to when it is returned to by Back/Forward.
    defaultCharacterId: string | null
    // Perspectives the bootstrap authorizes: a stamp naming any other is treated as no stamp.
    authorized: ReadonlySet<string>
}
let committedPerspective: CommittedPerspective | null = null

export function setCommittedPerspective(next: CommittedPerspective | null): void {
    committedPerspective = next
}

// The perspective an entry's `state.ctx` records: `undefined` when the entry carries no valid stamp
// (direct entry, an older entry, tampered state). Shape and version only, plus authorization when known.
export function readEntryPerspective(state: unknown, authorized?: ReadonlySet<string>): string | null | undefined {
    if (typeof state !== "object" || state === null) return undefined
    const ctx = (state as { ctx?: unknown }).ctx
    if (typeof ctx !== "object" || ctx === null) return undefined
    const { v, characterId } = ctx as { v?: unknown; characterId?: unknown }
    if (v !== 1) return undefined
    if (characterId === null) return null
    if (typeof characterId !== "string") return undefined
    return authorized !== undefined && !authorized.has(characterId) ? undefined : characterId
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

// Whether a transition needs the departure guard's question (when the page is dirty or a hold is
// active): a pathname change, or a change of committed perspective at the same path. The comparison is
// of recorded context, never of a transient marker, so Back/Forward between same-path entries is
// guarded long after the transition that created them. A PUSH or REPLACE with no stamp (an ordinary
// link, a query-only change, the stamping replace itself) keeps the committed perspective; only a
// Back/Forward to an unstamped entry resolves to the default.
export function isGuardedTransition(args: {
    currentLocation: Location
    nextLocation: Location
    historyAction: NavigationType
}): boolean {
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
    if (committedPerspective === null) return false
    const stamped = readEntryPerspective(nextLocation.state, committedPerspective.authorized)
    if (stamped === undefined && historyAction !== "POP") return false
    const effective = stamped === undefined ? committedPerspective.defaultCharacterId : stamped
    return effective !== committedPerspective.characterId
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
