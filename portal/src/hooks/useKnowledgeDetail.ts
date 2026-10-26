import {
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react"
import {
    fetchKnowledgeDetail,
    KnowledgeRequestError,
} from "../api/knowledge"
import { useSession } from "../context/SessionContext"
import type { RefetchOutcome } from "./useAuthoringResource"
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
    // Re-reads the detail in place: the current item stays on screen (nothing remounts)
    // until the new one arrives, unlike `retry`, which starts again from "loading". It resolves
    // with what the read did and never rejects. "failed": it was not applied; a recoverable
    // failure keeps the item already shown (a caller that just saved reports it as behind), while
    // a refused or missing answer makes the item unavailable. "superseded": a newer read, a change
    // of record or perspective, or a sign-in boundary replaced it.
    refresh: () => Promise<RefetchOutcome>
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
    const refreshController = useRef<AbortController | null>(null)

    const [snapshot, setSnapshot] =
        useState<KnowledgeDetailSnapshot>(() => ({
            campaignId,
            knowledgeItemId,
            characterId,
            partyId,
            requestVersion: 0,
            state: initialState,
        }))

    const refresh = useCallback(async (): Promise<RefetchOutcome> => {
        refreshController.current?.abort()
        const controller = new AbortController()
        refreshController.current = controller
        const keys = { campaignId, knowledgeItemId, characterId, partyId, requestVersion }
        try {
            const item = await fetchKnowledgeDetail(
                campaignId,
                knowledgeItemId,
                characterId,
                partyId,
                controller.signal,
            )
            if (controller.signal.aborted) return "superseded"
            setSnapshot({ ...keys, state: { status: "success", item } })
            return "ok"
        } catch (error: unknown) {
            if (controller.signal.aborted) return "superseded"
            if (error instanceof DOMException && error.name === "AbortError") return "superseded"
            if (error instanceof KnowledgeRequestError && error.status === 401) {
                void reload()
                return "superseded"
            }
            if (
                error instanceof KnowledgeRequestError &&
                (error.status === 403 || error.status === 404)
            ) {
                setSnapshot({ ...keys, state: { status: "unavailable" } })
                return "failed"
            }
            // Recoverable: the item already shown stays, and the caller says it may be behind.
            return "failed"
        }
    }, [campaignId, knowledgeItemId, characterId, partyId, requestVersion, reload])

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
            refreshController.current?.abort()
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
        refresh,
    }
}
