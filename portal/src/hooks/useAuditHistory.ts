import {
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react"
import {
    AuditHistoryRequestError,
    fetchAuditHistory,
} from "../api/auditHistory"
import { useSession } from "../context/SessionContext"
import type {
    AuditHistoryFilters,
    AuditHistoryItem,
} from "../types/auditHistory"

export type AuditHistoryState =
    | {
        status: "loading"
    }
    | {
        status: "success"
        items: AuditHistoryItem[]
        nextCursor: string | null
        isLoadingMore: boolean
        loadMoreError: boolean
    }
    | {
        status: "unavailable"
    }
    | {
        status: "error"
        error: unknown
    }

export interface UseAuditHistoryResult {
    state: AuditHistoryState
    retry: () => void
    loadMore: () => void
}

interface Snapshot {
    campaignId: string
    filtersKey: string
    requestVersion: number
    state: AuditHistoryState
}

const initialState: AuditHistoryState = {
    status: "loading",
}

// A stable, order-independent key for the filter set this hook currently
// represents — used (rather than comparing the filters object by
// reference) so a caller re-creating an equal-by-value filters object on
// every render never trips a spurious reset, while a genuine filter
// change always does.
function filtersKeyOf(filters: AuditHistoryFilters): string {
    return JSON.stringify([
        filters.category,
        filters.actorUserId,
        filters.occurredFrom,
        filters.occurredTo,
    ])
}

// Campaign-scoped, filter-scoped audit history with "load more" keyset
// pagination (dnd_ai.api.audit_history — see docs/AUDIT_HISTORY_API.md).
//
// A campaign or filter change is always a full reset to "loading" — never
// a "refreshing" carry-over of the previous scope's items (unlike
// useWorldEntities' category/query refresh-in-place allowance) — matching
// useAccessOverview's stricter posture: this is authorization-sensitive,
// per-campaign audit data, so a prior campaign's (or prior filter set's)
// rows must never remain visible, even briefly, while a new request is in
// flight.
//
// Stale-response suppression: the single AbortController created for the
// current (campaignId, filters, requestVersion) scope is reused by
// loadMore() as well, so a campaign/filter change (or retry()) aborts any
// in-flight "load more" fetch the same way it aborts the primary one —
// its resolution is then a no-op against a scope the hook has already
// moved on from, never appended to the new scope's items.
export function useAuditHistory(
    campaignId: string,
    filters: AuditHistoryFilters,
): UseAuditHistoryResult {
    const { reload } = useSession()

    const [requestVersion, setRequestVersion] =
        useState(0)

    const filtersKey = filtersKeyOf(filters)

    const [snapshot, setSnapshot] =
        useState<Snapshot>(() => ({
            campaignId,
            filtersKey,
            requestVersion: 0,
            state: initialState,
        }))

    const snapshotRef = useRef(snapshot)
    useEffect(() => {
        snapshotRef.current = snapshot
    }, [snapshot])

    const abortControllerRef =
        useRef<AbortController | null>(null)

    const retry = useCallback(() => {
        setRequestVersion(
            (currentVersion) => currentVersion + 1,
        )
    }, [])

    const snapshotMatchesRequest =
        snapshot.campaignId === campaignId &&
        snapshot.filtersKey === filtersKey &&
        snapshot.requestVersion === requestVersion

    const state: AuditHistoryState = snapshotMatchesRequest
        ? snapshot.state
        : initialState

    useEffect(() => {
        const controller = new AbortController()
        abortControllerRef.current = controller

        void fetchAuditHistory(
            campaignId,
            filters,
            null,
            controller.signal,
        )
            .then((page) => {
                if (controller.signal.aborted) {
                    return
                }

                setSnapshot({
                    campaignId,
                    filtersKey,
                    requestVersion,
                    state: {
                        status: "success",
                        items: page.items,
                        nextCursor: page.next_cursor,
                        isLoadingMore: false,
                        loadMoreError: false,
                    },
                })
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return
                }

                if (
                    error instanceof DOMException &&
                    error.name === "AbortError"
                ) {
                    return
                }

                if (
                    error instanceof
                    AuditHistoryRequestError &&
                    error.status === 401
                ) {
                    // A stale authorization: drop any retained state
                    // before reloading the session rather than leaving a
                    // now-untrustworthy page visible.
                    setSnapshot({
                        campaignId,
                        filtersKey,
                        requestVersion,
                        state: initialState,
                    })
                    void reload()
                    return
                }

                if (
                    error instanceof
                    AuditHistoryRequestError &&
                    (error.status === 403 ||
                        error.status === 404)
                ) {
                    setSnapshot({
                        campaignId,
                        filtersKey,
                        requestVersion,
                        state: {
                            status: "unavailable",
                        },
                    })
                    return
                }

                setSnapshot({
                    campaignId,
                    filtersKey,
                    requestVersion,
                    state: {
                        status: "error",
                        error,
                    },
                })
            })

        return () => {
            controller.abort()
        }
        // filters is intentionally represented by filtersKey — an
        // object re-created on every render with equal contents must not
        // retrigger this effect.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [campaignId, filtersKey, reload, requestVersion])

    const loadMore = useCallback(() => {
        const current = snapshotRef.current
        if (
            current.campaignId !== campaignId ||
            current.filtersKey !== filtersKey ||
            current.requestVersion !== requestVersion ||
            current.state.status !== "success" ||
            current.state.nextCursor === null ||
            current.state.isLoadingMore
        ) {
            return
        }

        const cursor = current.state.nextCursor
        const controller = abortControllerRef.current
        if (controller === null || controller.signal.aborted) {
            return
        }

        setSnapshot((prev) =>
            prev.state.status === "success"
                ? {
                    ...prev,
                    state: {
                        ...prev.state,
                        isLoadingMore: true,
                        loadMoreError: false,
                    },
                }
                : prev,
        )

        void fetchAuditHistory(
            campaignId,
            filters,
            cursor,
            controller.signal,
        )
            .then((page) => {
                if (controller.signal.aborted) {
                    return
                }
                setSnapshot((prev) => {
                    if (
                        prev.campaignId !== campaignId ||
                        prev.filtersKey !== filtersKey ||
                        prev.requestVersion !==
                        requestVersion ||
                        prev.state.status !== "success"
                    ) {
                        return prev
                    }
                    return {
                        ...prev,
                        state: {
                            status: "success",
                            items: [
                                ...prev.state.items,
                                ...page.items,
                            ],
                            nextCursor: page.next_cursor,
                            isLoadingMore: false,
                            loadMoreError: false,
                        },
                    }
                })
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return
                }
                if (
                    error instanceof DOMException &&
                    error.name === "AbortError"
                ) {
                    return
                }
                // A "load more" failure is recoverable in place: keep the
                // already-loaded items visible and let the caller retry
                // loadMore() again, rather than discarding a successful
                // first page over a second-page network error.
                setSnapshot((prev) =>
                    prev.campaignId === campaignId &&
                        prev.filtersKey === filtersKey &&
                        prev.requestVersion ===
                        requestVersion &&
                        prev.state.status === "success"
                        ? {
                            ...prev,
                            state: {
                                ...prev.state,
                                isLoadingMore: false,
                                loadMoreError: true,
                            },
                        }
                        : prev,
                )
            })
    }, [campaignId, filters, filtersKey, requestVersion])

    return {
        state,
        retry,
        loadMore,
    }
}
