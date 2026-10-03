import { useCallback, useEffect, useRef, useState } from "react"
import {
    completeInvitationOnboarding,
    InvitationOnboardingRequestError,
} from "../api/invitationOnboarding"
import { useSession } from "../context/SessionContext"
import type { CompleteInvitationOnboardingResponse } from "../types/invitationOnboarding"

export type CompleteInvitationOnboardingStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success"; result: CompleteInvitationOnboardingResponse }
    | { kind: "unavailable" }
    // R-5: a 401 here means the caller's session expired mid-flow. Unlike
    // the shared 401 handling elsewhere in the portal (which redirects to
    // /login), this route's own page must return to the sign-in/register
    // state *in place*, preserving the onboarding cookie -- never bounce
    // away from the invitation link. Reported as its own status so the
    // page can react without the hook making a routing decision itself.
    | { kind: "session_expired" }
    | { kind: "error" }

export interface UseCompleteInvitationOnboardingResult {
    status: CompleteInvitationOnboardingStatus
    submit: () => void
    reset: () => void
}

const idleStatus: CompleteInvitationOnboardingStatus = { kind: "idle" }

// The explicit confirm step for a visitor already signed in as some
// account (PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §7.1 S-1/S-4) --
// takes no arguments beyond the caller's own current session; the account
// this binds to is always whichever one `require_human_user_id` resolves
// server-side from the session cookie, never anything this hook asserts.
export function useCompleteInvitationOnboarding(): UseCompleteInvitationOnboardingResult {
    const { state: sessionState, reload } = useSession()
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<CompleteInvitationOnboardingStatus>(idleStatus)

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    const submit = useCallback(() => {
        if (status.kind === "pending") {
            return
        }
        if (sessionState.status !== "authenticated") {
            return
        }

        const controller = new AbortController()
        controllerRef.current = controller
        setStatus({ kind: "pending" })

        void completeInvitationOnboarding(sessionState.bootstrap.csrf_token, controller.signal)
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
                    if (cause.status === 401) {
                        setStatus({ kind: "session_expired" })
                        void reload()
                        return
                    }
                    if (cause.status === 404) {
                        setStatus({ kind: "unavailable" })
                        return
                    }
                }

                setStatus({ kind: "error" })
            })
    }, [reload, sessionState, status.kind])

    const reset = useCallback(() => {
        setStatus(idleStatus)
    }, [])

    return { status, submit, reset }
}
