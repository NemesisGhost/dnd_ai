import { useLocation, useSearchParams } from "react-router"
import type { CharacterType } from "../types/world"

export interface CharactersBrowseState {
    // null means every character type.
    type: CharacterType | null
    query: string
    // The cursors that produced the pages after the first, oldest first (the list API pages
    // forward only), so Previous, a reload and a deep link all keep the page.
    cursors: readonly string[]
    showHidden: boolean
    cursor: string | null
    pageNumber: number
    // The path and query string this view is at, carried as router state on a row link so the
    // sheet's "Back to characters" returns to this exact view.
    returnTo: string
    // The query string (leading "?", or "") for a changed state; changing the type, the search or
    // the draft preview restarts paging, because a cursor is only valid for the inputs it was
    // issued for.
    hrefFor: (change: Partial<Pick<CharactersBrowseState, "type" | "query" | "showHidden">>) => string
    setQuery: (query: string) => void
    setShowHidden: (value: boolean) => void
    goToNextPage: (nextCursor: string) => void
    goToPreviousPage: () => void
}

export function parseCharacterType(value: string | null): CharacterType | null {
    return value === "npc" || value === "player_character" ? value : null
}

interface Inputs {
    type: CharacterType | null
    query: string
    cursors: readonly string[]
    showHidden: boolean
}

function buildSearch(state: Inputs): string {
    const params = new URLSearchParams()
    if (state.type !== null) params.set("type", state.type)
    if (state.query !== "") params.set("q", state.query)
    if (state.showHidden) params.set("hidden", "1")
    for (const cursor of state.cursors) params.append("cursor", cursor)
    const text = params.toString()
    return text === "" ? "" : `?${text}`
}

// The Characters browser's type, search, page trail and draft preview live in the address, the
// way the World browser's do: entries return to the same view, and Back, Forward and deep links
// work. A search keystroke replaces the entry; a type or page change pushes one.
export function useCharactersBrowseState(): CharactersBrowseState {
    const [params, setParams] = useSearchParams()
    const { pathname, search } = useLocation()
    const state: Inputs = {
        type: parseCharacterType(params.get("type")),
        query: params.get("q") ?? "",
        cursors: params.getAll("cursor").filter((cursor) => cursor !== ""),
        showHidden: params.get("hidden") === "1",
    }
    const navigateTo = (next: Inputs, replace: boolean) =>
        setParams(new URLSearchParams(buildSearch(next)), { replace })

    return {
        ...state,
        cursor: state.cursors.length > 0 ? state.cursors[state.cursors.length - 1]! : null,
        pageNumber: state.cursors.length + 1,
        returnTo: `${pathname}${search}`,
        hrefFor: (change) => buildSearch({ ...state, ...change, cursors: [] }) || "?",
        setQuery: (query) => navigateTo({ ...state, query, cursors: [] }, true),
        setShowHidden: (showHidden) => navigateTo({ ...state, showHidden, cursors: [] }, false),
        goToNextPage: (nextCursor) =>
            navigateTo({ ...state, cursors: [...state.cursors, nextCursor] }, false),
        goToPreviousPage: () => navigateTo({ ...state, cursors: state.cursors.slice(0, -1) }, false),
    }
}
