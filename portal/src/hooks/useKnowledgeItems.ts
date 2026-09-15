import {
    useCallback,
    useEffect,
    useState,
} from "react"
import {
    fetchKnowledgeItems,
    KnowledgeRequestError,
} from "../api/knowledge"
import {
    useSession,
} from "../context/SessionContext"
import type {
    KnowledgePage,
    KnowledgeView,
} from "../types/knowledge"

export type KnowledgeItemsState =
    | {
        status: "loading"
    }
    | {
        status: "success"
        page: KnowledgePage
    }
    | {
        status: "refreshing"
        page: KnowledgePage
    }
    | {
        status: "unavailable"
    }
    | {
        status: "error"
        error: unknown
    }

export interface UseKnowledgeItemsResult {
    state: KnowledgeItemsState
    retry: () => void
}

interface KnowledgeItemsSnapshot {
    campaignId: string
    view: KnowledgeView
    characterId: string | null
    partyId: string | null
    query: string
    knowledgeType: string | null
    cursor: string | null
    requestVersion: number
    state: KnowledgeItemsState
}

const initialState: KnowledgeItemsState = {
    status: "loading",
}

function retainedPage(
    state: KnowledgeItemsState,
): KnowledgePage | null {
    return state.status === "success" ||
        state.status === "refreshing"
        ? state.page
        : null
}

export function useKnowledgeItems(
    campaignId: string,
    view: KnowledgeView,
    characterId: string | null,
    partyId: string | null,
    query: string,
    knowledgeType: string | null,
    cursor: string | null = null,
): UseKnowledgeItemsResult {
    const { reload } = useSession()

    const [requestVersion, setRequestVersion] =
        useState(0)

    const [snapshot, setSnapshot] =
        useState<KnowledgeItemsSnapshot>(() => ({
            campaignId,
            view,
            characterId,
            partyId,
            query,
            knowledgeType,
            cursor,
            requestVersion: 0,
            state: initialState,
        }))

    const retry = useCallback(() => {
        setRequestVersion(
            (currentVersion) =>
                currentVersion + 1,
        )
    }, [])

    const snapshotMatchesRequest =
        snapshot.campaignId === campaignId &&
        snapshot.view === view &&
        snapshot.characterId === characterId &&
        snapshot.partyId === partyId &&
        snapshot.query === query &&
        snapshot.knowledgeType ===
        knowledgeType &&
        snapshot.cursor === cursor &&
        snapshot.requestVersion ===
        requestVersion

    const authorizationScopeMatches =
        snapshot.campaignId === campaignId &&
        snapshot.view === view &&
        snapshot.characterId === characterId &&
        snapshot.partyId === partyId

    const previousPage =
        retainedPage(snapshot.state)

    const state: KnowledgeItemsState =
        snapshotMatchesRequest
            ? snapshot.state
            : authorizationScopeMatches &&
                previousPage !== null
                ? {
                    status: "refreshing",
                    page: previousPage,
                }
                : initialState

    useEffect(() => {
        const controller =
            new AbortController()

        void fetchKnowledgeItems(
            campaignId,
            {
                view,
                characterId,
                partyId,
                query,
                knowledgeType,
                cursor,
            },
            controller.signal,
        )
            .then((page) => {
                if (
                    controller.signal.aborted
                ) {
                    return
                }

                setSnapshot({
                    campaignId,
                    view,
                    characterId,
                    partyId,
                    query,
                    knowledgeType,
                    cursor,
                    requestVersion,
                    state: {
                        status: "success",
                        page,
                    },
                })
            })
            .catch((error: unknown) => {
                if (
                    controller.signal.aborted
                ) {
                    return
                }

                if (
                    error instanceof
                    DOMException &&
                    error.name ===
                    "AbortError"
                ) {
                    return
                }

                if (
                    error instanceof
                    KnowledgeRequestError &&
                    error.status === 401
                ) {
                    setSnapshot({
                        campaignId,
                        view,
                        characterId,
                        partyId,
                        query,
                        knowledgeType,
                        cursor,
                        requestVersion,
                        state: initialState,
                    })

                    void reload()
                    return
                }

                if (
                    error instanceof
                    KnowledgeRequestError &&
                    (error.status === 403 ||
                        error.status === 404)
                ) {
                    setSnapshot({
                        campaignId,
                        view,
                        characterId,
                        partyId,
                        query,
                        knowledgeType,
                        cursor,
                        requestVersion,
                        state: {
                            status:
                                "unavailable",
                        },
                    })
                    return
                }

                setSnapshot({
                    campaignId,
                    view,
                    characterId,
                    partyId,
                    query,
                    knowledgeType,
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
        view,
        characterId,
        partyId,
        query,
        knowledgeType,
        cursor,
        requestVersion,
        reload,
    ])

    return {
        state,
        retry,
    }
}