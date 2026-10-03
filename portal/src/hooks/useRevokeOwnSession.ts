import { useCallback, useEffect, useRef, useState } from "react"
import { OwnSessionsRequestError, revokeOwnSession } from "../api/ownSessions"
import { useSession } from "../context/SessionContext"

export type RevokeOwnSessionStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "error" }

export interface UseRevokeOwnSessionResult {
    status: RevokeOwnSessionStatus
    submit: (browserSessionId: string, isCurrent: boolean) => void
    reset: () => void
}

const idleStatus: RevokeOwnSessionStatus = { kind: "idle" }

// DELETE /auth/sessions/{id} still returns a normal 204 even when the
// caller revokes their own current session -- the request's principal was
// already resolved before this handler ran, so revoking it mid-request
// does not retroactively fail the request itself; only the *next* request
// would see it gone. isCurrent (read from the session list this session
// came from) is threaded straight through to onSuccess so the page can
// decide that revoking the current session is an intentional sign-out
// (navigate to /login) rather than a recoverable error, while revoking
// any other session just refreshes the list.
export function useRevokeOwnSession(
    onSuccess: (browserSessionId: string, isCurrent: boolean) => void,
): UseRevokeOwnSessionResult {
    const { state: sessionState } = useSession()
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<RevokeOwnSessionStatus>(idleStatus)

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    const submit = useCallback(
        (browserSessionId: string, isCurrent: boolean) => {
            if (status.kind === "pending") {
                return
            }
            if (sessionState.status !== "authenticated") {
                return
            }

            const controller = new AbortController()
            controllerRef.current = controller
            setStatus({ kind: "pending" })

            void revokeOwnSession(
                browserSessionId,
                sessionState.bootstrap.csrf_token,
                controller.signal,
            )
                .then(() => {
                    if (controller.signal.aborted) {
                        return
                    }
                    setStatus({ kind: "success" })
                    onSuccess(browserSessionId, isCurrent)
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }
                    if (cause instanceof OwnSessionsRequestError) {
                        if (cause.status === 403 || cause.status === 404) {
                            setStatus({ kind: "denied" })
                            return
                        }
                    }
                    setStatus({ kind: "error" })
                })
        },
        [onSuccess, sessionState, status.kind],
    )

    const reset = useCallback(() => {
        setStatus(idleStatus)
    }, [])

    return { status, submit, reset }
}
