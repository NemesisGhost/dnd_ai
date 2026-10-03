import { useCallback, useEffect, useState } from "react"
import { fetchOwnSessions, OwnSessionsRequestError } from "../api/ownSessions"
import { useSession } from "../context/SessionContext"
import type { OwnBrowserSession } from "../types/accountSessions"

export type OwnSessionsState =
    | { status: "loading" }
    | { status: "success"; sessions: OwnBrowserSession[] }
    | { status: "error"; error: unknown }

export interface UseOwnSessionsResult {
    state: OwnSessionsState
    retry: () => void
}

interface Snapshot {
    requestVersion: number
    state: OwnSessionsState
}

const initialState: OwnSessionsState = { status: "loading" }

export function useOwnSessions(): UseOwnSessionsResult {
    const { reload } = useSession()
    const [requestVersion, setRequestVersion] = useState(0)
    const [snapshot, setSnapshot] = useState<Snapshot>(() => ({
        requestVersion: 0,
        state: initialState,
    }))

    const retry = useCallback(() => {
        setRequestVersion((current) => current + 1)
    }, [])

    const state = snapshot.requestVersion === requestVersion ? snapshot.state : initialState

    useEffect(() => {
        const controller = new AbortController()

        void fetchOwnSessions(controller.signal)
            .then((sessions) => {
                if (controller.signal.aborted) {
                    return
                }
                setSnapshot({ requestVersion, state: { status: "success", sessions } })
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return
                }
                if (error instanceof DOMException && error.name === "AbortError") {
                    return
                }
                if (error instanceof OwnSessionsRequestError && error.status === 401) {
                    void reload()
                    return
                }
                setSnapshot({ requestVersion, state: { status: "error", error } })
            })

        return () => {
            controller.abort()
        }
    }, [requestVersion, reload])

    return { state, retry }
}
