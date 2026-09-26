import { useCallback, useEffect, useRef, useState } from "react"
import {
    InvitationOnboardingRequestError,
    registerInvitedAccount,
} from "../api/invitationOnboarding"
import type { RegisterInvitedAccountResponse } from "../types/invitationOnboarding"

export type RegisterInvitedAccountStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success"; result: RegisterInvitedAccountResponse }
    | { kind: "policy_violation" }
    | { kind: "login_name_taken" }
    | { kind: "unavailable" }
    | { kind: "denied" }
    | { kind: "rate_limited" }
    | { kind: "error" }

export interface RegisterInvitedAccountInput {
    loginName: string
    displayName: string
    password: string
    onboardingCsrfToken: string
}

export interface UseRegisterInvitedAccountResult {
    status: RegisterInvitedAccountStatus
    submit: (input: RegisterInvitedAccountInput) => void
    reset: () => void
}

const idleStatus: RegisterInvitedAccountStatus = { kind: "idle" }

// `password` is a plain function argument only, held in this hook's own
// state for the life of the in-flight request and never persisted
// anywhere -- no storage, no log.
export function useRegisterInvitedAccount(
    onSuccess: (result: RegisterInvitedAccountResponse) => void,
): UseRegisterInvitedAccountResult {
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<RegisterInvitedAccountStatus>(idleStatus)

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    const submit = useCallback(
        (input: RegisterInvitedAccountInput) => {
            if (status.kind === "pending") {
                return
            }

            const controller = new AbortController()
            controllerRef.current = controller
            setStatus({ kind: "pending" })

            void registerInvitedAccount(
                input.loginName,
                input.displayName,
                input.password,
                input.onboardingCsrfToken,
                controller.signal,
            )
                .then((result) => {
                    if (controller.signal.aborted) {
                        return
                    }
                    setStatus({ kind: "success", result })
                    onSuccess(result)
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    if (cause instanceof InvitationOnboardingRequestError) {
                        if (cause.status === 400) {
                            setStatus({ kind: "policy_violation" })
                            return
                        }
                        if (cause.status === 409) {
                            setStatus({ kind: "login_name_taken" })
                            return
                        }
                        if (cause.status === 404) {
                            setStatus({ kind: "unavailable" })
                            return
                        }
                        if (cause.status === 403) {
                            setStatus({ kind: "denied" })
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
        [onSuccess, status.kind],
    )

    const reset = useCallback(() => {
        setStatus(idleStatus)
    }, [])

    return { status, submit, reset }
}
