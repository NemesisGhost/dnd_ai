import {
    useCallback,
    useContext,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
} from "react"
import { WorldRequestError } from "../api/world"
import { useSession } from "../context/SessionContext"
import { BreadcrumbLabelContext } from "../navigation/BreadcrumbLabelContext"
import type { LabelRegistry } from "../navigation/labelRegistry"

export type WorldDetailState<T> =
    | {
        status: "loading"
    }
    | {
        status: "success"
        detail: T
    }
    | {
        status: "unavailable"
    }
    | {
        status: "error"
        error: unknown
    }

export interface UseWorldDetailResult<T> {
    state: WorldDetailState<T>
    retry: () => void
    // The breadcrumb-label authority generation under which the read behind `state` STARTED (see
    // useAuthoringResource), or null while loading or where the read began outside any registry.
    authority: LabelRegistry | null
}

type FetchWorldDetail<T> = (
    campaignId: string,
    entityId: string,
    signal?: AbortSignal,
) => Promise<T>

interface WorldDetailSnapshot<T> {
    campaignId: string
    entityId: string
    requestVersion: number
    state: WorldDetailState<T>
    authority: LabelRegistry | null
}

const initialState: WorldDetailState<never> = {
    status: "loading",
}

// Shared request-lifecycle hook behind every World detail category
// (location/religion/item/event). Every World detail endpoint shares the
// exact (campaignId, entityId, signal) => Promise<T> shape and the same
// WorldRequestError status mapping, so the per-category hooks
// (useLocationDetail, useReligionDetail, ...) are thin wrappers around this
// — never a "render any API object" primitive, since callers still receive
// a fully typed T and domain pages still select which fields to show.
//
// Unlike useWorldEntities (a list, which may refresh in place), a detail
// route never shows the previous record while a new id loads — changing
// campaignId or entityId always resets to "loading".
export function useWorldDetail<T>(
    fetchDetail: FetchWorldDetail<T>,
    campaignId: string,
    entityId: string,
): UseWorldDetailResult<T> {
    const { reload } = useSession()
    // The label authority in force when a request starts: a ref, not a dependency, so a change of
    // authority never starts a read.
    const registry = useContext(BreadcrumbLabelContext)
    const currentAuthority = useRef(registry)
    useLayoutEffect(() => {
        currentAuthority.current = registry
    })

    const [requestVersion, setRequestVersion] = useState(0)

    const [snapshot, setSnapshot] =
        useState<WorldDetailSnapshot<T>>(() => ({
            campaignId,
            entityId,
            requestVersion: 0,
            state: initialState,
            authority: null,
        }))

    const retry = useCallback(() => {
        setRequestVersion(
            (currentVersion) => currentVersion + 1,
        )
    }, [])

    const snapshotMatchesRequest =
        snapshot.campaignId === campaignId &&
        snapshot.entityId === entityId &&
        snapshot.requestVersion === requestVersion

    const state: WorldDetailState<T> = snapshotMatchesRequest
        ? snapshot.state
        : initialState

    useEffect(() => {
        const controller = new AbortController()
        const authority = currentAuthority.current

        void fetchDetail(campaignId, entityId, controller.signal)
            .then((detail) => {
                if (controller.signal.aborted) {
                    return
                }

                setSnapshot({
                    campaignId,
                    entityId,
                    requestVersion,
                    authority,
                    state: {
                        status: "success",
                        detail,
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
                    error instanceof WorldRequestError &&
                    error.status === 401
                ) {
                    setSnapshot({
                        campaignId,
                        entityId,
                        requestVersion,
                        authority,
                        state: initialState,
                    })
                    void reload()
                    return
                }

                if (
                    error instanceof WorldRequestError &&
                    (error.status === 403 || error.status === 404)
                ) {
                    setSnapshot({
                        campaignId,
                        entityId,
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
                    entityId,
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
        entityId,
        fetchDetail,
        reload,
        requestVersion,
    ])

    return {
        state,
        retry,
        authority: snapshotMatchesRequest ? snapshot.authority : null,
    }
}
