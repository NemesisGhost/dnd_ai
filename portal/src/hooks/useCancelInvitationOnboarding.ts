import { useCallback, useEffect, useRef, useState } from "react"
import {
    cancelInvitationOnboarding,
    InvitationOnboardingRequestError,
} from "../api/invitationOnboarding"

export type CancelInvitationOnboardingStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "unavailable" }
    | { kind: "denied" }
    | { kind: "error" }

export interface UseCancelInvitationOnboardingResult {
    status: CancelInvitationOnboardingStatus
    submit: (onboardingCsrfToken: string) => void
    reset: () => void
}

const idleStatus: CancelInvitationOnboardingStatus = { kind: "idle" }

export function useCancelInvitationOnboarding(
    onSuccess: () => void,
): UseCancelInvitationOnboardingResult {
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<CancelInvitationOnboardingStatus>(idleStatus)

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    const submit = useCallback(
        (onboardingCsrfToken: string) => {
            if (status.kind === "pending") {
                return
            }

            const controller = new AbortController()
            controllerRef.current = controller
            setStatus({ kind: "pending" })

            void cancelInvitationOnboarding(onboardingCsrfToken, controller.signal)
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

                    if (cause instanceof InvitationOnboardingRequestError) {
                        if (cause.status === 404) {
                            setStatus({ kind: "unavailable" })
                            return
                        }
                        if (cause.status === 403) {
                            setStatus({ kind: "denied" })
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
