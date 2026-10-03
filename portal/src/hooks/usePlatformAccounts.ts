import { useCallback, useEffect, useRef, useState } from "react"
import { fetchPlatformAccounts, PlatformAccountsRequestError } from "../api/platformAccounts"
import { useSession } from "../context/SessionContext"
import type { PlatformAccount } from "../types/platformAccounts"

export type PlatformAccountsState =
    | { status: "loading" }
    | { status: "success"; items: PlatformAccount[]; nextCursor: string | null }
    | { status: "denied" }
    | { status: "error"; error: unknown }

export interface UsePlatformAccountsResult {
    state: PlatformAccountsState
    query: string
    setQuery: (query: string) => void
    retry: () => void
    loadMore: () => void
}

interface Snapshot {
    query: string
    requestVersion: number
    cursor: string | null
    state: PlatformAccountsState
}

const initialState: PlatformAccountsState = { status: "loading" }

export function usePlatformAccounts(): UsePlatformAccountsResult {
    const { reload } = useSession()
    const [query, setQueryState] = useState("")
    const [requestVersion, setRequestVersion] = useState(0)
    const [cursor, setCursor] = useState<string | null>(null)
    const [snapshot, setSnapshot] = useState<Snapshot>(() => ({
        query: "",
        requestVersion: 0,
        cursor: null,
        state: initialState,
    }))
    const nextCursorRef = useRef<string | null>(null)

    const state =
        snapshot.query === query &&
        snapshot.requestVersion === requestVersion &&
        snapshot.cursor === cursor
            ? snapshot.state
            : initialState

    const setQuery = useCallback((next: string) => {
        setQueryState(next)
        setCursor(null)
    }, [])

    const retry = useCallback(() => {
        setRequestVersion((current) => current + 1)
    }, [])

    const loadMore = useCallback(() => {
        if (nextCursorRef.current === null) {
            return
        }
        setCursor(nextCursorRef.current)
    }, [])

    useEffect(() => {
        const controller = new AbortController()
        const requestQuery = query
        const requestCursor = cursor

        void fetchPlatformAccounts(
            { q: requestQuery || undefined, cursor: requestCursor || undefined },
            controller.signal,
        )
            .then((result) => {
                if (controller.signal.aborted) {
                    return
                }
                nextCursorRef.current = result.next_cursor
                setSnapshot((current) => ({
                    query: requestQuery,
                    requestVersion,
                    cursor: requestCursor,
                    state: {
                        status: "success",
                        items:
                            requestCursor === null
                                ? result.items
                                : [
                                      ...(current.state.status === "success"
                                          ? current.state.items
                                          : []),
                                      ...result.items,
                                  ],
                        nextCursor: result.next_cursor,
                    },
                }))
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return
                }
                if (error instanceof DOMException && error.name === "AbortError") {
                    return
                }
                if (error instanceof PlatformAccountsRequestError && error.status === 401) {
                    void reload()
                    return
                }
                if (error instanceof PlatformAccountsRequestError && error.status === 404) {
                    setSnapshot({
                        query: requestQuery,
                        requestVersion,
                        cursor: requestCursor,
                        state: { status: "denied" },
                    })
                    return
                }
                setSnapshot({
                    query: requestQuery,
                    requestVersion,
                    cursor: requestCursor,
                    state: { status: "error", error },
                })
            })

        return () => {
            controller.abort()
        }
    }, [query, requestVersion, cursor, reload])

    return { state, query, setQuery, retry, loadMore }
}
