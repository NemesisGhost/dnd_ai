import {
    useCallback,
    useEffect,
    useState,
} from "react"
import {
    CampaignSessionsRequestError,
    fetchCampaignSession,
} from "../api/campaignSessions"
import { useSession } from "../context/SessionContext"
import type {
    CampaignSessionDetail,
} from "../types/campaignSession"

export type CampaignSessionState =
    | {
        status: "loading"
    }
    | {
        status: "success"
        session: CampaignSessionDetail
    }
    | {
        status: "unavailable"
    }
    | {
        status: "error"
        error: unknown
    }

export interface UseCampaignSessionResult {
    state: CampaignSessionState
    retry: () => void
}

interface CampaignSessionSnapshot {
    campaignId: string
    sessionId: string
    requestVersion: number
    state: CampaignSessionState
}

const initialState: CampaignSessionState = {
    status: "loading",
}

export function useCampaignSession(
    campaignId: string,
    sessionId: string,
): UseCampaignSessionResult {
    const { reload } = useSession()

    const [requestVersion, setRequestVersion] =
        useState(0)

    const [snapshot, setSnapshot] =
        useState<CampaignSessionSnapshot>(() => ({
            campaignId,
            sessionId,
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
        snapshot.sessionId === sessionId &&
        snapshot.requestVersion === requestVersion

    const state = snapshotMatchesRequest
        ? snapshot.state
        : initialState

    useEffect(() => {
        const controller = new AbortController()

        void fetchCampaignSession(
            campaignId,
            sessionId,
            controller.signal,
        )
            .then((session) => {
                if (controller.signal.aborted) {
                    return
                }

                setSnapshot({
                    campaignId,
                    sessionId,
                    requestVersion,
                    state: {
                        status: "success",
                        session,
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
                        sessionId,
                        requestVersion,
                        state: {
                            status: "unavailable",
                        },
                    })
                    return
                }

                setSnapshot({
                    campaignId,
                    sessionId,
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
        sessionId,
        reload,
        requestVersion,
    ])

    return {
        state,
        retry,
    }
}