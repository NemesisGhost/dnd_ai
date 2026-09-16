import {
    useCallback,
    useEffect,
    useState,
} from "react"
import {
    fetchKnowledgeDetail,
    KnowledgeRequestError,
} from "../api/knowledge"
import { useSession } from "../context/SessionContext"
import type { KnowledgeDetail } from "../types/knowledge"

export type KnowledgeDetailState =
    | {
        status: "loading"
    }
    | {
        status: "success"
        item: KnowledgeDetail
    }
    | {
        status: "unavailable"
    }
    | {
        status: "error"
        error: unknown
    }

export interface UseKnowledgeDetailResult {
    state: KnowledgeDetailState
    retry: () => void
}

interface KnowledgeDetailSnapshot {
    campaignId: string
    knowledgeItemId: string
    characterId: string | null
    partyId: string | null
    requestVersion: number
    state: KnowledgeDetailState
}

const initialState: KnowledgeDetailState = {
    status: "loading",
}

// A missing, foreign, unauthorized, or cross-campaign item is treated
// identically to a nonexistent one (403/404 -> "unavailable"), matching the
// backend's fixed non-disclosing 404. The previous record is never shown
// while a new id/perspective loads — every key field resets to "loading".
export function useKnowledgeDetail(
    campaignId: string,
    knowledgeItemId: string,
    characterId: string | null,
    partyId: string | null,
): UseKnowledgeDetailResult {
    const { reload } = useSession()
    const [requestVersion, setRequestVersion] = useState(0)

    const [snapshot, setSnapshot] =
        useState<KnowledgeDetailSnapshot>(() => ({
            campaignId,
            knowledgeItemId,
            characterId,
            partyId,
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
        snapshot.knowledgeItemId === knowledgeItemId &&
        snapshot.characterId === characterId &&
        snapshot.partyId === partyId &&
        snapshot.requestVersion === requestVersion

    const state = snapshotMatchesRequest
        ? snapshot.state
        : initialState

    useEffect(() => {
        const controller = new AbortController()

        void fetchKnowledgeDetail(
            campaignId,
            knowledgeItemId,
            characterId,
            partyId,
            controller.signal,
        )
            .then((item) => {
                if (controller.signal.aborted) {
                    return
                }

                setSnapshot({
                    campaignId,
                    knowledgeItemId,
                    characterId,
                    partyId,
                    requestVersion,
                    state: {
                        status: "success",
                        item,
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
                    error instanceof KnowledgeRequestError &&
                    error.status === 401
                ) {
                    setSnapshot({
                        campaignId,
                        knowledgeItemId,
                        characterId,
                        partyId,
                        requestVersion,
                        state: initialState,
                    })
                    void reload()
                    return
                }

                if (
                    error instanceof KnowledgeRequestError &&
                    (error.status === 403 || error.status === 404)
                ) {
                    setSnapshot({
                        campaignId,
                        knowledgeItemId,
                        characterId,
                        partyId,
                        requestVersion,
                        state: {
                            status: "unavailable",
                        },
                    })
                    return
                }

                setSnapshot({
                    campaignId,
                    knowledgeItemId,
                    characterId,
                    partyId,
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
        knowledgeItemId,
        characterId,
        partyId,
        reload,
        requestVersion,
    ])

    return {
        state,
        retry,
    }
}
