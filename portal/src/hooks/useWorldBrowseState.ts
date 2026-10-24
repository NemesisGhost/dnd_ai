import { useLocation, useSearchParams } from "react-router"
import { parseWorldCategory } from "../utils/worldCategories"
import type { WorldCategory } from "../types/world"

export interface WorldBrowseState {
    category: WorldCategory | null
    query: string
    // The cursors that produced the pages after the first, oldest first. The
    // list API pages forward only, so the whole trail lives in the address:
    // Previous drops the last one, and a deep link or reload keeps it.
    cursors: readonly string[]
    showHidden: boolean
    cursor: string | null
    pageNumber: number
    // The query string (with leading "?", or "") for a changed state.
    hrefFor: (change: Partial<Omit<WorldBrowseState, "cursor" | "pageNumber">>) => string
    // Passed as router state on an entry link so its "Back to World" link can
    // return to this exact view.
    returnSearch: string
    setQuery: (query: string) => void
    setShowHidden: (value: boolean) => void
    goToNextPage: (nextCursor: string) => void
    goToPreviousPage: () => void
}

function buildSearch(state: {
    category: WorldCategory | null
    query: string
    cursors: readonly string[]
    showHidden: boolean
}): string {
    const params = new URLSearchParams()
    if (state.category !== null) params.set("category", state.category)
    if (state.query !== "") params.set("q", state.query)
    if (state.showHidden) params.set("hidden", "1")
    for (const cursor of state.cursors) params.append("cursor", cursor)
    const text = params.toString()
    return text === "" ? "" : `?${text}`
}

// World browsing state (category, search, page trail, draft preview) lives in
// the query string: entries open and return to the same view, and Back/Forward
// and deep links work. A changed category or search always restarts paging,
// because a cursor is only valid for the inputs it was issued for. A search
// keystroke replaces the entry; a category or page change pushes one.
export function useWorldBrowseState(): WorldBrowseState {
    const [params, setParams] = useSearchParams()
    const { search } = useLocation()
    const state = {
        category: parseWorldCategory(params.get("category")),
        query: params.get("q") ?? "",
        cursors: params.getAll("cursor").filter((cursor) => cursor !== ""),
        showHidden: params.get("hidden") === "1",
    }
    const navigateTo = (next: typeof state, replace: boolean) =>
        setParams(new URLSearchParams(buildSearch(next)), { replace })

    return {
        ...state,
        cursor: state.cursors.length > 0 ? state.cursors[state.cursors.length - 1]! : null,
        pageNumber: state.cursors.length + 1,
        hrefFor: (change) => {
            const next = { ...state, ...change }
            // Any change to the inputs a cursor was issued for restarts paging.
            const restarts =
                change.category !== undefined || change.query !== undefined || change.showHidden !== undefined
            return buildSearch(restarts ? { ...next, cursors: change.cursors ?? [] } : next)
        },
        returnSearch: search,
        setQuery: (query) => navigateTo({ ...state, query, cursors: [] }, true),
        setShowHidden: (showHidden) => navigateTo({ ...state, showHidden, cursors: [] }, false),
        goToNextPage: (nextCursor) =>
            navigateTo({ ...state, cursors: [...state.cursors, nextCursor] }, false),
        goToPreviousPage: () => navigateTo({ ...state, cursors: state.cursors.slice(0, -1) }, false),
    }
}
