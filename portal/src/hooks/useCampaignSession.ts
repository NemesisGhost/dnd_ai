import {
    useCallback,
    useContext,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
} from "react"
import {
    CampaignSessionsRequestError,
    fetchCampaignSession,
} from "../api/campaignSessions"
import { useSession } from "../context/SessionContext"
import { BreadcrumbLabelContext } from "../navigation/BreadcrumbLabelContext"
import type { LabelRegistry } from "../navigation/labelRegistry"
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
    // The breadcrumb-label authority under which the read behind `state` STARTED (see
    // useAuthoringResource): the only registry its answer may publish the session's title into.
    authority: LabelRegistry | null
    // Re-fetches the session in place. The displayed session stays mounted (no
    // loading state) until the response replaces it, so callers keep their
    // unsaved input. Resolves true when fresh data was applied.
    refresh: () => Promise<boolean>
}

interface CampaignSessionSnapshot {
    campaignId: string
    sessionId: string
    requestVersion: number
    state: CampaignSessionState
    authority: LabelRegistry | null
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
            authority: null,
        }))

    // The label authority now in force, read when a request starts (a ref: a change of authority must
    // not start a read).
    const registry = useContext(BreadcrumbLabelContext)
    const currentAuthority = useRef(registry)
    useLayoutEffect(() => {
        currentAuthority.current = registry
    })

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
        const authority = currentAuthority.current

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
                    authority,
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
                        authority,
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
                    authority,
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

    const refreshController = useRef<AbortController | null>(null)

    useEffect(() => {
        return () => {
            refreshController.current?.abort()
        }
    }, [campaignId, sessionId])

    const refresh = useCallback(async (): Promise<boolean> => {
        refreshController.current?.abort()
        const controller = new AbortController()
        refreshController.current = controller
        const authority = currentAuthority.current

        try {
            const session = await fetchCampaignSession(
                campaignId,
                sessionId,
                controller.signal,
            )

            if (controller.signal.aborted) {
                return false
            }

            setSnapshot({
                campaignId,
                sessionId,
                requestVersion,
                authority,
                state: {
                    status: "success",
                    session,
                },
            })
            return true
        } catch (error: unknown) {
            if (controller.signal.aborted) {
                return false
            }

            if (
                error instanceof CampaignSessionsRequestError &&
                error.status === 401
            ) {
                void reload()
            } else if (
                error instanceof CampaignSessionsRequestError &&
                (error.status === 403 || error.status === 404)
            ) {
                setSnapshot({
                    campaignId,
                    sessionId,
                    requestVersion,
                    authority,
                    state: {
                        status: "unavailable",
                    },
                })
            }

            return false
        }
    }, [campaignId, sessionId, reload, requestVersion])

    return {
        state,
        retry,
        authority: snapshotMatchesRequest ? snapshot.authority : null,
        refresh,
    }
}