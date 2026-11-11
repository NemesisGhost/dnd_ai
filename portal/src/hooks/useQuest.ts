import {
    useCallback,
    useContext,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
} from "react"
import {
    fetchQuest,
    QuestRequestError,
} from "../api/quests"
import { useSession } from "../context/SessionContext"
import { BreadcrumbLabelContext } from "../navigation/BreadcrumbLabelContext"
import type { LabelRegistry } from "../navigation/labelRegistry"
import { usePartyNotFoundEpisodes } from "./usePartyScopeRecovery"
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
    // The breadcrumb-label authority under which the read behind `state` STARTED (see
    // useAuthoringResource): the only registry its answer may publish the record's name into.
    authority: LabelRegistry | null
}

interface QuestSnapshot {
    campaignId: string
    questId: string
    characterId: string | null
    partyId: string | null
    requestVersion: number
    state: QuestState
    authority: LabelRegistry | null
}

const initialState: QuestState = {
    status: "loading",
}

export function useQuest(
    campaignId: string,
    questId: string,
    characterId: string | null,
    partyId: string | null = null,
): UseQuestResult {
    const { reload } = useSession()
    const partyEpisode = usePartyNotFoundEpisodes()

    const [requestVersion, setRequestVersion] =
        useState(0)

    const [snapshot, setSnapshot] =
        useState<QuestSnapshot>(() => ({
            campaignId,
            questId,
            characterId,
            partyId,
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
        snapshot.questId === questId &&
        snapshot.characterId === characterId &&
        snapshot.partyId === partyId &&
        snapshot.requestVersion === requestVersion

    const state = snapshotMatchesRequest
        ? snapshot.state
        : initialState

    useEffect(() => {
        const controller = new AbortController()
        const authority = currentAuthority.current

        void fetchQuest(
            campaignId,
            questId,
            characterId,
            partyId,
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
                    partyId,
                    requestVersion,
                    authority,
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

                // See useCampaignQuests: a party-scoped 404 is rechecked once per episode and the
                // party's content is never kept while that happens.
                if (
                    error instanceof QuestRequestError &&
                    error.status === 404 &&
                    characterId !== null &&
                    partyId !== null
                ) {
                    setSnapshot({
                        campaignId,
                        questId,
                        characterId,
                        partyId,
                        requestVersion,
                        authority,
                        state: initialState,
                    })
                    void partyEpisode(
                        [campaignId, questId, characterId, partyId, requestVersion].join("|"),
                    ).then((outcome) => {
                        if (controller.signal.aborted) {
                            return
                        }

                        setSnapshot({
                            campaignId,
                            questId,
                            characterId,
                            partyId,
                            requestVersion,
                            authority,
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
                        questId,
                        characterId,
                        partyId,
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
                    questId,
                    characterId,
                    partyId,
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
        questId,
        characterId,
        partyId,
        partyEpisode,
        reload,
        requestVersion,
    ])

    return {
        state,
        retry,
        authority: snapshotMatchesRequest ? snapshot.authority : null,
    }
}