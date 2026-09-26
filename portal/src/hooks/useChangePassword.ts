import { useCallback, useEffect, useRef, useState } from "react"
import { changePassword, ChangePasswordRequestError } from "../api/changePassword"
import { useSession } from "../context/SessionContext"

export type ChangePasswordStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "policy_violation" }
    | { kind: "error" }

export interface UseChangePasswordResult {
    status: ChangePasswordStatus
    submit: (currentPassword: string, newPassword: string) => void
    reset: () => void
}

const idleStatus: ChangePasswordStatus = { kind: "idle" }

export function useChangePassword(onSuccess: () => void): UseChangePasswordResult {
    const { state: sessionState } = useSession()
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<ChangePasswordStatus>(idleStatus)

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    const submit = useCallback(
        (currentPassword: string, newPassword: string) => {
            if (status.kind === "pending") {
                return
            }
            if (sessionState.status !== "authenticated") {
                return
            }

            const controller = new AbortController()
            controllerRef.current = controller
            setStatus({ kind: "pending" })

            void changePassword(
                currentPassword,
                newPassword,
                sessionState.bootstrap.csrf_token,
                controller.signal,
            )
                .then(() => {
                    if (controller.signal.aborted) {
                        return
                    }
                    setStatus({ kind: "success" })
                    onSuccess()
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }
                    if (cause instanceof ChangePasswordRequestError) {
                        if (cause.status === 401) {
                            // A wrong current password, not an expired
                            // session -- require_human_user_id already
                            // authorized this request before change_password
                            // ever ran, so this 401 means the caller
                            // mistyped their own current password.
                            // Deliberately does not reload the session the
                            // way other hooks' 401 handling does.
                            setStatus({ kind: "denied" })
                            return
                        }
                        if (cause.status === 400) {
                            setStatus({ kind: "policy_violation" })
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
