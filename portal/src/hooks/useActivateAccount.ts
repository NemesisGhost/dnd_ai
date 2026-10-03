import { useCallback, useEffect, useRef, useState } from "react"
import { activateAccount, ActivateAccountRequestError } from "../api/activateAccount"
import type { ActivateAccountResponse } from "../api/activateAccount"

export type ActivateAccountStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success"; result: ActivateAccountResponse }
    | { kind: "policy_violation" }
    | { kind: "unavailable" }
    | { kind: "rate_limited" }
    | { kind: "error" }

export interface UseActivateAccountResult {
    status: ActivateAccountStatus
    submit: (token: string, password: string) => void
    reset: () => void
}

const idleStatus: ActivateAccountStatus = { kind: "idle" }

// `onUnavailable` runs when final activation reports the token unusable, so the
// caller can drop its in-memory copy of the raw token.
export function useActivateAccount(onUnavailable?: () => void): UseActivateAccountResult {
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<ActivateAccountStatus>(idleStatus)

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    const submit = useCallback(
        (token: string, password: string) => {
            if (status.kind === "pending") {
                return
            }

            const controller = new AbortController()
            controllerRef.current = controller
            setStatus({ kind: "pending" })

            void activateAccount(token, password, controller.signal)
                .then((result) => {
                    if (controller.signal.aborted) {
                        return
                    }
                    setStatus({ kind: "success", result })
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }
                    if (cause instanceof ActivateAccountRequestError) {
                        if (cause.status === 400) {
                            setStatus({ kind: "policy_violation" })
                            return
                        }
                        // 404: unusable token. 409: the login name was claimed by
                        // another account (login_name_taken) -- the link can never
                        // succeed, so both are terminal and indistinguishable.
                        if (cause.status === 404 || cause.status === 409) {
                            onUnavailable?.()
                            setStatus({ kind: "unavailable" })
                            return
                        }
                        if (cause.status === 429) {
                            setStatus({ kind: "rate_limited" })
                            return
                        }
                    }
                    setStatus({ kind: "error" })
                })
        },
        [status.kind, onUnavailable],
    )

    const reset = useCallback(() => {
        controllerRef.current?.abort()
        setStatus(idleStatus)
    }, [])

    return { status, submit, reset }
}
