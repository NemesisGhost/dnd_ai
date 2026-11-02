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
import { usePartyNotFoundEpisodes } from "./usePartyScopeRecovery"
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
    partyId: string | null
    requestVersion: number
    state: CampaignQuestsState
}

const initialState: CampaignQuestsState = {
    status: "loading",
}

export function useCampaignQuests(
    campaignId: string,
    characterId: string | null,
    partyId: string | null = null,
): UseCampaignQuestsResult {
    const { reload } = useSession()
    const partyEpisode = usePartyNotFoundEpisodes()

    const [requestVersion, setRequestVersion] =
        useState(0)

    const [snapshot, setSnapshot] =
        useState<CampaignQuestsSnapshot>(() => ({
            campaignId,
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
        snapshot.characterId === characterId &&
        snapshot.partyId === partyId &&
        snapshot.requestVersion === requestVersion

    const state = snapshotMatchesRequest
        ? snapshot.state
        : initialState

    useEffect(() => {
        const controller = new AbortController()

        void fetchCampaignQuests(
            campaignId,
            characterId,
            partyId,
            controller.signal,
        )
            .then((quests) => {
                if (controller.signal.aborted) {
                    return
                }

                setSnapshot({
                    campaignId,
                    characterId,
                    partyId,
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

                // A party-scoped 404 may mean the party is no longer authorized. Nothing of this
                // party's is kept meanwhile; eligibility is refreshed once for this episode, and
                // the page then either re-derives its selection (the party is gone, so this effect
                // re-runs without it) or this stays an ordinary "unavailable".
                if (
                    error instanceof QuestRequestError &&
                    error.status === 404 &&
                    characterId !== null &&
                    partyId !== null
                ) {
                    setSnapshot({
                        campaignId,
                        characterId,
                        partyId,
                        requestVersion,
                        state: initialState,
                    })
                    void partyEpisode(
                        [campaignId, characterId, partyId, requestVersion].join("|"),
                    ).then((outcome) => {
                        if (controller.signal.aborted || outcome === "signed_out") {
                            return
                        }

                        setSnapshot({
                            campaignId,
                            characterId,
                            partyId,
                            requestVersion,
                            state:
                                outcome === "failed"
                                    ? { status: "error", error }
                                    : { status: "unavailable" },
                        })
                    })
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
        characterId,
        partyId,
        partyEpisode,
        reload,
        requestVersion,
    ])

    return {
        state,
        retry,
    }
}