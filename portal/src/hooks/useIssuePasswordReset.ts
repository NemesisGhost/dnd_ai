import { useCallback, useEffect, useRef, useState } from "react"
import { issuePasswordReset } from "../api/issuePasswordReset"
import { PlatformAccountsRequestError } from "../api/platformAccounts"
import { useSession } from "../context/SessionContext"
import type { IssuePasswordResetResponse } from "../types/platformAccounts"

export type IssuePasswordResetStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "error" }

export interface UseIssuePasswordResetResult {
    status: IssuePasswordResetStatus
    submit: (targetUserId: string, revokeSessions: boolean) => void
    reset: () => void
}

const idleStatus: IssuePasswordResetStatus = { kind: "idle" }

export function useIssuePasswordReset(
    onSuccess: (result: IssuePasswordResetResponse) => void,
): UseIssuePasswordResetResult {
    const { state: sessionState, reload } = useSession()
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<IssuePasswordResetStatus>(idleStatus)

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    const submit = useCallback(
        (targetUserId: string, revokeSessions: boolean) => {
            if (status.kind === "pending") {
                return
            }
            if (sessionState.status !== "authenticated") {
                return
            }

            const controller = new AbortController()
            controllerRef.current = controller
            setStatus({ kind: "pending" })

            void issuePasswordReset(
                targetUserId,
                revokeSessions,
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
