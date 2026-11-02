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
import { usePartyNotFoundEpisodes } from "./usePartyScopeRecovery"
import type {
    KnowledgeLifecycle,
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
        // The server refused a non-active lifecycle (archive browsing is not allowed for this
        // caller): the page falls back to the active list rather than showing a dead end.
        status: "lifecycle_rejected"
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
    includePublic: boolean
    lifecycle: KnowledgeLifecycle
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
    includePublic = true,
    lifecycle: KnowledgeLifecycle = "active",
): UseKnowledgeItemsResult {
    const { reload } = useSession()
    const partyEpisode = usePartyNotFoundEpisodes()

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
            includePublic,
            lifecycle,
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
        snapshot.includePublic === includePublic &&
        snapshot.lifecycle === lifecycle &&
        snapshot.requestVersion ===
        requestVersion

    // A lifecycle change is a different collection, not a refinement: never keep showing the
    // previous lifecycle's results while the new ones load (they would be mislabelled).
    const authorizationScopeMatches =
        snapshot.campaignId === campaignId &&
        snapshot.lifecycle === lifecycle &&
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
                includePublic,
                lifecycle,
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
                    includePublic,
                    lifecycle,
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
                        includePublic,
                        lifecycle,
                        requestVersion,
                        state: initialState,
                    })

                    void reload()
                    return
                }

                if (
                    error instanceof
                    KnowledgeRequestError &&
                    error.status === 403 &&
                    lifecycle !== "active"
                ) {
                    setSnapshot({
                        campaignId,
                        view,
                        characterId,
                        partyId,
                        query,
                        knowledgeType,
                        cursor,
                        includePublic,
                        lifecycle,
                        requestVersion,
                        state: {
                            status:
                                "lifecycle_rejected",
                        },
                    })
                    return
                }

                // A party-scoped 404 may mean the party is no longer authorized: the party's results
                // are dropped at once (no "refreshing" page is kept), eligibility is refreshed once
                // for this episode, and the page then re-derives its selection or this stays an
                // ordinary "unavailable".
                if (
                    error instanceof
                    KnowledgeRequestError &&
                    error.status === 404 &&
                    characterId !== null &&
                    partyId !== null
                ) {
                    const scope = {
                        campaignId,
                        view,
                        characterId,
                        partyId,
                        query,
                        knowledgeType,
                        cursor,
                        includePublic,
                        lifecycle,
                        requestVersion,
                    }
                    setSnapshot({ ...scope, state: initialState })
                    void partyEpisode(
                        [
                            campaignId,
                            view,
                            characterId,
                            partyId,
                            query,
                            knowledgeType,
                            cursor,
                            includePublic,
                            lifecycle,
                            requestVersion,
                        ].join("|"),
                    ).then((outcome) => {
                        if (controller.signal.aborted) {
                            return
                        }

                        setSnapshot({
                            ...scope,
                            state:
                                outcome === "failed"
                                    ? { status: "error", error }
                                    : { status: "unavailable" },
                        })
                    })
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
                        includePublic,
                        lifecycle,
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
                    includePublic,
                    lifecycle,
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
        includePublic,
        lifecycle,
        requestVersion,
        partyEpisode,
        reload,
    ])

    return {
        state,
        retry,
    }
}