import {
    useCallback,
    useEffect,
    useState,
} from "react"
import {
    CampaignSessionsRequestError,
    fetchCampaignSessions,
} from "../api/campaignSessions"
import { useSession } from "../context/SessionContext"
import type {
    CampaignSessionListItem,
} from "../types/campaignSession"

export type CampaignSessionsState =
    | {
        status: "loading"
    }
    | {
        status: "success"
        sessions: CampaignSessionListItem[]
    }
    | {
        status: "unavailable"
    }
    | {
        status: "error"
        error: unknown
    }

export interface UseCampaignSessionsResult {
    state: CampaignSessionsState
    retry: () => void
}

interface CampaignSessionsSnapshot {
    campaignId: string
    requestVersion: number
    state: CampaignSessionsState
}

const initialState: CampaignSessionsState = {
    status: "loading",
}

export function useCampaignSessions(
    campaignId: string,
): UseCampaignSessionsResult {
    const { reload } = useSession()
    const [requestVersion, setRequestVersion] = useState(0)

    const [snapshot, setSnapshot] =
        useState<CampaignSessionsSnapshot>(() => ({
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

        void fetchCampaignSessions(
            campaignId,
            controller.signal,
        )
            .then((sessions) => {
                if (controller.signal.aborted) {
                    return
                }

                setSnapshot({
                    campaignId,
                    requestVersion,
                    state: {
                        status: "success",
                        sessions,
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
                    error instanceof CampaignSessionsRequestError &&
                    error.status === 401
                ) {
                    void reload()
                    return
                }

                if (
                    error instanceof CampaignSessionsRequestError &&
                    (error.status === 403 || error.status === 404)
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