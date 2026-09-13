import {
    useCallback,
    useEffect,
    useState,
} from "react"
import {
    fetchWorldEntities,
    WorldRequestError,
} from "../api/world"
import { useSession } from "../context/SessionContext"
import type {
    WorldCategory,
    WorldEntityPage,
} from "../types/world"

export type WorldEntitiesState =
    | {
        status: "loading"
    }
    | {
        status: "success"
        page: WorldEntityPage
    }
    | {
        // A category/query/cursor change within the same authorized
        // campaign: the previous page is still valid to show while the
        // new one loads.
        status: "refreshing"
        page: WorldEntityPage
    }
    | {
        status: "unavailable"
    }
    | {
        status: "error"
        error: unknown
    }

export interface UseWorldEntitiesResult {
    state: WorldEntitiesState
    retry: () => void
}

interface WorldEntitiesSnapshot {
    campaignId: string
    category: WorldCategory | null
    query: string
    cursor: string | null
    requestVersion: number
    state: WorldEntitiesState
}

const initialState: WorldEntitiesState = {
    status: "loading",
}

function retainedPage(
    state: WorldEntitiesState,
): WorldEntityPage | null {
    return state.status === "success" ||
        state.status === "refreshing"
        ? state.page
        : null
}

export function useWorldEntities(
    campaignId: string,
    category: WorldCategory | null,
    query: string,
    cursor: string | null = null,
): UseWorldEntitiesResult {
    const { reload } = useSession()

    const [requestVersion, setRequestVersion] =
        useState(0)

    const [snapshot, setSnapshot] =
        useState<WorldEntitiesSnapshot>(() => ({
            campaignId,
            category,
            query,
            cursor,
            requestVersion: 0,
            state: initialState,
        }))

    const retry = useCallback(() => {
        setRequestVersion(
            (currentVersion) => currentVersion + 1,
        )
    }, [])

    const snapshotMatchesRequest =
        snapshot.campaignId === campaignId &&
        snapshot.category === category &&
        snapshot.query === query &&
        snapshot.cursor === cursor &&
        snapshot.requestVersion === requestVersion

    // A campaign switch is a new authorization scope: never carry the
    // previous campaign's results into it, even for an instant. A
    // category/query/cursor change within the same campaign is just a
    // different view of already-authorized data, so it may refresh in
    // place.
    const isCampaignChange =
        snapshot.campaignId !== campaignId

    const page = retainedPage(snapshot.state)

    const state: WorldEntitiesState = snapshotMatchesRequest
        ? snapshot.state
        : !isCampaignChange && page !== null
            ? { status: "refreshing", page }
            : initialState

    useEffect(() => {
        const controller = new AbortController()

        void fetchWorldEntities(
            campaignId,
            {
                category,
                query,
                cursor,
            },
            controller.signal,
        )
            .then((page) => {
                if (controller.signal.aborted) {
                    return
                }

                setSnapshot({
                    campaignId,
                    category,
                    query,
                    cursor,
                    requestVersion,
                    state: {
                        status: "success",
                        page,
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
                    error instanceof WorldRequestError &&
                    error.status === 401
                ) {
                    void reload()
                    return
                }

                if (
                    error instanceof WorldRequestError &&
                    (error.status === 403 ||
                        error.status === 404)
                ) {
                    setSnapshot({
                        campaignId,
                        category,
                        query,
                        cursor,
                        requestVersion,
                        state: {
                            status: "unavailable",
                        },
                    })
                    return
                }

                setSnapshot({
                    campaignId,
                    category,
                    query,
                    cursor,
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
    }, [
        campaignId,
        category,
        query,
        cursor,
        reload,
        requestVersion,
    ])

    return {
        state,
        retry,
    }
}
