import { useCallback, useEffect, useRef, useState } from "react"
import { createAccount } from "../api/createAccount"
import { PlatformAccountsRequestError } from "../api/platformAccounts"
import { useSession } from "../context/SessionContext"
import type { CreateAccountResponse } from "../types/platformAccounts"

export type CreateAccountStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "error" }

export interface UseCreateAccountResult {
    status: CreateAccountStatus
    submit: (loginName: string, displayName: string, email: string | null) => void
    reset: () => void
}

const idleStatus: CreateAccountStatus = { kind: "idle" }

export function useCreateAccount(
    onSuccess: (result: CreateAccountResponse) => void,
): UseCreateAccountResult {
    const { state: sessionState, reload } = useSession()
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<CreateAccountStatus>(idleStatus)

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    const submit = useCallback(
        (loginName: string, displayName: string, email: string | null) => {
            if (status.kind === "pending") {
                return
            }
            if (sessionState.status !== "authenticated") {
                return
            }

            const controller = new AbortController()
            controllerRef.current = controller
            setStatus({ kind: "pending" })

            void createAccount(
                loginName,
                displayName,
                email,
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
