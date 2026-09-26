import { useCallback, useEffect, useRef, useState } from "react"
import { disableAccount } from "../api/disableAccount"
import { PlatformAccountsRequestError } from "../api/platformAccounts"
import { useSession } from "../context/SessionContext"
import type { AccountLifecycleResponse } from "../types/platformAccounts"

export type DisableAccountStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "conflict"; message: string }
    | { kind: "error" }

export interface UseDisableAccountResult {
    status: DisableAccountStatus
    submit: (targetUserId: string) => void
    reset: () => void
}

const idleStatus: DisableAccountStatus = { kind: "idle" }

export function useDisableAccount(
    onSuccess: (result: AccountLifecycleResponse) => void,
): UseDisableAccountResult {
    const { state: sessionState, reload } = useSession()
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<DisableAccountStatus>(idleStatus)

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

            void disableAccount(targetUserId, sessionState.bootstrap.csrf_token, controller.signal)
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
                        if (cause.status === 409) {
                            // The platform's last active administrator --
                            // the one lifecycle-transition failure with a
                            // specific, safe-to-disclose reason (dnd_ai.
                            // commands.local_auth.
                            // LastActivePlatformAdministratorError).
                            setStatus({
                                kind: "conflict",
                                message:
                                    "This is the platform's only active administrator account and cannot be disabled.",
                            })
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
