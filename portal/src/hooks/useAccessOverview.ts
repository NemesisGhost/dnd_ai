import {
    useCallback,
    useEffect,
    useState,
} from "react"
import {
    AccessOverviewRequestError,
    fetchCampaignAccessOverview,
} from "../api/accessOverview"
import { useSession } from "../context/SessionContext"
import type {
    CampaignAccessOverview,
} from "../types/accessOverview"

export type AccessOverviewState =
    | {
        status: "loading"
    }
    | {
        status: "success"
        overview: CampaignAccessOverview
    }
    | {
        status: "unavailable"
    }
    | {
        status: "error"
        error: unknown
    }

export interface UseAccessOverviewResult {
    state: AccessOverviewState
    retry: () => void
}

interface AccessOverviewSnapshot {
    campaignId: string
    requestVersion: number
    state: AccessOverviewState
}

const initialState: AccessOverviewState = {
    status: "loading",
}

// Campaign-scoped, no perspective/character parameter — every request
// needs only campaignId (docs/PLAN.md Phase 13E-A). A campaign change
// (or a retry) never retains the previous campaign's members: any
// mismatch between the last-seen request and the current one falls back
// to initialState below, exactly like dnd_ai's useCampaignQuests — access
// data is authorization-sensitive, so this hook never keeps a prior
// campaign's overview visible as "refreshing" while a new one loads.
export function useAccessOverview(
    campaignId: string,
): UseAccessOverviewResult {
    const { reload } = useSession()

    const [requestVersion, setRequestVersion] =
        useState(0)

    const [snapshot, setSnapshot] =
        useState<AccessOverviewSnapshot>(() => ({
            campaignId,
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
        snapshot.requestVersion === requestVersion

    const state = snapshotMatchesRequest
        ? snapshot.state
        : initialState

    useEffect(() => {
        const controller = new AbortController()

        void fetchCampaignAccessOverview(
            campaignId,
            controller.signal,
        )
            .then((overview) => {
                if (controller.signal.aborted) {
                    return
                }

                setSnapshot({
                    campaignId,
                    requestVersion,
                    state: {
                        status: "success",
                        overview,
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
                    AccessOverviewRequestError &&
                    error.status === 401
                ) {
                    void reload()
                    return
                }

                if (
                    error instanceof
                    AccessOverviewRequestError &&
                    (error.status === 403 ||
                        error.status === 404)
                ) {
                    setSnapshot({
                        campaignId,
                        requestVersion,
                        state: {
                            status: "unavailable",
                        },
                    })
                    return
                }

                setSnapshot({
                    campaignId,
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
        reload,
        requestVersion,
    ])

    return {
        state,
        retry,
    }
}
