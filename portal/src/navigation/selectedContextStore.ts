import { createContext, useContext, useState, useSyncExternalStore } from "react"
import type { SessionBootstrap } from "../types/bootstrap"

// The person's explicit selection in this tab (docs/UI_DESIGN.md §4.8): ids only, in memory only, owned
// above the campaign-scoped session so it survives a campaign-scope change. It is NOT execution scope
// (the route decides what a page reads and writes), NOT the viewed record, and NOT authority: every
// consumer validates it against the current bootstrap before showing it, and every read is authorized
// by the server. Nothing here is written to browser storage, a URL or history; the history mirror is
// the entry stamp (navigation/contexts.ts).

export interface SelectedContextState {
    // The signed-in user and browser session the selection was made under. A different owner reads as
    // an empty selection and is replaced on the next commit.
    owner: string | null
    campaignId: string | null
    worldId: string | null
    timelineId: string | null
    // `undefined`: no perspective has been chosen or initialized for this campaign, so the campaign's
    // server default initializes it. `null`: an explicit choice of no perspective. An id: a choice.
    characterId: string | null | undefined
}

export interface SelectedContextSnapshot extends SelectedContextState {
    // Increases on every change; unchanged commits do not move it.
    revision: number
}

export interface SelectedContextStore {
    getSnapshot: () => SelectedContextSnapshot
    subscribe: (listener: () => void) => () => void
    // Replaces the whole selection. A no-op (no notification) when nothing differs.
    commit: (next: SelectedContextState) => void
    // Drops the whole selection (sign-out, an owner change).
    reset: () => void
}

export const EMPTY_SELECTION: SelectedContextState = {
    owner: null,
    campaignId: null,
    worldId: null,
    timelineId: null,
    characterId: undefined,
}

export function selectionOwner(bootstrap: SessionBootstrap): string {
    return `${bootstrap.user.user_id}\u0000${bootstrap.browser_session_id}`
}

function same(left: SelectedContextState, right: SelectedContextState): boolean {
    return (
        left.owner === right.owner &&
        left.campaignId === right.campaignId &&
        left.worldId === right.worldId &&
        left.timelineId === right.timelineId &&
        left.characterId === right.characterId
    )
}

export function createSelectedContextStore(): SelectedContextStore {
    let snapshot: SelectedContextSnapshot = { ...EMPTY_SELECTION, revision: 0 }
    const listeners = new Set<() => void>()
    const replace = (next: SelectedContextState): void => {
        if (same(snapshot, next)) return
        snapshot = { ...next, revision: snapshot.revision + 1 }
        listeners.forEach((listener) => listener())
    }
    return {
        getSnapshot: () => snapshot,
        subscribe(listener) {
            listeners.add(listener)
            return () => {
                listeners.delete(listener)
            }
        },
        commit: (next) => replace({ ...next }),
        reset: () => replace(EMPTY_SELECTION),
    }
}

export const SelectedContextStoreContext = createContext<SelectedContextStore | null>(null)

/**
 * The store in force. Under `SelectedContextProvider` (main.tsx) it is the tab's one store; a tree
 * without the provider (an isolated test of one component) gets a private store of its own, so no
 * selection can leak between such trees.
 */
export function useSelectedContextStore(): SelectedContextStore {
    const provided = useContext(SelectedContextStoreContext)
    const [local] = useState(() => (provided === null ? createSelectedContextStore() : null))
    return provided ?? local!
}

/** The snapshot, re-rendering the caller on change. Read the owner before trusting any level of it. */
export function useSelectedContextSnapshot(): SelectedContextSnapshot {
    const store = useSelectedContextStore()
    return useSyncExternalStore(store.subscribe, store.getSnapshot)
}

/** The selection as a consumer may use it: empty unless it was made by the current owner. */
export function selectionFor(snapshot: SelectedContextState, bootstrap: SessionBootstrap | null): SelectedContextState {
    return bootstrap !== null && snapshot.owner === selectionOwner(bootstrap) ? snapshot : EMPTY_SELECTION
}
