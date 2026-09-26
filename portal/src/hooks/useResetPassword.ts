import { useCallback, useEffect, useRef, useState } from "react"
import { resetPassword, ResetPasswordRequestError } from "../api/resetPassword"
import type { ResetPasswordResponse } from "../api/resetPassword"

export type ResetPasswordStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success"; result: ResetPasswordResponse }
    | { kind: "policy_violation" }
    | { kind: "unavailable" }
    | { kind: "rate_limited" }
    | { kind: "error" }

export interface UseResetPasswordResult {
    status: ResetPasswordStatus
    submit: (token: string, newPassword: string) => void
    reset: () => void
}

const idleStatus: ResetPasswordStatus = { kind: "idle" }

export function useResetPassword(): UseResetPasswordResult {
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<ResetPasswordStatus>(idleStatus)

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    const submit = useCallback(
        (token: string, newPassword: string) => {
            if (status.kind === "pending") {
                return
            }

            const controller = new AbortController()
            controllerRef.current = controller
            setStatus({ kind: "pending" })

            void resetPassword(token, newPassword, controller.signal)
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
                    if (cause instanceof ResetPasswordRequestError) {
                        if (cause.status === 400) {
                            setStatus({ kind: "policy_violation" })
                            return
                        }
                        if (cause.status === 404) {
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
        [status.kind],
    )

    const reset = useCallback(() => {
        setStatus(idleStatus)
    }, [])

    return { status, submit, reset }
}
