import {
    useCallback,
    useEffect,
    useState,
} from "react"
import {
    fetchQuest,
    QuestRequestError,
} from "../api/quests"
import { useSession } from "../context/SessionContext"
import type {
    QuestDetail,
} from "../types/quest"

export type QuestState =
    | {
        status: "loading"
    }
    | {
        status: "success"
        quest: QuestDetail
    }
    | {
        status: "unavailable"
    }
    | {
        status: "error"
        error: unknown
    }

export interface UseQuestResult {
    state: QuestState
    retry: () => void
}

interface QuestSnapshot {
    campaignId: string
    questId: string
    characterId: string | null
    requestVersion: number
    state: QuestState
}

const initialState: QuestState = {
    status: "loading",
}

export function useQuest(
    campaignId: string,
    questId: string,
    characterId: string | null,
): UseQuestResult {
    const { reload } = useSession()

    const [requestVersion, setRequestVersion] =
        useState(0)

    const [snapshot, setSnapshot] =
        useState<QuestSnapshot>(() => ({
            campaignId,
            questId,
            characterId,
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
        snapshot.questId === questId &&
        snapshot.characterId === characterId &&
        snapshot.requestVersion === requestVersion

    const state = snapshotMatchesRequest
        ? snapshot.state
        : initialState

    useEffect(() => {
        const controller = new AbortController()

        void fetchQuest(
            campaignId,
            questId,
            characterId,
            controller.signal,
        )
            .then((quest) => {
                if (controller.signal.aborted) {
                    return
                }

                setSnapshot({
                    campaignId,
                    questId,
                    characterId,
                    requestVersion,
                    state: {
                        status: "success",
                        quest,
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
                    error instanceof QuestRequestError &&
                    error.status === 401
                ) {
                    void reload()
                    return
                }

                if (
                    error instanceof QuestRequestError &&
                    (error.status === 403 ||
                        error.status === 404)
                ) {
                    setSnapshot({
                        campaignId,
                        questId,
                        characterId,
                        requestVersion,
                        state: {
                            status: "unavailable",
                        },
                    })
                    return
                }

                setSnapshot({
                    campaignId,
                    questId,
                    characterId,
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
        questId,
        characterId,
        reload,
        requestVersion,
    ])

    return {
        state,
        retry,
    }
}