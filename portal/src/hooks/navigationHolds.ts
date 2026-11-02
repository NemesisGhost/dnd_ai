import { useEffect, useSyncExternalStore } from "react"

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
