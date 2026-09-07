import {
    useCallback,
    useEffect,
    useState,
} from "react"
import {
    fetchCampaignQuests,
    QuestRequestError,
} from "../api/quests"
import { useSession } from "../context/SessionContext"
import type {
    CampaignQuestListItem,
} from "../types/quest"

export type CampaignQuestsState =
    | {
        status: "loading"
    }
    | {
        status: "success"
        quests: CampaignQuestListItem[]
    }
    | {
        status: "unavailable"
    }
    | {
        status: "error"
        error: unknown
    }

export interface UseCampaignQuestsResult {
    state: CampaignQuestsState
    retry: () => void
}

interface CampaignQuestsSnapshot {
    campaignId: string
    characterId: string | null
    requestVersion: number
    state: CampaignQuestsState
}

const initialState: CampaignQuestsState = {
    status: "loading",
}

export function useCampaignQuests(
    campaignId: string,
    characterId: string | null,
): UseCampaignQuestsResult {
    const { reload } = useSession()

    const [requestVersion, setRequestVersion] =
        useState(0)

    const [snapshot, setSnapshot] =
        useState<CampaignQuestsSnapshot>(() => ({
            campaignId,
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
        snapshot.characterId === characterId &&
        snapshot.requestVersion === requestVersion

    const state = snapshotMatchesRequest
        ? snapshot.state
        : initialState

    useEffect(() => {
        const controller = new AbortController()

        void fetchCampaignQuests(
            campaignId,
            characterId,
            controller.signal,
        )
            .then((quests) => {
                if (controller.signal.aborted) {
                    return
                }

                setSnapshot({
                    campaignId,
                    characterId,
                    requestVersion,
                    state: {
                        status: "success",
                        quests,
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
        characterId,
        reload,
        requestVersion,
    ])

    return {
        state,
        retry,
    }
}