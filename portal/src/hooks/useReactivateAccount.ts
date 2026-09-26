import { useCallback, useEffect, useRef, useState } from "react"
import { PlatformAccountsRequestError } from "../api/platformAccounts"
import { reactivateAccount } from "../api/reactivateAccount"
import { useSession } from "../context/SessionContext"
import type { AccountLifecycleResponse } from "../types/platformAccounts"

export type ReactivateAccountStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "error" }

export interface UseReactivateAccountResult {
    status: ReactivateAccountStatus
    submit: (targetUserId: string) => void
    reset: () => void
}

const idleStatus: ReactivateAccountStatus = { kind: "idle" }

export function useReactivateAccount(
    onSuccess: (result: AccountLifecycleResponse) => void,
): UseReactivateAccountResult {
    const { state: sessionState, reload } = useSession()
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<ReactivateAccountStatus>(idleStatus)

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

            void reactivateAccount(
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
