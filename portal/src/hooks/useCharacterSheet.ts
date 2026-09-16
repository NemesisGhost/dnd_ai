import {
    useCallback,
    useEffect,
    useState,
} from "react"
import {
    CharacterSheetRequestError,
    fetchCharacterSheet,
} from "../api/characterSheet"
import { useSession } from "../context/SessionContext"
import type { CharacterSheet } from "../types/characterSheet"

export type CharacterSheetState =
    | {
        status: "loading"
    }
    | {
        status: "success"
        sheet: CharacterSheet
    }
    | {
        status: "unavailable"
    }
    | {
        status: "error"
        error: unknown
    }

export interface UseCharacterSheetResult {
    state: CharacterSheetState
    retry: () => void
}

interface CharacterSheetSnapshot {
    campaignId: string
    characterId: string
    requestVersion: number
    state: CharacterSheetState
}

const initialState: CharacterSheetState = {
    status: "loading",
}

export function useCharacterSheet(
    campaignId: string,
    characterId: string,
): UseCharacterSheetResult {
    const { reload } = useSession()

    const [requestVersion, setRequestVersion] =
        useState(0)

    const [snapshot, setSnapshot] =
        useState<CharacterSheetSnapshot>(() => ({
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

        void fetchCharacterSheet(
            campaignId,
            characterId,
            controller.signal,
        )
            .then((sheet) => {
                if (controller.signal.aborted) {
                    return
                }

                setSnapshot({
                    campaignId,
                    characterId,
                    requestVersion,
                    state: {
                        status: "success",
                        sheet,
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
                    error instanceof CharacterSheetRequestError &&
                    error.status === 401
                ) {
                    void reload()
                    return
                }

                if (
                    error instanceof CharacterSheetRequestError &&
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