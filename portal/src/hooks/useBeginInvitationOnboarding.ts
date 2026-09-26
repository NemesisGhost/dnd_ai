import { useCallback, useEffect, useRef, useState } from "react"
import {
    beginInvitationOnboarding,
    InvitationOnboardingRequestError,
} from "../api/invitationOnboarding"
import type { BeginInvitationOnboardingResponse } from "../types/invitationOnboarding"

export type BeginInvitationOnboardingStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success"; result: BeginInvitationOnboardingResponse }
    | { kind: "unavailable" }
    | { kind: "denied" }
    | { kind: "rate_limited" }
    | { kind: "error" }

export interface UseBeginInvitationOnboardingResult {
    status: BeginInvitationOnboardingStatus
    submit: (invitationToken: string) => void
    reset: () => void
}

const idleStatus: BeginInvitationOnboardingStatus = { kind: "idle" }

// Begins a single-link onboarding session for `invitationToken`.
// `invitationToken` is a plain function argument only, never retained in
// this hook's own state after the request resolves -- see
// PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §6.2's "Token elimination."
export function useBeginInvitationOnboarding(): UseBeginInvitationOnboardingResult {
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<BeginInvitationOnboardingStatus>(idleStatus)

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    const submit = useCallback(
        (invitationToken: string) => {
            if (status.kind === "pending") {
                return
            }

            const controller = new AbortController()
            controllerRef.current = controller
            setStatus({ kind: "pending" })

            void beginInvitationOnboarding(invitationToken, controller.signal)
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

                    if (cause instanceof InvitationOnboardingRequestError) {
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
        [status.kind],
    )

    const reset = useCallback(() => {
        setStatus(idleStatus)
    }, [])

    return { status, submit, reset }
}
