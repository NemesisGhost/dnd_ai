import {
    useCallback,
    useContext,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
} from "react"
import {
    CharacterRequestError,
    fetchCharacter,
} from "../api/character"
import { useSession } from "../context/SessionContext"
import { BreadcrumbLabelContext } from "../navigation/BreadcrumbLabelContext"
import type { LabelRegistry } from "../navigation/labelRegistry"
import type { CharacterDetail } from "../types/character"

export type CharacterState =
    | {
        status: "loading"
    }
    | {
        status: "success"
        character: CharacterDetail
    }
    | {
        status: "unavailable"
    }
    | {
        status: "error"
        error: unknown
    }

export interface UseCharacterResult {
    state: CharacterState
    retry: () => void
    // The breadcrumb-label authority under which the read behind `state` STARTED (see
    // useAuthoringResource): the only registry its answer may publish the character's name into.
    authority: LabelRegistry | null
}

interface CharacterSnapshot {
    campaignId: string
    characterId: string
    requestVersion: number
    state: CharacterState
    authority: LabelRegistry | null
}

const initialState: CharacterState = {
    status: "loading",
}

export function useCharacter(
    campaignId: string,
    characterId: string,
): UseCharacterResult {
    const { reload } = useSession()
    const [requestVersion, setRequestVersion] = useState(0)

    const [snapshot, setSnapshot] =
        useState<CharacterSnapshot>(() => ({
            campaignId,
            characterId,
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
        snapshot.characterId === characterId &&
        snapshot.requestVersion === requestVersion

    const state = snapshotMatchesRequest
        ? snapshot.state
        : initialState

    useEffect(() => {
        const controller = new AbortController()
        const authority = currentAuthority.current

        void fetchCharacter(
            campaignId,
            characterId,
            controller.signal,
        )
            .then((character) => {
                if (controller.signal.aborted) {
                    return
                }

                setSnapshot({
                    campaignId,
                    characterId,
                    requestVersion,
                    authority,
                    state: {
                        status: "success",
                        character,
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
                    error instanceof CharacterRequestError &&
                    error.status === 401
                ) {
                    void reload()
                    return
                }

                if (
                    error instanceof CharacterRequestError &&
                    (error.status === 403 || error.status === 404)
                ) {
                    setSnapshot({
                        campaignId,
                        characterId,
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
                    characterId,
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
        characterId,
        reload,
        requestVersion,
    ])

    return {
        state,
        retry,
        authority: snapshotMatchesRequest ? snapshot.authority : null,
    }
}