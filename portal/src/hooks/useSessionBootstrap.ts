import { useEffect, useState } from "react"
import { fetchSessionBootstrap } from "../api/session"
import type { SessionBootstrap } from "../types/bootstrap"

export type SessionBootstrapState =
    | {
        status: "loading"
    }
    | {
        status: "authenticated"
        bootstrap: SessionBootstrap
    }
    | {
        status: "unauthenticated"
    }
    | {
        status: "error"
        error: Error
    }

const initialState: SessionBootstrapState = {
    status: "loading",
}

export function useSessionBootstrap(): SessionBootstrapState {
    const [state, setState] =
        useState<SessionBootstrapState>(initialState)

    useEffect(() => {
        const controller = new AbortController()

        void fetchSessionBootstrap(controller.signal)
            .then((bootstrap) => {
                if (controller.signal.aborted) {
                    return
                }

                if (bootstrap === null) {
                    setState({
                        status: "unauthenticated",
                    })
                    return
                }

                setState({
                    status: "authenticated",
                    bootstrap,
                })
            })
            .catch((cause: unknown) => {
                if (controller.signal.aborted) {
                    return
                }

                const error =
                    cause instanceof Error
                        ? cause
                        : new Error("Session bootstrap request failed")

                setState({
                    status: "error",
                    error,
                })
            })

        return () => {
            controller.abort()
        }
    }, [])

    return state
}