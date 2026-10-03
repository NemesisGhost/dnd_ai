import { useCallback, useEffect, useRef, useState } from "react"
import { PlatformAccountsRequestError } from "../api/platformAccounts"
import { revokeAllSessions } from "../api/revokeAllSessions"
import { useSession } from "../context/SessionContext"
import type { RevokeAllSessionsResponse } from "../types/platformAccounts"

export type RevokeAllSessionsStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "error" }

export interface UseRevokeAllSessionsResult {
    status: RevokeAllSessionsStatus
    submit: (targetUserId: string) => void
    reset: () => void
}

const idleStatus: RevokeAllSessionsStatus = { kind: "idle" }

export function useRevokeAllSessions(
    onSuccess: (result: RevokeAllSessionsResponse) => void,
): UseRevokeAllSessionsResult {
    const { state: sessionState, reload } = useSession()
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<RevokeAllSessionsStatus>(idleStatus)

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    const submit = useCallback(
        (targetUserId: string) => {
            if (status.kind === "pending") {
                return
            }
            if (sessionState.status !== "authenticated") {
                return
            }

            const controller = new AbortController()
            controllerRef.current = controller
            setStatus({ kind: "pending" })

            void revokeAllSessions(
                targetUserId,
                sessionState.bootstrap.csrf_token,
                controller.signal,
            )
                .then((result) => {
                    if (controller.signal.aborted) {
                        return
                    }
                    setStatus({ kind: "success" })
                    onSuccess(result)
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }
                    if (cause instanceof PlatformAccountsRequestError) {
                        if (cause.status === 401) {
                            setStatus(idleStatus)
                            void reload()
                            return
                        }
                        if (cause.status === 403 || cause.status === 404) {
                            setStatus({ kind: "denied" })
                            return
                        }
                    }
                    setStatus({ kind: "error" })
                })
        },
        [onSuccess, reload, sessionState, status.kind],
    )

    const reset = useCallback(() => {
        setStatus(idleStatus)
    }, [])

    return { status, submit, reset }
}
